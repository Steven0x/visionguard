"""Derive which claim types a subject currently supports, from the (draft) claims matrix.

See docs/legal/claims-matrix.md (status: unapproved). Baseline for EVERY claim type is an
active agent authorization (the enforceability gate). Biometric features are handled
separately and are NOT a claim type.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models.rights import (
    ConsentRecord,
    ConsentType,
    RecordStatus,
    RightsRecord,
    RightsStatus,
    RightsType,
)
from api.app.models.subjects import Subject
from api.app.services.authorizations import active_authorization

CLAIM_TYPES = ("copyright", "trademark", "likeness", "ncii", "impersonation")

# Single source of truth for the matrix approval state surfaced to the API/UI. Update this
# (and the banner in docs/legal/claims-matrix.md) together when counsel signs off.
MATRIX_STATUS = "draft — pending counsel"

# Rights types that prove ownership for a copyright claim. A management_agreement grants
# representation, not ownership; a photographer_license only counts if it explicitly grants
# the enforcement right (checked separately).
_OWNERSHIP_TYPES = {RightsType.self_owned_declaration, RightsType.copyright_registration}


@dataclass
class ClaimSupport:
    claim_type: str
    supported: bool
    missing: list[str]


def _counting_rights(session: Session, subject_id: int) -> list[RightsRecord]:
    today = date.today()
    records = session.scalars(
        select(RightsRecord).where(
            RightsRecord.subject_id == subject_id,
            RightsRecord.status == RightsStatus.active,
        )
    ).all()
    # Expired records (past expires_on) confer no support, even if still marked active.
    return [r for r in records if r.expires_on is None or r.expires_on >= today]


def _supports_copyright(rights: list[RightsRecord]) -> bool:
    for r in rights:
        if r.type in _OWNERSHIP_TYPES:
            return True
        if r.type == RightsType.photographer_license and r.grants_enforcement_right:
            return True
    return False


def _has_active_enforcement_consent(session: Session, subject_id: int) -> bool:
    return (
        session.scalar(
            select(ConsentRecord.id)
            .where(
                ConsentRecord.subject_id == subject_id,
                ConsentRecord.type == ConsentType.enforcement,
                ConsentRecord.status == RecordStatus.active,
            )
            .limit(1)
        )
        is not None
    )


def _has_active_biometric_consent(session: Session, subject_id: int) -> bool:
    return (
        session.scalar(
            select(ConsentRecord.id)
            .where(
                ConsentRecord.subject_id == subject_id,
                ConsentRecord.type == ConsentType.biometric,
                ConsentRecord.status == RecordStatus.active,
            )
            .limit(1)
        )
        is not None
    )


def claim_support(session: Session, subject: Subject) -> list[ClaimSupport]:
    """Which claim types the subject has the LEGAL-BASIS RECORDS to support.

    IMPORTANT: ``supported`` means "the required records exist", NOT "safe to file". The
    claims matrix additionally requires identity verification for ``likeness`` / ``ncii`` /
    ``impersonation`` (Phase 2 liveness/ID — deferred here), and ``self_owned_declaration``
    is an unverified attestation. A later filing slice must still apply identity verification,
    fair-use, and allowlist checks; it must key off ``supported`` but never treat it as
    file-ready. See docs/legal/claims-matrix.md (status: unapproved).
    """
    has_auth = active_authorization(session, subject.id) is not None
    rights = _counting_rights(session, subject.id)
    copyright_ok = _supports_copyright(rights)
    enforcement_consent = _has_active_enforcement_consent(session, subject.id)

    results: list[ClaimSupport] = []
    for claim in CLAIM_TYPES:
        missing: list[str] = []
        if not has_auth:
            missing.append("active agent authorization")
        if claim == "copyright":
            if not copyright_ok:
                missing.append(
                    "ownership rights record (self-owned declaration, copyright "
                    "registration, or a photographer license granting the enforcement right)"
                )
        elif claim in ("likeness", "ncii", "impersonation"):
            if not enforcement_consent:
                missing.append("active enforcement consent")
        elif claim == "trademark":
            missing.append("trademark registration record (Brands mode, Phase 2)")
        results.append(
            ClaimSupport(claim_type=claim, supported=not missing, missing=missing)
        )
    return results


def subject_enforcement(session: Session, subject: Subject) -> dict:
    auth = active_authorization(session, subject.id)
    return {
        "enforceable": auth is not None,
        "active_authorization_id": auth.id if auth else None,
    }


def biometric_status(session: Session, subject: Subject) -> dict:
    has_consent = _has_active_biometric_consent(session, subject.id)
    return {
        "active_biometric_consent": has_consent,
        "biometrics_blocked": subject.biometrics_blocked,
        # Requires BOTH active biometric consent AND biometrics_blocked == false.
        # biometrics_blocked == false alone never implies consent.
        "biometric_features_enabled": has_consent and not subject.biometrics_blocked,
    }
