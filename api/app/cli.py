"""Operational CLI: run migrations, seed the first admin, provision a workspace."""

from __future__ import annotations

import typer

from api.app.db.migrate import upgrade_all
from api.app.models.public import StaffRole
from api.app.services.provisioning import create_workspace
from api.app.services.staff import seed_first_admin

app = typer.Typer(help="VisionGuard admin CLI", no_args_is_help=True)


@app.callback()
def _main() -> None:
    """Configure structured, scrubbed logging for every CLI command (incl. the migrate release
    step) so nothing sensitive leaks to deploy logs."""
    from api.app.obs.logging import configure_logging

    configure_logging()


@app.command()
def migrate() -> None:
    """Apply migrations to the public schema and every tenant schema."""
    upgrade_all()
    typer.echo("migrations applied to public + all tenant schemas")


@app.command("seed-first-admin")
def seed_first_admin_cmd(
    email: str = typer.Option(..., help="Admin email"),
    clerk_user_id: str = typer.Option(..., help="Clerk user id (sub claim)"),
) -> None:
    """Create the very first admin. Refuses if any staff already exist."""
    staff = seed_first_admin(clerk_user_id=clerk_user_id, email=email)
    typer.echo(f"created admin staff id={staff.id} ({staff.email})")


@app.command("seed-demo")
def seed_demo_cmd() -> None:
    """Seed a clickable demo: a workspace, an authorized+consenting subject, five
    fingerprinted images, and discovery candidates (fake providers) for the review inbox.
    Idempotent. Requires migrations applied and a shared object store (MinIO/R2)."""
    from api.app.demo import seed_demo

    result = seed_demo()
    typer.echo(
        f"demo ready: workspace '{result.workspace_slug}' (id={result.workspace_id}, "
        f"schema={result.schema})\n"
        f"  subject id={result.subject_id}, assets={result.assets}\n"
        f"  review inbox: {result.pending_candidates} pending, "
        f"{result.auto_dismissed} auto-dismissed (allowlisted)"
    )


@app.command("create-workspace")
def create_workspace_cmd(
    name: str = typer.Option(..., help="Workspace display name"),
    slug: str = typer.Option(..., help="Unique slug"),
    plan: str = typer.Option("starter", help="Plan"),
) -> None:
    """Provision a workspace and its tenant schema."""
    ws = create_workspace(name=name, slug=slug, plan=plan)
    typer.echo(f"created workspace id={ws.id} slug={ws.slug} schema={ws.schema_name}")


@app.command("verify-evidence")
def verify_evidence_cmd(
    workspace_id: int = typer.Option(..., help="Workspace id"),
    case_id: int = typer.Option(..., help="Case id"),
    capture_id: int = typer.Option(..., help="Evidence capture id"),
) -> None:
    """Standalone re-check of a capture: re-hash every artifact + verify the timestamp token."""
    from api.app.db.base import schema_for_workspace
    from api.app.db.session import tenant_session
    from api.app.services import evidence as svc

    schema = schema_for_workspace(workspace_id)
    with tenant_session(schema) as session:
        capture = svc.get_capture(session, capture_id)
        if capture is None or capture.case_id != case_id:
            raise typer.BadParameter("capture not found for that case")
        result = svc.verify_capture(
            session, schema=schema, capture=capture, actor_staff_id=None, reason="cli verify"
        )
    for name, ok in result.files.items():
        typer.echo(f"{'OK  ' if ok else 'BAD '} {name}")
    typer.echo(f"manifest: {'OK' if result.manifest_ok else 'BAD'}")
    typer.echo(f"timestamp: {result.timestamp_ok}")
    typer.echo("VERIFIED" if result.ok else "VERIFICATION FAILED")
    raise typer.Exit(0 if result.ok else 1)


@app.command("mint-token")
def mint_token_cmd(
    clerk_user_id: str = typer.Option(..., help="Staff clerk_user_id (the token 'sub')"),
    azp: str = typer.Option(
        "http://localhost:5173", help="Authorized party; must match an ALLOWED_ORIGINS entry"
    ),
) -> None:
    """Print a local bearer token for API calls WITHOUT Clerk. Only works when
    AUTH_TEST_MODE=1 (dev/test). Use it as: Authorization: Bearer <token>."""
    from api.app.auth.clerk import make_test_token
    from api.app.config import get_settings

    if not get_settings().auth_test_mode:
        raise typer.BadParameter("AUTH_TEST_MODE must be 1 to mint local tokens")
    typer.echo(make_test_token(clerk_user_id, azp=azp))


@app.command("sample-report")
def sample_report_cmd(
    out: str = typer.Option("sample-report.pdf", help="Where to write the PDF"),
    subject_id: int | None = typer.Option(None, help="Per-subject report (default: whole ws)"),
    start: str = typer.Option("2020-01-01", help="Period start (YYYY-MM-DD)"),
    end: str = typer.Option("2030-12-31", help="Period end (YYYY-MM-DD)"),
) -> None:
    """Seed the demo workspace, generate an agency report for it, and write the PDF locally.

    Backs the Slice-10 'done when' (a sample agency report from the demo workspace). Requires a
    SHARED object store (STORAGE_BACKEND=s3 / MinIO) so the sealed PDF is readable back."""
    from datetime import date

    from api.app.db.session import tenant_session
    from api.app.demo import seed_demo
    from api.app.services import reports as reports_svc

    demo = seed_demo()
    with tenant_session(demo.schema) as session:
        report = reports_svc.generate_report(
            session, schema=demo.schema, workspace_id=demo.workspace_id, subject_id=subject_id,
            start=date.fromisoformat(start), end=date.fromisoformat(end),
            actor_staff_id=None, include_thumbnails=False,
        )
        pdf, _ = reports_svc.read_artifact(report, which="pdf")
    with open(out, "wb") as fh:
        fh.write(pdf)
    typer.echo(
        f"report id={report.id} for workspace '{demo.workspace_slug}' written to {out} "
        f"({len(pdf)} bytes, sha256={report.pdf_sha256[:12]}…)"
    )


def _resolve_schema(workspace_id: int) -> str:
    """Look up the workspace in public and return its tenant schema, or fail with a clear error."""
    from api.app.db.session import public_session
    from api.app.models.public import Workspace

    with public_session() as session:
        ws = session.get(Workspace, workspace_id)
        if ws is None:
            raise typer.BadParameter(f"workspace {workspace_id} not found")
        return ws.schema_name


@app.command("requeue-pending-assets")
def requeue_pending_assets_cmd(
    workspace: int = typer.Option(..., "--workspace", help="Workspace id"),
) -> None:
    """Re-enqueue fingerprinting for assets stuck in 'pending' (e.g. after a broken worker)."""
    from api.app.db.session import tenant_session
    from api.app.services import assets as asset_service

    schema = _resolve_schema(workspace)
    with tenant_session(schema) as session:
        count = asset_service.requeue_pending_assets(session, workspace_id=workspace)
    typer.echo(f"re-queued {count} pending asset(s) in workspace {workspace}")


@app.command("reprocess-assets")
def reprocess_assets_cmd(
    workspace: int = typer.Option(..., "--workspace", help="Workspace id"),
    subject: int | None = typer.Option(None, "--subject", help="Limit to one subject id"),
) -> None:
    """Re-derive thumbnail/pHash/embedding for 'ready' assets (e.g. to backfill the EXIF fix)."""
    from api.app.db.session import tenant_session
    from api.app.services import assets as asset_service

    schema = _resolve_schema(workspace)
    with tenant_session(schema) as session:
        count = asset_service.reprocess_assets(
            session, workspace_id=workspace, subject_id=subject
        )
    typer.echo(f"enqueued reprocess for {count} asset(s) in workspace {workspace}")


@app.command("purge-unconsented-embeddings")
def purge_unconsented_embeddings_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Count only; make no changes"),
) -> None:
    """Null CLIP embeddings for assets + discovery candidates whose subject lacks active biometric
    consent (or is geo-blocked), across EVERY workspace. One-time cleanup (CLAUDE.md #1); writes a
    biometrics.purged audit per affected subject."""
    from sqlalchemy import select

    from api.app.db.session import public_session, tenant_session
    from api.app.models.public import Workspace
    from api.app.services.biometrics import purge_unconsented_embeddings

    with public_session() as session:
        workspaces = [
            (w.id, w.schema_name)
            for w in session.scalars(select(Workspace).order_by(Workspace.id))
        ]

    total_subjects = 0
    total_embeddings = 0
    for workspace_id, schema in workspaces:
        with tenant_session(schema) as session:
            affected = purge_unconsented_embeddings(
                session, workspace_id=workspace_id, actor_staff_id=None, dry_run=dry_run
            )
        if affected:
            n = sum(affected.values())
            total_subjects += len(affected)
            total_embeddings += n
            typer.echo(
                f"  workspace {workspace_id} ({schema}): "
                f"{len(affected)} subject(s), {n} embedding(s)"
            )
    verb = "would clear" if dry_run else "cleared"
    prefix = "[dry-run] " if dry_run else ""
    typer.echo(
        f"{prefix}{verb} {total_embeddings} embedding(s) across {total_subjects} subject(s) "
        f"in {len(workspaces)} workspace(s)"
    )


# StaffRole is re-exported for convenience in future subcommands.
__all__ = ["app", "StaffRole"]


if __name__ == "__main__":
    app()
