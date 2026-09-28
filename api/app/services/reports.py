"""Reports service (Slice 10): generate the agency PDF report + a JSON input-snapshot, seal both
write-once, and verify them later. The ONLY writer of ``reports``.

Every number comes from ``services/metrics.py`` (``report_metrics``) — this module formats and
renders, it does not count. Data minimization (CLAUDE.md #7) is applied at render time: ncii cases
never show an image and their URLs are domain-only; other-claim thumbnails are off unless the
report opts in; a per-subject report only ever touches that subject's rows. See
docs/specs/reports.md, ADR 0013."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.db.base import validate_schema_name
from api.app.models.cases import TERMINAL_STATES, Case
from api.app.models.discovery import DiscoveryCandidate
from api.app.models.reports import Report
from api.app.models.subjects import Subject
from api.app.services import metrics as metrics_svc
from api.app.storage import get_storage
from api.app.storage.evidence import get_evidence_storage

_NCII = "ncii"


class ReportError(Exception):
    """A report request that can't proceed (e.g. an invalid date range) → 422."""


class ReportSubjectNotFound(ReportError):
    """A per-subject report named a subject that isn't in this workspace → 404."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _report_key(schema: str, token: str, name: str) -> str:
    return f"{validate_schema_name(schema)}/reports/{token}/{name}"


# ── The redacted per-case view rendered in the PDF (never in the JSON snapshot) ──


@dataclass
class CaseRow:
    case_id: int
    claim_type: str
    status: str
    url: str  # domain-only for ncii, full otherwise
    thumbnail: bytes | None  # never for ncii; only when include_thumbnails otherwise


def _redact_url(url: str | None, claim_type: str) -> str:
    if not url:
        return "—"
    if claim_type == _NCII:
        host = urlsplit(url).hostname or ""
        return host or "—"
    return url


def gather_case_rows(
    session: Session, *, subject_id: int | None, include_thumbnails: bool
) -> list[CaseRow]:
    """Open (non-terminal) cases in scope, with URLs/thumbnails redacted per the minimization
    rules. This is the exact set of per-case data that reaches the PDF — tested directly."""
    stmt = (
        select(Case)
        .where(Case.status.notin_([s.value for s in TERMINAL_STATES]))
        .order_by(Case.id)
    )
    if subject_id is not None:
        stmt = stmt.where(Case.subject_id == subject_id)
    storage = get_storage()
    rows: list[CaseRow] = []
    for case in session.scalars(stmt).all():
        thumb: bytes | None = None
        # Default-deny: an image renders ONLY for a NOT-sensitive, non-ncii case with the report
        # toggle on. The `sensitive` flag is the primary gate (leaked paid content is often filed as
        # copyright, so claim type alone can't gate imagery); the explicit `!= ncii` check is
        # belt-and-suspenders so ncii can never emit an image even if the flag ever drifted
        # (CLAUDE.md #7).
        if (
            not case.sensitive
            and case.claim_type != _NCII
            and include_thumbnails
            and case.candidate_id is not None
        ):
            candidate = session.get(DiscoveryCandidate, case.candidate_id)
            if candidate is not None and candidate.thumbnail_key:
                try:
                    thumb = storage.get_object(candidate.thumbnail_key)
                except Exception:  # noqa: BLE001, S110 - a missing thumbnail never breaks a report
                    thumb = None
        rows.append(
            CaseRow(
                case_id=case.id,
                claim_type=case.claim_type,
                status=str(case.status),
                url=_redact_url(case.page_url or case.source_url, case.claim_type),
                thumbnail=thumb,
            )
        )
    return rows


# ── JSON input-snapshot (the numbers only — no per-case URLs/images) ──────────


def _snapshot(m: metrics_svc.ReportMetrics, *, as_of: datetime, include_thumbnails: bool) -> dict:
    """A deterministic dict of the report's numbers + parameters. Contains no per-case URLs or
    images, so the sealed JSON is safe to hand back even for ncii-heavy workspaces."""
    return {
        "as_of": as_of.isoformat(),
        "period_start": m.period_start.isoformat(),
        "period_end": m.period_end.isoformat(),
        "subject_id": m.subject_id,
        "include_thumbnails": include_thumbnails,
        "found": m.found,
        "filed": m.filed,
        "withdrawn": m.withdrawn,
        "removed": m.removed,
        "removed_verified": m.removed_verified,
        "removed_staff_only": m.removed_staff_only,
        "countered": m.countered,
        "still_pending": m.still_pending,
        "median_days_to_removal": m.median_days_to_removal,
        "open_cases_by_status": m.open_cases_by_status,
        "needs_from_you": {
            "missing_authorization": sorted(m.needs_from_you.missing_authorization),
            "ownership_rights": sorted(m.needs_from_you.ownership_rights),
            "enforcement_consent": sorted(m.needs_from_you.enforcement_consent),
            "licensed_use_confirmations": m.needs_from_you.licensed_use_confirmations,
        },
        "highlights": m.highlights,
    }


def _snapshot_bytes(snapshot: dict) -> bytes:
    return json.dumps(snapshot, sort_keys=True, indent=2).encode("utf-8")


# ── PDF rendering ─────────────────────────────────────────────────────────────


def _render_pdf(
    *, snapshot: dict, subject_name: str | None, case_rows: list[CaseRow]
) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    def line(y: float, text: str, size: int = 10) -> float:
        pdf.setFont("Helvetica", size)
        pdf.drawString(0.75 * inch, y, text[:110])
        return y - (size + 4)

    def page_break(y: float, floor: float = 1.0) -> float:
        if y < floor * inch:
            pdf.showPage()
            return height - 0.75 * inch
        return y

    y = height - 0.75 * inch
    scope = f"subject {subject_name}" if subject_name else "whole workspace"
    y = line(y, "VisionGuard agency report", 16)
    y = line(y, f"scope: {scope}    period: {snapshot['period_start']} → {snapshot['period_end']}")
    y = line(y, f"generated as of: {snapshot['as_of']}", 8)
    y -= 6

    y = line(y, "Summary", 13)
    y = line(y, f"Found (confirmed): {snapshot['found']}")
    y = line(y, f"Filed: {snapshot['filed']}   (withdrawn: {snapshot['withdrawn']})")
    y = line(
        y,
        f"Removed: {snapshot['removed']}  "
        f"(verified {snapshot['removed_verified']} / staff-only {snapshot['removed_staff_only']})",
    )
    mttr = snapshot["median_days_to_removal"]
    y = line(y, f"Median time to removal: {mttr if mttr is not None else '—'} days")
    y = line(y, f"Still pending: {snapshot['still_pending']}")
    y -= 6

    y = page_break(y, 3.0)
    y = line(y, "Open cases by status", 13)
    if snapshot["open_cases_by_status"]:
        for status, count in sorted(snapshot["open_cases_by_status"].items()):
            y = line(y, f"  {status}: {count}")
    else:
        y = line(y, "  none")
    y -= 6

    if snapshot["highlights"]:
        y = page_break(y, 2.5)
        y = line(y, "Highlights", 13)
        for h in snapshot["highlights"]:
            y = line(y, f"  • {h}")
        y -= 6

    needs = snapshot["needs_from_you"]
    y = page_break(y, 2.5)
    y = line(y, "Needs from you", 13)
    y = line(y, f"  Missing authorizations: {len(needs['missing_authorization'])} subject(s)")
    y = line(y, f"  Ownership / photographer proof: {len(needs['ownership_rights'])} subject(s)")
    y = line(y, f"  Enforcement consent: {len(needs['enforcement_consent'])} subject(s)")
    y = line(y, f"  Licensed-use confirmations: {needs['licensed_use_confirmations']}")
    y -= 6

    y = page_break(y, 2.5)
    y = line(y, "Open cases", 13)
    for row in case_rows:
        y = page_break(y, 1.5)
        y = line(y, f"  #{row.case_id}  {row.claim_type}  {row.status}  {row.url}")
        if row.thumbnail is not None:
            try:
                reader = ImageReader(io.BytesIO(row.thumbnail))
                pdf.drawImage(
                    reader, 0.9 * inch, y - 1.6 * inch, width=1.6 * inch, height=1.4 * inch,
                    preserveAspectRatio=True, anchor="nw",
                )
                y -= 1.7 * inch
            except Exception:  # noqa: BLE001, S110 - a bad image never breaks a report
                y = line(y, "    [thumbnail could not be rendered]", 8)

    pdf.showPage()
    pdf.save()
    return buf.getvalue()


# ── Generate / list / get / verify ────────────────────────────────────────────


def generate_report(
    session: Session,
    *,
    schema: str,
    workspace_id: int,
    subject_id: int | None,
    start: date,
    end: date,
    actor_staff_id: int | None,
    include_thumbnails: bool = False,
) -> Report:
    if start > end:
        raise ReportError("start date must not be after end date")
    subject_name: str | None = None
    if subject_id is not None:
        subject = session.get(Subject, subject_id)
        if subject is None:
            raise ReportSubjectNotFound(f"subject {subject_id} not found in this workspace")
        subject_name = subject.legal_name

    as_of = datetime.now(UTC)
    m = metrics_svc.report_metrics(
        session, subject_id=subject_id, start=start, end=end, as_of=as_of
    )
    snapshot = _snapshot(m, as_of=as_of, include_thumbnails=include_thumbnails)
    json_bytes = _snapshot_bytes(snapshot)
    case_rows = gather_case_rows(
        session, subject_id=subject_id, include_thumbnails=include_thumbnails
    )
    pdf_bytes = _render_pdf(snapshot=snapshot, subject_name=subject_name, case_rows=case_rows)

    # Seal both write-once under an unguessable per-report path (no UPDATE — the row is written
    # once with the keys/hashes already known, since `reports` is append-only).
    token = uuid.uuid4().hex
    storage = get_evidence_storage()
    pdf_key = _report_key(schema, token, "report.pdf")
    json_key = _report_key(schema, token, "inputs.json")
    storage.seal_object(pdf_key, pdf_bytes, "application/pdf")
    storage.seal_object(json_key, json_bytes, "application/json")

    report = Report(
        subject_id=subject_id,
        period_start=start,
        period_end=end,
        as_of=as_of,
        include_thumbnails=include_thumbnails,
        pdf_key=pdf_key,
        pdf_sha256=_sha256(pdf_bytes),
        json_key=json_key,
        json_sha256=_sha256(json_bytes),
        generated_by_staff_id=actor_staff_id,
    )
    session.add(report)
    session.flush()
    record_audit(
        session, workspace_id=workspace_id, actor_staff_id=actor_staff_id,
        action="report.generated", entity_type="report", entity_id=str(report.id),
        meta={
            "subject_id": subject_id, "period_start": start.isoformat(),
            "period_end": end.isoformat(), "as_of": as_of.isoformat(),
            "include_thumbnails": include_thumbnails,
        },
    )
    return report


def list_reports(session: Session, *, subject_id: int | None = None) -> list[Report]:
    stmt = select(Report).order_by(Report.id.desc())
    if subject_id is not None:
        stmt = stmt.where(Report.subject_id == subject_id)
    return list(session.scalars(stmt).all())


def get_report(session: Session, report_id: int) -> Report | None:
    return session.get(Report, report_id)


def read_artifact(report: Report, *, which: str) -> tuple[bytes, str]:
    """Return the sealed (bytes, content_type) for ``pdf`` or ``json``."""
    storage = get_evidence_storage()
    if which == "pdf":
        return storage.get_object(report.pdf_key), "application/pdf"
    if which == "json":
        return storage.get_object(report.json_key), "application/json"
    raise ValueError(f"unknown artifact {which!r}")


def verify_report(report: Report) -> bool:
    """Re-fetch the sealed bytes and confirm they still hash to the recorded SHA-256s — the
    'regenerate and check later' guarantee."""
    storage = get_evidence_storage()
    try:
        pdf_ok = _sha256(storage.get_object(report.pdf_key)) == report.pdf_sha256
        json_ok = _sha256(storage.get_object(report.json_key)) == report.json_sha256
    except Exception:  # noqa: BLE001 - a missing/unreadable artifact fails verification
        return False
    return pdf_ok and json_ok


def snapshot_dict(report: Report) -> dict:
    """The stored JSON snapshot as a dict (for the API/tests: report totals == metrics totals)."""
    data, _ = read_artifact(report, which="json")
    result: dict = json.loads(data)
    return result


__all__ = [
    "CaseRow",
    "ReportError",
    "ReportSubjectNotFound",
    "gather_case_rows",
    "generate_report",
    "get_report",
    "list_reports",
    "read_artifact",
    "snapshot_dict",
    "verify_report",
]
