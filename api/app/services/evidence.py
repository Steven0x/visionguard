"""Evidence service: sealing (hash + manifest + RFC 3161 timestamp, write-once), custody log,
verification, freshness gate, and the PDF pack. See docs/specs/evidence.md."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.capture.base import CaptureResult
from api.app.config import get_settings
from api.app.db.base import validate_schema_name
from api.app.evidence_ts import get_timestamp, verify_timestamp
from api.app.models.cases import Case
from api.app.models.evidence import (
    CaptureKind,
    CaptureStatus,
    CustodyAction,
    CustodyEvent,
    EvidenceArtifact,
    EvidenceCapture,
    TimestampStatus,
)
from api.app.storage.evidence import get_evidence_storage

# Artifacts hashed into the manifest (manifest.json/manifest.tsr are meta, not self-referential).
_MANIFEST = "manifest.json"
_TSR = "manifest.tsr"


class EvidenceError(Exception):
    """Raised for evidence operations that cannot proceed (e.g. CSAM gate closed)."""


def _evidence_key(schema: str, capture_id: int, name: str) -> str:
    return f"{validate_schema_name(schema)}/evidence/{capture_id}/{name}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Custody ─────────────────────────────────────────────────────────────────


def record_custody(
    session: Session,
    *,
    case_id: int,
    capture_id: int | None,
    action: CustodyAction,
    actor_staff_id: int | None,
    reason: str | None = None,
    detail: str | None = None,
) -> None:
    session.add(
        CustodyEvent(
            case_id=case_id,
            capture_id=capture_id,
            action=action,
            actor_staff_id=actor_staff_id,
            reason=reason,
            detail=detail,
        )
    )
    session.flush()


# ── Creating + triggering captures ────────────────────────────────────────────


def create_pending_capture(
    session: Session,
    *,
    case: Case,
    kind: CaptureKind,
    requested_url: str | None,
    captured_by_staff_id: int | None,
) -> EvidenceCapture:
    capture = EvidenceCapture(
        case_id=case.id,
        kind=kind,
        status=CaptureStatus.pending,
        requested_url=requested_url,
        captured_by_staff_id=captured_by_staff_id,
        tool_version=get_settings().capture_tool_version,
    )
    session.add(capture)
    session.flush()
    return capture


def trigger_capture(
    session: Session,
    *,
    workspace_id: int,
    case: Case,
    kind: CaptureKind,
    actor_staff_id: int | None,
) -> EvidenceCapture:
    """Create a pending capture, COMMIT, then enqueue the worker. Like _enqueue_fingerprint,
    this finalizes the transaction — callers must not mutate further afterwards."""
    capture = create_pending_capture(
        session,
        case=case,
        kind=kind,
        requested_url=case.source_url,
        captured_by_staff_id=actor_staff_id,
    )
    capture_id = capture.id
    session.commit()
    from worker.evidence import capture_evidence

    capture_evidence.delay(workspace_id, capture_id)
    session.refresh(capture)
    return capture


# ── Sealing ────────────────────────────────────────────────────────────────


def _seal(
    session: Session,
    *,
    schema: str,
    capture: EvidenceCapture,
    artifacts: dict[str, tuple[bytes, str]],
    manifest_meta: dict,
) -> None:
    """Write each artifact once, build + hash the manifest, timestamp it, and mark sealed."""
    storage = get_evidence_storage()
    file_hashes: dict[str, str] = {}
    for name, (data, content_type) in artifacts.items():
        key = _evidence_key(schema, capture.id, name)
        storage.seal_object(key, data, content_type)
        digest = _sha256(data)
        file_hashes[name] = digest
        session.add(
            EvidenceArtifact(
                capture_id=capture.id,
                name=name,
                object_key=key,
                sha256=digest,
                content_type=content_type,
                size_bytes=len(data),
            )
        )

    manifest = {
        **manifest_meta,
        "hash_algorithm": "sha256",
        "tool": capture.tool_version,
        "files": file_hashes,
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    manifest_key = _evidence_key(schema, capture.id, _MANIFEST)
    storage.seal_object(manifest_key, manifest_bytes, "application/json")
    manifest_sha = _sha256(manifest_bytes)
    session.add(
        EvidenceArtifact(
            capture_id=capture.id, name=_MANIFEST, object_key=manifest_key,
            sha256=manifest_sha, content_type="application/json",
            size_bytes=len(manifest_bytes),
        )
    )

    ts = get_timestamp(manifest_bytes)
    if ts.ok and ts.token is not None:
        tsr_key = _evidence_key(schema, capture.id, _TSR)
        storage.seal_object(tsr_key, ts.token, "application/timestamp-reply")
        session.add(
            EvidenceArtifact(
                capture_id=capture.id, name=_TSR, object_key=tsr_key,
                sha256=_sha256(ts.token), content_type="application/timestamp-reply",
                size_bytes=len(ts.token),
            )
        )

    capture.manifest_sha256 = manifest_sha
    capture.timestamp_status = TimestampStatus.ok if ts.ok else TimestampStatus.untimestamped
    capture.tsa_url = ts.tsa_url
    capture.tsa_time = ts.tsa_time
    capture.status = CaptureStatus.sealed
    capture.capture_finished_at = datetime.now(UTC)
    session.flush()
    record_custody(
        session, case_id=capture.case_id, capture_id=capture.id,
        action=CustodyAction.captured, actor_staff_id=capture.captured_by_staff_id,
        detail=f"kind={capture.kind} timestamp={capture.timestamp_status}",
    )


def seal_browser_capture(
    session: Session, *, schema: str, capture: EvidenceCapture, result: CaptureResult
) -> None:
    """Seal artifacts produced by the capture backend (screenshot/html/mhtml/meta)."""
    capture.final_url = result.final_url
    capture.http_status = result.http_status
    capture.page_title = result.page_title
    capture.visible_counts = result.visible_counts
    capture.error = result.load_error
    meta = _build_meta(capture, extra={"load_error": result.load_error})
    artifacts = {
        "screenshot.png": (result.screenshot, "image/png"),
        "page.html": (result.html, "text/html"),
        "page.mhtml": (result.mhtml, "multipart/related"),
        "meta.json": (json.dumps(meta, indent=2, sort_keys=True).encode(), "application/json"),
    }
    _seal(session, schema=schema, capture=capture, artifacts=artifacts,
          manifest_meta=_manifest_meta(capture))


def seal_manual_upload(
    session: Session,
    *,
    schema: str,
    capture: EvidenceCapture,
    screenshot_png: bytes,
    attestation: str,
) -> None:
    """Seal a staff-uploaded screenshot (already image-validated) + an attestation."""
    meta = _build_meta(capture, extra={"attestation": attestation, "manual": True})
    artifacts = {
        "screenshot.png": (screenshot_png, "image/png"),
        "meta.json": (json.dumps(meta, indent=2, sort_keys=True).encode(), "application/json"),
    }
    _seal(session, schema=schema, capture=capture, artifacts=artifacts,
          manifest_meta=_manifest_meta(capture))


def seal_notice_capture(
    session: Session,
    *,
    schema: str,
    capture: EvidenceCapture,
    notice_text: str,
    recipients: list[str],
    headers: dict[str, str],
    claim_type: str,
    template_id: int,
    template_version: int,
) -> None:
    """Seal the exact sent notice (rendered text + recipients + headers), write-once, so the
    filing record is immutable (CLAUDE.md #6). Mirrors seal_manual_upload."""
    meta = _build_meta(
        capture,
        extra={
            "notice": True,
            "claim_type": claim_type,
            "template_id": template_id,
            "template_version": template_version,
            "recipients": recipients,
            "headers": headers,
        },
    )
    artifacts = {
        "notice.txt": (notice_text.encode("utf-8"), "text/plain"),
        "meta.json": (json.dumps(meta, indent=2, sort_keys=True).encode(), "application/json"),
    }
    _seal(session, schema=schema, capture=capture, artifacts=artifacts,
          manifest_meta=_manifest_meta(capture))


def _manifest_meta(capture: EvidenceCapture) -> dict:
    return {
        "case_id": capture.case_id,
        "capture_id": capture.id,
        "kind": str(capture.kind),
        "requested_url": capture.requested_url,
        "final_url": capture.final_url,
    }


def _build_meta(capture: EvidenceCapture, *, extra: dict) -> dict:
    return {
        "case_id": capture.case_id,
        "capture_id": capture.id,
        "kind": str(capture.kind),
        "requested_url": capture.requested_url,
        "final_url": capture.final_url,
        "http_status": capture.http_status,
        "page_title": capture.page_title,
        "visible_counts": capture.visible_counts,
        "tool": capture.tool_version,
        "captured_by_staff_id": capture.captured_by_staff_id,
        "capture_finished_utc": datetime.now(UTC).isoformat(),
        **extra,
    }


# ── Verification ──────────────────────────────────────────────────────────────


@dataclass
class VerifyResult:
    ok: bool
    files: dict[str, bool] = field(default_factory=dict)
    manifest_ok: bool = False
    timestamp_ok: bool | None = None


def verify_capture(
    session: Session,
    *,
    schema: str,
    capture: EvidenceCapture,
    actor_staff_id: int | None,
    reason: str | None,
) -> VerifyResult:
    storage = get_evidence_storage()
    artifacts = list_artifacts(session, capture.id)
    by_name = {a.name: a for a in artifacts}
    files: dict[str, bool] = {}
    for a in artifacts:
        if a.name == _TSR:
            continue
        actual = _sha256(storage.get_object(a.object_key))
        files[a.name] = actual == a.sha256

    manifest_ok = False
    timestamp_ok: bool | None = None
    if _MANIFEST in by_name:
        manifest_bytes = storage.get_object(by_name[_MANIFEST].object_key)
        manifest_ok = _sha256(manifest_bytes) == capture.manifest_sha256
        if _TSR in by_name:
            token = storage.get_object(by_name[_TSR].object_key)
            timestamp_ok = verify_timestamp(token, manifest_bytes)

    ok = all(files.values()) and manifest_ok and (timestamp_ok is not False)
    record_custody(
        session, case_id=capture.case_id, capture_id=capture.id,
        action=CustodyAction.verified, actor_staff_id=actor_staff_id, reason=reason,
        detail=f"ok={ok}",
    )
    return VerifyResult(ok=ok, files=files, manifest_ok=manifest_ok, timestamp_ok=timestamp_ok)


# ── Reads + freshness gate ─────────────────────────────────────────────────────


def list_captures(session: Session, case_id: int) -> list[EvidenceCapture]:
    return list(
        session.scalars(
            select(EvidenceCapture)
            .where(EvidenceCapture.case_id == case_id)
            .order_by(EvidenceCapture.id.desc())
        ).all()
    )


def get_capture(session: Session, capture_id: int) -> EvidenceCapture | None:
    return session.get(EvidenceCapture, capture_id)


def list_artifacts(session: Session, capture_id: int) -> list[EvidenceArtifact]:
    return list(
        session.scalars(
            select(EvidenceArtifact)
            .where(EvidenceArtifact.capture_id == capture_id)
            .order_by(EvidenceArtifact.name)
        ).all()
    )


def list_custody(session: Session, case_id: int) -> list[CustodyEvent]:
    return list(
        session.scalars(
            select(CustodyEvent)
            .where(CustodyEvent.case_id == case_id)
            .order_by(CustodyEvent.id)
        ).all()
    )


def has_fresh_sealed_capture(session: Session, case_id: int) -> bool:
    cutoff = datetime.now(UTC) - timedelta(days=get_settings().evidence_freshness_days)
    return (
        session.scalar(
            select(EvidenceCapture.id)
            .where(
                EvidenceCapture.case_id == case_id,
                EvidenceCapture.status == CaptureStatus.sealed,
                # A sealed NOTICE is not page evidence — it must never satisfy the evidence gate.
                EvidenceCapture.kind != CaptureKind.notice,
                EvidenceCapture.capture_finished_at >= cutoff,
            )
            .limit(1)
        )
        is not None
    )


def latest_sealed_page_capture(session: Session, case_id: int) -> EvidenceCapture | None:
    """The newest sealed page-evidence capture (excludes sealed notices), for referencing its
    manifest hash + capture time in a notice."""
    return session.scalar(
        select(EvidenceCapture)
        .where(
            EvidenceCapture.case_id == case_id,
            EvidenceCapture.status == CaptureStatus.sealed,
            EvidenceCapture.kind != CaptureKind.notice,
        )
        .order_by(EvidenceCapture.capture_finished_at.desc(), EvidenceCapture.id.desc())
        .limit(1)
    )


# ── PDF pack ───────────────────────────────────────────────────────────────


def build_pack_pdf(
    session: Session,
    *,
    schema: str,
    case: Case,
    actor_staff_id: int | None,
    reason: str,
    include_sensitive: bool,
) -> bytes:
    """Admin-only per-case pack (custody-logged). Sensitive screenshots are blurred unless the
    admin explicitly opts in (that choice is logged too)."""
    buf = _render_pack(session, schema=schema, case=case, include_sensitive=include_sensitive)
    record_custody(
        session, case_id=case.id, capture_id=None, action=CustodyAction.exported,
        actor_staff_id=actor_staff_id, reason=reason,
        detail=f"include_sensitive={include_sensitive}",
    )
    return buf


def _render_pack(
    session: Session, *, schema: str, case: Case, include_sensitive: bool
) -> bytes:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    storage = get_evidence_storage()
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    def line(y: float, text: str, size: int = 10) -> float:
        pdf.setFont("Helvetica", size)
        pdf.drawString(0.75 * inch, y, text[:110])
        return y - (size + 4)

    y = height - 0.75 * inch
    y = line(y, f"VisionGuard evidence pack — case #{case.id}", 16)
    y = line(y, f"claim: {case.claim_type}   status: {case.status}   subject: {case.subject_id}")
    y -= 6

    for capture in list_captures(session, case.id):
        if capture.status != CaptureStatus.sealed:
            continue
        if y < 3 * inch:
            pdf.showPage()
            y = height - 0.75 * inch
        y = line(y, f"Capture #{capture.id} · {capture.kind} · {capture.timestamp_status}", 12)
        y = line(y, f"url: {capture.final_url or capture.requested_url or '—'}")
        y = line(y, f"captured: {capture.capture_finished_at}  manifest: {capture.manifest_sha256}")
        for a in list_artifacts(session, capture.id):
            y = line(y, f"  {a.name}  {a.sha256}", 8)

        shot = next(
            (a for a in list_artifacts(session, capture.id) if a.name == "screenshot.png"), None
        )
        if shot is not None:
            img_bytes = storage.get_object(shot.object_key)
            if capture.sensitive and not include_sensitive:
                img_bytes = _blur(img_bytes)
            try:
                reader = ImageReader(io.BytesIO(img_bytes))
                pdf.drawImage(reader, 0.75 * inch, y - 2.6 * inch, width=3.2 * inch,
                              height=2.4 * inch, preserveAspectRatio=True, anchor="nw")
            except Exception:  # noqa: BLE001, S110 - never let a bad image break the pack
                y = line(y, "  [screenshot could not be rendered]", 8)
            y -= 2.7 * inch

    if y < 2 * inch:
        pdf.showPage()
        y = height - 0.75 * inch
    y = line(y, "Chain of custody", 12)
    for ev in list_custody(session, case.id):
        y = line(
            y,
            f"  {ev.created_at}  {ev.action}  staff={ev.actor_staff_id}  {ev.reason or ''}",
            8,
        )
        if y < 0.75 * inch:
            pdf.showPage()
            y = height - 0.75 * inch

    pdf.showPage()
    pdf.save()
    return buf.getvalue()


def _blur(png_bytes: bytes) -> bytes:
    from PIL import Image, ImageFilter

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    img = img.filter(ImageFilter.GaussianBlur(radius=18))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
