"""Slice 14 design screenshots.

Captures every main staff-console and agency-portal screen to a directory (default
docs/design/before). Reuses the existing AUTH_TEST_MODE Clerk bypass: it mints HS256 test
tokens for the demo admin + a demo agency user and injects them into the SPA's localStorage
(the frontend reads `vg_dev_token` when VITE_DEV_AUTH=1 — see web/src/useToken.ts).

Prereqs (started separately, see the slice notes):
  * Postgres with `make seed-demo` already run.
  * A capture API:  APP_ENV=dev AUTH_TEST_MODE=1 ALLOWED_ORIGINS=http://localhost:5174
                    uvicorn api.app.main:app --port 8001
  * A capture web:  VITE_DEV_AUTH=1 VITE_API_BASE_URL=http://localhost:8001
                    npm --prefix web run dev -- --port 5174

Usage:  python scripts/design_capture.py [out_dir] [web_base]
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

from api.app.auth.clerk import make_test_token
from api.app.db.session import public_session
from api.app.models.public import Staff, StaffRole, Workspace
from api.app.services import agency_users as agency_svc

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/design/before")
WEB = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:5174"
AZP = "http://localhost:5174"
DEMO_SLUG = "demo-agency"
AGENCY_CLERK_ID = "dev_capture_agency"
AGENCY_EMAIL = "agency@demo.invalid"


def _setup_tokens() -> tuple[str, str]:
    """Resolve the admin identity + ensure a demo agency user; return (admin_token, agency_token)."""
    with public_session() as session:
        admin = session.scalar(
            select(Staff).where(Staff.role == StaffRole.admin).order_by(Staff.id)
        )
        if admin is None:
            raise SystemExit("no admin Staff — run `make seed-admin` first")
        admin_sub = admin.clerk_user_id

        ws = session.scalar(select(Workspace).where(Workspace.slug == DEMO_SLUG))
        if ws is None:
            raise SystemExit("no demo workspace — run `make seed-demo` first")
        existing = session.scalar(
            select(Staff).where(Staff.clerk_user_id == AGENCY_CLERK_ID)
        )
        if existing is None:
            agency_svc.create_agency_user(
                session, workspace_id=ws.id, clerk_user_id=AGENCY_CLERK_ID, email=AGENCY_EMAIL
            )
            session.commit()
    return (
        make_test_token(admin_sub, azp=AZP, expires_in=86400),
        make_test_token(AGENCY_CLERK_ID, azp=AZP, expires_in=86400),
    )


def main() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    admin_token, agency_token = _setup_tokens()

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def shot(page, name: str, *, full: bool = True) -> None:
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=full)
            print("captured", name)

        def el_shot(page, selector: str, name: str) -> None:
            try:
                page.locator(selector).first.screenshot(path=str(OUT / f"{name}.png"))
                print("captured", name)
            except Exception as exc:  # noqa: BLE001 - best-effort per element
                print("skip", name, exc)

        def new_page(token: str, width: int = 1440, height: int = 900, theme: str = "light"):
            ctx = browser.new_context(viewport={"width": width, "height": height})
            ctx.add_init_script(
                f"localStorage.setItem('vg_dev_token', {token!r});"
                f"localStorage.setItem('vg_theme', {theme!r});"
            )
            return ctx, ctx.new_page()

        def open_workspace(page) -> None:
            page.get_by_role("heading", name="Workspaces").wait_for(timeout=15000)
            page.get_by_role("button", name="Demo Agency").first.click()
            page.get_by_role("heading", name="Review inbox", exact=True).wait_for(timeout=15000)
            page.wait_for_timeout(1200)

        def nav(page, label: str) -> None:
            page.get_by_role("button", name=label, exact=True).first.click()
            page.wait_for_timeout(1200)

        # ---- Staff console (light) ----
        ctx, page = new_page(admin_token)
        page.goto(WEB)
        page.get_by_role("heading", name="Workspaces").wait_for(timeout=15000)
        shot(page, "staff-workspace-list")

        open_workspace(page)
        shot(page, "staff-review-inbox")
        el_shot(page, '[data-testid="review-inbox"]', "staff-review-inbox-panel")

        nav(page, "Cases")
        shot(page, "staff-cases")
        try:
            page.get_by_role("button", name="open").first.click()
            page.get_by_role("button", name="← Cases").wait_for(timeout=10000)
            page.wait_for_timeout(1000)
            shot(page, "staff-case-detail")
            el_shot(page, '[data-testid="evidence-section"]', "staff-evidence-section")
        except Exception as exc:  # noqa: BLE001
            print("skip staff-case-detail", exc)

        nav(page, "Follow-ups")
        shot(page, "staff-followups")
        nav(page, "Reports")
        shot(page, "staff-reports")
        nav(page, "Subjects")
        shot(page, "staff-subjects")
        try:
            page.get_by_role("button", name="Demo Subject").first.click()
            page.wait_for_timeout(1500)
            shot(page, "staff-subject-detail")
        except Exception as exc:  # noqa: BLE001
            print("skip staff-subject-detail", exc)
        nav(page, "Settings")
        shot(page, "staff-settings")
        ctx.close()

        # ---- Staff console (dark) — the review inbox ----
        ctx, page = new_page(admin_token, theme="dark")
        page.goto(WEB)
        open_workspace(page)
        shot(page, "staff-review-inbox-dark")
        ctx.close()

        # Tablet width.
        ctx, page = new_page(admin_token, width=1024, height=768)
        page.goto(WEB)
        open_workspace(page)
        shot(page, "staff-review-inbox-tablet")
        ctx.close()

        # ---- Agency portal (light) ----
        ctx, page = new_page(agency_token)
        page.goto(WEB)
        page.get_by_text("Demo Agency").first.wait_for(timeout=15000)
        page.wait_for_timeout(1200)
        shot(page, "portal-cases")
        for tab, name in [
            ("Subjects", "portal-subjects"),
            ("Needs from you", "portal-needs"),
            ("Reports", "portal-reports"),
            ("Billing", "portal-billing"),
        ]:
            try:
                page.get_by_role("tab", name=tab).first.click()
                page.wait_for_timeout(1200)
                shot(page, name)
            except Exception as exc:  # noqa: BLE001
                print("skip", name, exc)
        try:
            page.get_by_role("tab", name="Cases").first.click()
            page.wait_for_timeout(800)
            page.get_by_role("button", name="Case #1").first.click()
            page.wait_for_timeout(1000)
            shot(page, "portal-case-detail")
        except Exception as exc:  # noqa: BLE001
            print("skip portal-case-detail", exc)
        ctx.close()

        # ---- Agency portal (dark + phone) ----
        ctx, page = new_page(agency_token, theme="dark")
        page.goto(WEB)
        page.get_by_text("Demo Agency").first.wait_for(timeout=15000)
        page.wait_for_timeout(1200)
        shot(page, "portal-cases-dark")
        ctx.close()

        ctx, page = new_page(agency_token, width=390, height=844)
        page.goto(WEB)
        page.get_by_text("Demo Agency").first.wait_for(timeout=15000)
        page.wait_for_timeout(1200)
        shot(page, "portal-mobile-cases")
        ctx.close()

        browser.close()
    print("done →", OUT)


if __name__ == "__main__":
    main()
