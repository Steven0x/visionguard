"""Operational CLI: run migrations, seed the first admin, provision a workspace."""

from __future__ import annotations

import typer

from api.app.db.migrate import upgrade_all
from api.app.models.public import StaffRole
from api.app.services.provisioning import create_workspace
from api.app.services.staff import seed_first_admin

app = typer.Typer(help="VisionGuard admin CLI", no_args_is_help=True)


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


@app.command("create-workspace")
def create_workspace_cmd(
    name: str = typer.Option(..., help="Workspace display name"),
    slug: str = typer.Option(..., help="Unique slug"),
    plan: str = typer.Option("starter", help="Plan"),
) -> None:
    """Provision a workspace and its tenant schema."""
    ws = create_workspace(name=name, slug=slug, plan=plan)
    typer.echo(f"created workspace id={ws.id} slug={ws.slug} schema={ws.schema_name}")


# StaffRole is re-exported for convenience in future subcommands.
__all__ = ["app", "StaffRole"]


if __name__ == "__main__":
    app()
