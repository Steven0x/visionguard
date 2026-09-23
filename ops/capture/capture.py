#!/usr/bin/env python3
"""
VisionGuard evidence capture (ops tool, day-1 version).

Captures a web page as evidence: full-page screenshot, raw HTML, MHTML page
archive and metadata. It hashes every file (SHA-256), writes a manifest, and
gets an RFC 3161 trusted timestamp over the manifest.

Usage:
  python capture.py capture --case VG-0001 --subject "Jane Doe" URL [URL ...]
  python capture.py capture --case VG-0001 --subject "Jane Doe" --file urls.txt
  python capture.py verify evidence/VG-0001/20260923T141500Z_1

Output (per URL):
  evidence/<case>/<UTC stamp>_<n>/
    screenshot.png   full-page screenshot
    page.html        rendered DOM at capture time
    page.mhtml       self-contained page archive (Chromium snapshot)
    meta.json        URL, final URL, HTTP status, title, headers, capturer, times
    manifest.json    SHA-256 of every file above + capture summary
    manifest.tsr     RFC 3161 timestamp token over manifest.json (if a TSA answered)
    timestamp.json   which TSA answered, when, and the token's hash
  evidence/evidence_log.csv   one row per capture (append-only)

Evidence rules: never edit files in a capture folder. If a page changes,
capture it again; the new capture is a new folder.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import json
import platform
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOL_VERSION = "vg-capture/0.1.0"

# TSAs tried in order; the first one that answers wins.
TSA_URLS = [
    "https://freetsa.org/tsr",
    "http://timestamp.digicert.com",
    "http://timestamp.sectigo.com",
]

EVIDENCE_FILES = ["screenshot.png", "page.html", "page.mhtml", "meta.json"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_rfc3161_token(data: bytes) -> tuple[bytes | None, str | None, str | None]:
    """Return (token, tsa_url, error). Never raises: evidence is still saved if every TSA fails."""
    try:
        import rfc3161ng
    except ImportError:
        return None, None, "rfc3161ng not installed (pip install rfc3161ng)"
    errors = []
    for url in TSA_URLS:
        try:
            ts = rfc3161ng.RemoteTimestamper(
                url, hashname="sha256", include_tsa_certificate=True, timeout=20
            )
            token = ts.timestamp(data=data)
            # Sanity check: the token must match our data and its signature must be valid.
            rfc3161ng.check_timestamp(token, data=data, hashname="sha256")
            return token, url, None
        except Exception as e:  # try the next TSA
            errors.append(f"{url}: {type(e).__name__}: {e}")
    return None, None, " | ".join(errors)


def capture_one(page, url: str, out_dir: Path, case: str, subject: str, note: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    started = utc_now()

    status, headers, error = None, {}, None
    try:
        resp = page.goto(url, wait_until="networkidle", timeout=45_000)
    except Exception:
        # Some pages never go idle (live feeds, ads): fall back to DOM ready.
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as e:
            resp, error = None, f"{type(e).__name__}: {e}"
    if resp is not None:
        status = resp.status
        try:
            headers = resp.all_headers()
        except Exception:
            headers = dict(resp.headers)
    page.wait_for_timeout(2500)  # let lazy images and late JS settle

    page.screenshot(path=str(out_dir / "screenshot.png"), full_page=True)
    (out_dir / "page.html").write_text(page.content(), encoding="utf-8")
    try:
        cdp = page.context.new_cdp_session(page)
        snap = cdp.send("Page.captureSnapshot", {"format": "mhtml"})
        (out_dir / "page.mhtml").write_text(snap["data"], encoding="utf-8")
    except Exception as e:
        (out_dir / "page.mhtml").write_text(f"MHTML capture failed: {e}", encoding="utf-8")

    finished = utc_now()
    meta = {
        "case_id": case,
        "subject": subject,
        "note": note,
        "requested_url": url,
        "final_url": page.url,
        "http_status": status,
        "load_error": error,
        "page_title": page.title(),
        "response_headers": headers,
        "viewport": page.viewport_size,
        "user_agent": page.evaluate("navigator.userAgent"),
        "capture_started_utc": started.isoformat(),
        "capture_finished_utc": finished.isoformat(),
        "captured_by": getpass.getuser(),
        "machine": socket.gethostname(),
        "os": platform.platform(),
        "tool": TOOL_VERSION,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    manifest = {
        "case_id": case,
        "requested_url": url,
        "final_url": page.url,
        "capture_finished_utc": finished.isoformat(),
        "tool": TOOL_VERSION,
        "hash_algorithm": "sha256",
        "files": {name: sha256_file(out_dir / name) for name in EVIDENCE_FILES},
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    (out_dir / "manifest.json").write_bytes(manifest_bytes)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()

    token, tsa_url, tsa_error = get_rfc3161_token(manifest_bytes)
    ts_info = {
        "manifest_sha256": manifest_hash,
        "tsa_url": tsa_url,
        "requested_utc": utc_now().isoformat(),
        "status": "ok" if token else "failed",
        "error": tsa_error,
    }
    if token:
        (out_dir / "manifest.tsr").write_bytes(token)
        ts_info["token_sha256"] = hashlib.sha256(token).hexdigest()
        try:
            import rfc3161ng
            ts_info["tsa_time_utc"] = rfc3161ng.get_timestamp(token).isoformat()
        except Exception:
            pass
    (out_dir / "timestamp.json").write_text(json.dumps(ts_info, indent=2), encoding="utf-8")

    load_ok = error is None and not page.url.startswith("chrome-error://") and (status is None or status < 400)
    return {
        "load_ok": load_ok,
        "case_id": case,
        "subject": subject,
        "url": url,
        "final_url": page.url,
        "http_status": status,
        "captured_utc": finished.isoformat(),
        "folder": str(out_dir),
        "manifest_sha256": manifest_hash,
        "timestamp": ts_info["status"],
        "tsa_time_utc": ts_info.get("tsa_time_utc", ""),
        "note": note,
    }


def append_log(log_path: Path, row: dict) -> None:
    new = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def cmd_capture(args) -> int:
    from playwright.sync_api import sync_playwright

    urls = list(args.urls)
    if args.file:
        urls += [
            line.strip()
            for line in Path(args.file).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    if not urls:
        print("No URLs given.", file=sys.stderr)
        return 2

    root = Path(args.out)
    case_dir = root / args.case
    case_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")

    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
        page = context.new_page()
        for i, url in enumerate(urls, 1):
            out_dir = case_dir / f"{stamp}_{i}"
            try:
                row = capture_one(page, url, out_dir, args.case, args.subject, args.note)
                append_log(root / "evidence_log.csv", row)
                if not row["load_ok"]:
                    failures += 1
                    print(f"[{i}/{len(urls)}] LOAD FAILED (status {row['http_status']}, final {row['final_url']}) {url} -> {out_dir}  "
                          "[page may need login: retry with --headed, or screenshot by hand]", file=sys.stderr)
                    continue
                flag = "" if row["timestamp"] == "ok" else "  [NO TIMESTAMP - re-run later]"
                print(f"[{i}/{len(urls)}] OK  {url}  ->  {out_dir}{flag}")
            except Exception as e:
                failures += 1
                print(f"[{i}/{len(urls)}] FAIL {url}: {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(1)
        browser.close()
    return 1 if failures else 0


def cmd_verify(args) -> int:
    folder = Path(args.folder)
    manifest_bytes = (folder / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    ok = True
    for name, expected in manifest["files"].items():
        actual = sha256_file(folder / name)
        match = actual == expected
        ok &= match
        print(f"{'OK  ' if match else 'BAD '} {name}  {actual}")

    tsr = folder / "manifest.tsr"
    if tsr.exists():
        try:
            import rfc3161ng
            token = tsr.read_bytes()
            rfc3161ng.check_timestamp(token, data=manifest_bytes, hashname="sha256")
            print(f"OK   timestamp  {rfc3161ng.get_timestamp(token).isoformat()} (signature and imprint valid)")
        except Exception as e:
            ok = False
            print(f"BAD  timestamp  {type(e).__name__}: {e}")
    else:
        print("WARN no timestamp token in this capture")

    print("VERIFIED" if ok else "VERIFICATION FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="VisionGuard evidence capture")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture", help="capture one or more URLs as evidence")
    c.add_argument("urls", nargs="*")
    c.add_argument("--file", help="text file with one URL per line")
    c.add_argument("--case", required=True, help="case ID from the tracker, e.g. VG-0001")
    c.add_argument("--subject", required=True, help="talent name as in the tracker")
    c.add_argument("--note", default="", help="short note, e.g. 'impersonation account'")
    c.add_argument("--out", default="evidence", help="evidence root folder (default: ./evidence)")
    c.add_argument("--headed", action="store_true", help="show the browser (for pages needing a login)")
    c.set_defaults(func=cmd_capture)

    v = sub.add_parser("verify", help="re-check hashes and the timestamp of a capture folder")
    v.add_argument("folder")
    v.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
