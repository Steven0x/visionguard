"""Safe notice rendering + injection guards (Slice 8).

Templates render via a whitelisted ``{{key}}`` substitution over a fixed context dict — no
expression evaluation, no attribute access, no template engine (see ADR 0011). Notices are
plain text (email plain-text body / copy-ready packet), so there is no markup sink and values
are substituted verbatim; the injection surface is the email *headers*, so every recipient,
subject, and header value is CR/LF-sanitized (``sanitize_header_value``), for both rendered
output and user-edited drafts.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from api.app.config import get_settings
from api.app.models.cases import Case
from api.app.models.subjects import Subject

# The ONLY placeholders a template may reference. A token outside this set is a template bug and
# render() raises rather than silently leaving it or evaluating anything.
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "subject_legal_name",
        "agent_name",
        "agent_email",
        "infringing_urls",
        "work_description",
        "evidence_sha256",
        "evidence_captured_at",
        "platform",
        "claim_type_label",
        "good_faith_statement",
        "perjury_statement",
        "date",
    }
)

CLAIM_TYPE_LABELS: dict[str, str] = {
    "copyright": "copyright infringement",
    "trademark": "trademark infringement",
    "likeness": "unauthorized use of likeness",
    "ncii": "non-consensual intimate imagery",
    "impersonation": "impersonation",
}

_GOOD_FAITH = (
    "I have a good-faith belief that the use of the material described above is not authorized "
    "by the rights owner, its agent, or the law."
)
_PERJURY = (
    "I declare, under penalty of perjury, that the information in this notice is accurate and "
    "that I am authorized to act on behalf of the owner of the rights described above."
)

_TOKEN_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_INJECTION_RE = re.compile(r"[\r\n\x00]")


class NoticeRenderError(Exception):
    """A template referenced an unknown field, or a header value was malformed."""


def sanitize_header_value(value: str) -> str:
    """Strip CR/LF/NUL so a subject/recipient can't smuggle extra headers."""
    return _INJECTION_RE.sub("", value).strip()


def render(template: str, context: dict[str, str]) -> str:
    """Replace only known ``{{key}}`` tokens from ``context``; unknown tokens raise."""

    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in ALLOWED_FIELDS:
            raise NoticeRenderError(f"template references unknown field {key!r}")
        if key not in context:
            raise NoticeRenderError(f"missing context value for field {key!r}")
        return context[key]

    return _TOKEN_RE.sub(_sub, template)


def build_context(
    session: Session, *, case: Case, subject: Subject, platform: str
) -> dict[str, str]:
    """Assemble the whitelisted field dict from case data. Missing legal basis (no active
    authorization / no sealed evidence) leaves those fields empty so completeness checks fail."""
    from api.app.services.authorizations import active_authorization
    from api.app.services.evidence import latest_sealed_page_capture

    auth = active_authorization(session, subject.id)
    capture = latest_sealed_page_capture(session, case.id)
    settings = get_settings()

    infringing_urls = case.source_url or ""
    work_description = (
        f"Content depicting {subject.legal_name}, enforced under a {case.claim_type} claim."
    )
    return {
        "subject_legal_name": subject.legal_name,
        "agent_name": auth.signer_name if auth else "",
        "agent_email": settings.email_from,
        "infringing_urls": infringing_urls,
        "work_description": work_description,
        "evidence_sha256": (capture.manifest_sha256 or "") if capture else "",
        "evidence_captured_at": (
            capture.capture_finished_at.isoformat()
            if capture and capture.capture_finished_at
            else ""
        ),
        "platform": platform,
        "claim_type_label": CLAIM_TYPE_LABELS.get(case.claim_type, case.claim_type),
        "good_faith_statement": _GOOD_FAITH,
        "perjury_statement": _PERJURY,
        "date": datetime.now(UTC).date().isoformat(),
    }


def missing_elements(required: list[str] | None, context: dict[str, str]) -> list[str]:
    """Required context keys whose value is empty/blank — the draft is incomplete (un-sendable)."""
    if not required:
        return []
    return [key for key in required if not (context.get(key) or "").strip()]


def now_utc() -> datetime:
    return datetime.now(UTC)
