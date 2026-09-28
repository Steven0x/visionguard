"""public schema: channel registry + notice templates (global reference data)

Revision ID: 0014_public
Revises: 0013_tenant
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.app.db.migration_scope import current_scope
from api.app.notices_matrix import method_allowed_for_claim
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014_public"
down_revision: str | None = "0013_tenant"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ── Seed data ─────────────────────────────────────────────────────────────────
# Routing obeys docs/legal/claims-matrix.md. Only `copyright` uses an email/DMCA channel;
# trademark/likeness/ncii/impersonation are platform-form only (never DMCA). Each row is
# asserted against notices_matrix.method_allowed_for_claim before insert.
_CHANNELS: list[dict] = [
    # The one email/DMCA channel: copyright only.
    {
        "platform": "generic_host",
        "claim_type": "copyright",
        "method": "email",
        "destination": "abuse@example-host.invalid",
        "required_fields": ["agent_name", "agent_email", "infringing_urls", "work_description"],
        "notes": "DMCA email to the host/CDN abuse or designated-agent address "
        "(footer/WHOIS lookup). Replace destination per host at send time.",
    },
    {"platform": "instagram", "claim_type": "copyright", "method": "web_form",
     "destination": "https://help.instagram.com/contact/552695131608132", "required_fields": None,
     "notes": "Instagram copyright report form."},
    {"platform": "instagram", "claim_type": "impersonation", "method": "web_form",
     "destination": "https://help.instagram.com/contact/636276399721841", "required_fields": None,
     "notes": "Instagram impersonation form (needs subject ID)."},
    {"platform": "instagram", "claim_type": "ncii", "method": "web_form",
     "destination": "https://help.instagram.com/contact/1417563077438681",
     "required_fields": None, "notes": "Instagram intimate-image / Take It Down process."},
    {"platform": "instagram", "claim_type": "likeness", "method": "web_form",
     "destination": "https://help.instagram.com/contact/636276399721841", "required_fields": None,
     "notes": "Instagram privacy/IP form."},
    {"platform": "facebook", "claim_type": "copyright", "method": "web_form",
     "destination": "https://www.facebook.com/help/contact/1758255661104383",
     "required_fields": None, "notes": "Facebook IP report."},
    {"platform": "facebook", "claim_type": "ncii", "method": "web_form",
     "destination": "https://www.facebook.com/help/contact/567360146613371",
     "required_fields": None, "notes": "Facebook intimate-image process."},
    {"platform": "tiktok", "claim_type": "copyright", "method": "web_form",
     "destination": "https://www.tiktok.com/legal/report/Copyright", "required_fields": None,
     "notes": "TikTok copyright IP report."},
    {"platform": "tiktok", "claim_type": "impersonation", "method": "web_form",
     "destination": "https://www.tiktok.com/legal/report/impersonation", "required_fields": None,
     "notes": "TikTok impersonation report."},
    {"platform": "x", "claim_type": "copyright", "method": "web_form",
     "destination": "https://help.x.com/forms/dmca", "required_fields": None,
     "notes": "X DMCA/copyright form."},
    {"platform": "x", "claim_type": "impersonation", "method": "web_form",
     "destination": "https://help.x.com/forms/impersonation", "required_fields": None,
     "notes": "X impersonation form."},
    {"platform": "google_search", "claim_type": "copyright", "method": "web_form",
     "destination": "https://support.google.com/legal/troubleshooter/1114905",
     "required_fields": None, "notes": "Google copyright removal (delist)."},
    {"platform": "google_search", "claim_type": "ncii", "method": "web_form",
     "destination": "https://support.google.com/websearch/answer/13650142", "required_fields": None,
     "notes": "Google explicit/intimate image removal."},
    # Trademark is platform-form only (Brands mode, Phase 2). Present to prove routing never
    # sends it to DMCA/email.
    {"platform": "amazon", "claim_type": "trademark", "method": "web_form",
     "destination": "https://brandservices.amazon.com/", "required_fields": None,
     "notes": "Amazon Brand Registry / trademark form."},
]

_DMCA_BODY = """\
To the Designated Copyright Agent for {{platform}},

Date: {{date}}

I, {{agent_name}}, am the authorized agent of {{subject_legal_name}}, the owner of the
copyrighted work described below, and submit this notice under 17 U.S.C. §512(c)(3).

1. Copyrighted work: {{work_description}}
2. Infringing material and its location:
{{infringing_urls}}
3. Sealed evidence of the infringing page (SHA-256 manifest): {{evidence_sha256}}
   captured {{evidence_captured_at}}.
4. Contact: {{agent_name}}, {{agent_email}}.
5. {{good_faith_statement}}
6. {{perjury_statement}}

Signed (electronic signature of the authorized agent): /{{agent_name}}/
"""

_FORM_BODY = """\
Platform: {{platform}}
Claim type: {{claim_type_label}}
Rights holder: {{subject_legal_name}}
Authorized agent: {{agent_name}} ({{agent_email}})
Date: {{date}}

Infringing material:
{{infringing_urls}}

Description of the misuse: {{work_description}}
Sealed evidence (SHA-256 manifest): {{evidence_sha256}} captured {{evidence_captured_at}}.

{{good_faith_statement}}
{{perjury_statement}}
"""

_DMCA_ELEMENTS = [
    "agent_name", "work_description", "infringing_urls", "agent_email",
    "good_faith_statement", "perjury_statement",
]
_FORM_ELEMENTS = [
    "subject_legal_name", "agent_name", "infringing_urls", "good_faith_statement",
    "perjury_statement",
]

_TEMPLATES: list[dict] = [
    {"claim_type": "copyright", "method": "email", "name": "DMCA takedown (email)",
     "subject_template": "DMCA takedown notice — {{subject_legal_name}}",
     "body_template": _DMCA_BODY, "required_elements": _DMCA_ELEMENTS},
    {"claim_type": "copyright", "method": "web_form", "name": "Copyright form packet",
     "subject_template": "Copyright infringement — {{subject_legal_name}}",
     "body_template": _FORM_BODY, "required_elements": _FORM_ELEMENTS},
    {"claim_type": "ncii", "method": "web_form", "name": "NCII / Take It Down packet",
     "subject_template": "Non-consensual intimate imagery — {{subject_legal_name}}",
     "body_template": _FORM_BODY, "required_elements": _FORM_ELEMENTS},
    {"claim_type": "impersonation", "method": "web_form", "name": "Impersonation packet",
     "subject_template": "Impersonation of {{subject_legal_name}}",
     "body_template": _FORM_BODY, "required_elements": _FORM_ELEMENTS},
    {"claim_type": "likeness", "method": "web_form", "name": "Likeness/right-of-publicity packet",
     "subject_template": "Unauthorized use of likeness — {{subject_legal_name}}",
     "body_template": _FORM_BODY, "required_elements": _FORM_ELEMENTS},
    {"claim_type": "trademark", "method": "web_form", "name": "Trademark form packet",
     "subject_template": "Trademark infringement — {{subject_legal_name}}",
     "body_template": _FORM_BODY, "required_elements": _FORM_ELEMENTS},
]


def upgrade() -> None:
    if current_scope() != "public":
        return

    channels = op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("claim_type", sa.String(length=30), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("required_fields", JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("platform", "claim_type", name="uq_channel_platform_claim"),
    )
    templates = op.create_table(
        "notice_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_type", sa.String(length=30), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("required_elements", JSONB(), nullable=True),
        sa.Column(
            "approval_status", sa.String(length=20), nullable=False,
            server_default="unapproved",
        ),
        sa.Column("approved_by_staff_id", sa.Integer(), nullable=True),
        sa.Column("approver_name", sa.String(length=200), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("claim_type", "method", name="uq_template_claim_method"),
    )

    # Validated seed: refuse to persist a matrix-violating route (e.g. trademark/likeness over
    # email/DMCA). This is defense-in-depth alongside the runtime route_for guard.
    for row in _CHANNELS:
        if not method_allowed_for_claim(row["claim_type"], row["method"]):
            raise ValueError(
                f"seed channel violates the claims matrix: {row['platform']} "
                f"{row['claim_type']} via {row['method']}"
            )
    op.bulk_insert(channels, _CHANNELS)
    op.bulk_insert(templates, _TEMPLATES)


def downgrade() -> None:
    if current_scope() != "public":
        return
    op.drop_table("notice_templates")
    op.drop_table("channels")
