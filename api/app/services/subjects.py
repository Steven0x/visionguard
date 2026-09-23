"""Subject services: normalization, the fail-closed biometrics rule, CRUD, and CSV import.

All writes go through a tenant-bound session (the router opens it via get_tenant_session),
so everything is workspace-isolated by construction.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.audit.service import record_audit
from api.app.constants import (
    BIOMETRICS_ALLOWED_STATES,
    SUBJECT_IMPORT_MAX_BYTES,
    SUBJECT_IMPORT_MAX_ROWS,
    US_STATES,
)
from api.app.models.subjects import Subject, SubjectStatus

CSV_COLUMNS = ("legal_name", "stage_names", "handles", "residence_state", "notes")
_MAX_LEGAL_NAME = 200


# ── Normalization & rules ─────────────────────────────────────────────────────


def normalize_residence(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    return cleaned or None


def compute_biometrics_blocked(residence_state: str | None) -> bool:
    """Fail closed: blocked unless residence is a known US state outside IL/WA."""
    return residence_state not in BIOMETRICS_ALLOWED_STATES


def normalize_handles(values: Iterable[str]) -> list[str]:
    """Trim, strip a leading '@', lowercase, keep a platform: prefix, drop empties, dedupe."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None:
            continue
        s = raw.strip()
        if not s:
            continue
        platform: str | None = None
        if ":" in s:
            prefix, rest = s.split(":", 1)
            if prefix.isalnum() and len(prefix) <= 20 and rest and not rest.startswith("/"):
                platform = prefix.lower()
                s = rest
        s = s.strip().lstrip("@").strip().lower()
        if not s:
            continue
        norm = f"{platform}:{s}" if platform else s
        if norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def normalize_stage_names(values: Iterable[str]) -> list[str]:
    """Trim, drop empties, dedupe exact (case preserved)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if raw is None:
            continue
        s = raw.strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


# ── CRUD ──────────────────────────────────────────────────────────────────────


def list_subjects(session: Session, *, status_filter: str = "active") -> list[Subject]:
    stmt = select(Subject).order_by(Subject.legal_name, Subject.id)
    if status_filter in ("active", "archived"):
        stmt = stmt.where(Subject.status == SubjectStatus(status_filter))
    return list(session.scalars(stmt).all())


def get_subject(session: Session, subject_id: int) -> Subject | None:
    return session.get(Subject, subject_id)


def create_subject(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    legal_name: str,
    stage_names: Iterable[str] = (),
    handles: Iterable[str] = (),
    residence_state: str | None = None,
    notes: str | None = None,
) -> Subject:
    residence = normalize_residence(residence_state)
    subject = Subject(
        legal_name=legal_name.strip(),
        stage_names=normalize_stage_names(stage_names),
        handles=normalize_handles(handles),
        residence_state=residence,
        biometrics_blocked=compute_biometrics_blocked(residence),
        notes=notes,
        status=SubjectStatus.active,
    )
    session.add(subject)
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="subject.created",
        entity_type="subject",
        entity_id=str(subject.id),
    )
    return subject


def update_subject(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    subject: Subject,
    legal_name: str,
    stage_names: Iterable[str] = (),
    handles: Iterable[str] = (),
    residence_state: str | None = None,
    notes: str | None = None,
) -> Subject:
    residence = normalize_residence(residence_state)
    subject.legal_name = legal_name.strip()
    subject.stage_names = normalize_stage_names(stage_names)
    subject.handles = normalize_handles(handles)
    subject.residence_state = residence
    # Always recomputed server-side; a client-supplied value is never honoured.
    subject.biometrics_blocked = compute_biometrics_blocked(residence)
    subject.notes = notes
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="subject.updated",
        entity_type="subject",
        entity_id=str(subject.id),
    )
    return subject


def archive_subject(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    subject: Subject,
) -> Subject:
    subject.status = SubjectStatus.archived
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="subject.archived",
        entity_type="subject",
        entity_id=str(subject.id),
    )
    return subject


# ── CSV import ────────────────────────────────────────────────────────────────


class CsvFileError(Exception):
    """File-level problem (too big, wrong encoding, missing column, too many rows)."""


@dataclass
class ParsedRow:
    row_no: int
    values: dict[str, Any]
    errors: list[str] = field(default_factory=list)


def _decode_csv(raw: bytes) -> str:
    if len(raw) > SUBJECT_IMPORT_MAX_BYTES:
        raise CsvFileError(
            f"file too large ({len(raw)} bytes; limit {SUBJECT_IMPORT_MAX_BYTES})"
        )
    try:
        text = raw.decode("utf-8-sig")  # tolerates a UTF-8 BOM
    except UnicodeDecodeError as exc:
        raise CsvFileError("not a valid UTF-8 CSV file") from exc
    if "\x00" in text:  # NUL byte → binary, not a text/CSV file
        raise CsvFileError("not a valid UTF-8 CSV file")
    return text


def _dup_key(legal_name: object) -> str:
    return str(legal_name).strip().lower()


def parse_and_validate(raw: bytes, existing_active: list[Subject]) -> list[ParsedRow]:
    """Parse a CSV and return every row with normalized values + per-row errors.

    Duplicates (same case-insensitive legal_name AND an overlapping normalized handle,
    against other rows or an existing active subject) are recorded as errors.
    """
    text = _decode_csv(raw)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "legal_name" not in reader.fieldnames:
        raise CsvFileError("missing required column: legal_name")

    rows: list[ParsedRow] = []
    for i, record in enumerate(reader, start=1):
        if i > SUBJECT_IMPORT_MAX_ROWS:
            raise CsvFileError(f"too many rows (limit {SUBJECT_IMPORT_MAX_ROWS})")

        errors: list[str] = []
        legal_name = (record.get("legal_name") or "").strip()
        if not legal_name:
            errors.append("legal_name is required")
        elif len(legal_name) > _MAX_LEGAL_NAME:
            errors.append(f"legal_name exceeds {_MAX_LEGAL_NAME} characters")

        residence = normalize_residence(record.get("residence_state"))
        if residence is not None and residence not in US_STATES:
            errors.append(f"invalid residence_state: {residence}")

        stage_names = normalize_stage_names((record.get("stage_names") or "").split(";"))
        handles = normalize_handles((record.get("handles") or "").split(";"))

        rows.append(
            ParsedRow(
                row_no=i,
                values={
                    "legal_name": legal_name,
                    "stage_names": stage_names,
                    "handles": handles,
                    "residence_state": residence,
                    "notes": (record.get("notes") or "").strip() or None,
                    "biometrics_blocked": compute_biometrics_blocked(residence),
                },
                errors=errors,
            )
        )

    _flag_duplicates(rows, existing_active)
    return rows


def _flag_duplicates(rows: list[ParsedRow], existing_active: list[Subject]) -> None:
    existing = [(_dup_key(s.legal_name), set(s.handles)) for s in existing_active]
    for i, row in enumerate(rows):
        key = _dup_key(row.values["legal_name"])
        handles = set(row.values["handles"])
        if not handles:
            continue  # duplicate requires an overlapping handle
        for ekey, ehandles in existing:
            if key == ekey and handles & ehandles:
                row.errors.append("duplicate of an existing subject")
                break
        for j in range(i):
            other = rows[j]
            if key == _dup_key(other.values["legal_name"]) and handles & set(
                other.values["handles"]
            ):
                row.errors.append(f"duplicate of row {other.row_no}")
                other.errors.append(f"duplicate of row {row.row_no}")
    for row in rows:
        row.errors = list(dict.fromkeys(row.errors))  # de-dupe messages, keep order


def import_commit(
    session: Session,
    *,
    workspace_id: int,
    actor_staff_id: int | None,
    raw: bytes,
) -> int:
    """All-or-nothing import. Raises CsvFileError or returns the inserted count.

    If any row has errors, raises ValueError-like via the rows (caller maps to 422). Uses the
    active subjects already in this workspace for duplicate checks.
    """
    existing_active = list_subjects(session, status_filter="active")
    rows = parse_and_validate(raw, existing_active)
    if any(row.errors for row in rows):
        raise CsvRowErrors(rows)

    for row in rows:
        session.add(
            Subject(
                legal_name=str(row.values["legal_name"]),
                stage_names=list(row.values["stage_names"]),
                handles=list(row.values["handles"]),
                residence_state=row.values["residence_state"],
                biometrics_blocked=bool(row.values["biometrics_blocked"]),
                notes=row.values["notes"],
                status=SubjectStatus.active,
            )
        )
    session.flush()
    record_audit(
        session,
        workspace_id=workspace_id,
        actor_staff_id=actor_staff_id,
        action="subjects.imported",
        entity_type="subject",
        meta={"count": len(rows)},
    )
    return len(rows)


class CsvRowErrors(Exception):
    """Raised by import_commit when one or more rows are invalid (all-or-nothing)."""

    def __init__(self, rows: list[ParsedRow]) -> None:
        self.rows = rows
        super().__init__("csv has invalid rows")
