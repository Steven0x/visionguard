#!/usr/bin/env python
"""Post-deploy smoke test: exercise the core path end-to-end against a running deployment.

    python scripts/smoke.py --base-url https://visionguard-api-staging.fly.dev --token "$TOKEN"

Steps (each asserted): readiness → create workspace → add an agent authorization → add a subject →
upload one image → run a manual URL intake → generate a report. The token is a staff Clerk session
token (an ADMIN — creating a workspace and reading it needs all-workspaces access). On staging you
can mint one; in production use a real staff session. Exits non-zero on the first failure and never
prints the token.
"""

from __future__ import annotations

import argparse
import io
import sys
from datetime import date, timedelta

import httpx

# A minimal valid 1x1 PNG (passes image sniffing + PIL decode at the upload choke point).
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000"
    "000c49444154789c63a8afaf070002fe017eba2570250000000049454e44ae426082"
)


def _fail(step: str, resp: httpx.Response) -> None:
    # Show status + a short body snippet for debugging; never echo request auth.
    print(f"FAIL  {step}: HTTP {resp.status_code} {resp.text[:300]}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="VisionGuard post-deploy smoke test")
    parser.add_argument("--base-url", required=True, help="API base URL, e.g. https://…fly.dev")
    parser.add_argument("--token", required=True, help="staff (admin) Clerk session token")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    client = httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {args.token}"},
        timeout=args.timeout,
    )

    # 1. Readiness (unauthenticated).
    r = httpx.get(f"{base}/readyz", timeout=args.timeout)
    if r.status_code != 200:
        _fail("readyz", r)
    print("OK    readyz:", r.json().get("checks"))

    # 2. Create a workspace.
    r = client.post("/workspaces", json={"name": "Smoke Test Agency", "plan": "starter"})
    if r.status_code != 201:
        _fail("create workspace", r)
    ws = r.json()["id"]
    print(f"OK    workspace #{ws}")

    # 3. Workspace-level agent authorization → subjects become enforceable (required for intake).
    r = client.post(
        f"/workspaces/{ws}/authorizations",
        data={"signer_name": "Smoke Signer", "authorized_date": date.today().isoformat()},
    )
    if r.status_code != 201:
        _fail("create authorization", r)
    print("OK    agent authorization")

    # 4. Add a subject.
    r = client.post(
        f"/workspaces/{ws}/subjects",
        json={"legal_name": "Smoke Subject", "residence_state": "CA"},
    )
    if r.status_code != 201:
        _fail("create subject", r)
    subject = r.json()["id"]
    print(f"OK    subject #{subject}")

    # 5. Upload one image (must pass the CSAM gate before it is stored).
    r = client.post(
        f"/workspaces/{ws}/subjects/{subject}/assets",
        files={"file": ("smoke.png", io.BytesIO(_PNG_1x1), "image/png")},
    )
    if r.status_code != 201:
        _fail("upload image", r)
    print(f"OK    asset #{r.json()['id']}")

    # 6. Manual URL intake.
    r = client.post(
        f"/workspaces/{ws}/subjects/{subject}/discovery/intake",
        json={"urls": ["https://example.com/smoke-check"]},
    )
    if r.status_code != 200:
        _fail("url intake", r)
    print(f"OK    intake run #{r.json()['id']}")

    # 7. Generate a report over the last 30 days.
    today = date.today()
    r = client.post(
        f"/workspaces/{ws}/reports",
        json={"start": (today - timedelta(days=30)).isoformat(), "end": today.isoformat()},
    )
    if r.status_code != 201:
        _fail("generate report", r)
    print(f"OK    report #{r.json()['id']}")

    print("\nSMOKE PASSED")


if __name__ == "__main__":
    main()
