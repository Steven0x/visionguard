"""Biometric gating and the consent-revocation purge hook (CLAUDE.md #1)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.audit import AuditLog
from api.app.models.public import Workspace
from api.app.models.rights import ConsentRecord, ConsentType, RecordStatus
from api.app.models.subjects import Subject
from api.app.services import consent as consent_service
from api.app.services.claim_support import biometric_status

_TODAY = date(2026, 1, 1)


def _subject_with_biometric_consent(schema: str, *, biometrics_blocked: bool):
    with tenant_session(schema) as s:
        subject = Subject(legal_name="s", biometrics_blocked=biometrics_blocked)
        s.add(subject)
        s.flush()
        s.add(
            ConsentRecord(
                subject_id=subject.id,
                type=ConsentType.biometric,
                file_key="k",
                file_name="c.pdf",
                content_type="application/pdf",
                signer_name="x",
                signed_date=_TODAY,
                status=RecordStatus.active,
            )
        )
        s.flush()
        return biometric_status(s, subject)


def test_biometric_features_need_consent_and_unblocked(db, new_workspace: Workspace) -> None:
    enabled = _subject_with_biometric_consent(new_workspace.schema_name, biometrics_blocked=False)
    assert enabled["active_biometric_consent"] is True
    assert enabled["biometric_features_enabled"] is True

    blocked = _subject_with_biometric_consent(new_workspace.schema_name, biometrics_blocked=True)
    assert blocked["active_biometric_consent"] is True
    assert blocked["biometric_features_enabled"] is False  # geo block wins


def test_unblocked_alone_does_not_imply_consent(db, new_workspace: Workspace) -> None:
    with tenant_session(new_workspace.schema_name) as s:
        subject = Subject(legal_name="no-consent", biometrics_blocked=False)
        s.add(subject)
        s.flush()
        status = biometric_status(s, subject)
    assert status["biometrics_blocked"] is False
    assert status["active_biometric_consent"] is False
    assert status["biometric_features_enabled"] is False


def test_service_refuses_biometric_consent_for_blocked_subject(
    db, new_workspace: Workspace
) -> None:
    from sqlalchemy import func

    with tenant_session(new_workspace.schema_name) as s:
        subject = Subject(legal_name="blocked", biometrics_blocked=True)
        s.add(subject)
        s.flush()
        sid = subject.id
        with pytest.raises(consent_service.BiometricConsentBlocked):
            consent_service.create_consent_record(
                s,
                workspace_id=new_workspace.id,
                schema=new_workspace.schema_name,
                actor_staff_id=db.admin_staff_id,
                subject_id=sid,
                type=ConsentType.biometric,
                data=b"%PDF-1.4",
                content_type="application/pdf",
                file_name="c.pdf",
                signer_name="x",
                signed_date=_TODAY,
            )
        # Nothing was written.
        count = s.scalar(
            select(func.count()).select_from(ConsentRecord).where(
                ConsentRecord.subject_id == sid
            )
        )
    assert count == 0


def _make_consent(schema: str, consent_type: ConsentType) -> int:
    with tenant_session(schema) as s:
        subject = Subject(legal_name="s")
        s.add(subject)
        s.flush()
        record = ConsentRecord(
            subject_id=subject.id,
            type=consent_type,
            file_key="k",
            file_name="c.pdf",
            content_type="application/pdf",
            signer_name="x",
            signed_date=_TODAY,
            status=RecordStatus.active,
        )
        s.add(record)
        s.flush()
        return record.id


def test_revoking_biometric_consent_fires_purge_hook(
    db, new_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = MagicMock(return_value=0)
    monkeypatch.setattr(consent_service, "purge_biometric_data", spy)
    consent_id = _make_consent(new_workspace.schema_name, ConsentType.biometric)

    with tenant_session(new_workspace.schema_name) as s:
        record = consent_service.get_consent(s, consent_id)
        assert record is not None
        consent_service.revoke_consent(
            s, workspace_id=new_workspace.id, actor_staff_id=db.admin_staff_id,
            record=record, reason="subject request",
        )
    spy.assert_called_once()

    with tenant_session(new_workspace.schema_name) as s:
        actions = set(s.scalars(select(AuditLog.action)).all())
    assert "consent.revoked" in actions
    assert "biometrics.purged" in actions


def test_purge_waits_until_no_active_biometric_consent_remains(
    db, new_workspace: Workspace
) -> None:
    schema = new_workspace.schema_name
    with tenant_session(schema) as s:
        subject = Subject(legal_name="s")
        s.add(subject)
        s.flush()
        ids = []
        for _ in range(2):
            record = ConsentRecord(
                subject_id=subject.id,
                type=ConsentType.biometric,
                file_key="k",
                file_name="c.pdf",
                content_type="application/pdf",
                signer_name="x",
                signed_date=_TODAY,
                status=RecordStatus.active,
            )
            s.add(record)
            s.flush()
            ids.append(record.id)

    def _revoke(consent_id: int) -> None:
        with tenant_session(schema) as s:
            record = consent_service.get_consent(s, consent_id)
            assert record is not None
            consent_service.revoke_consent(
                s, workspace_id=new_workspace.id, actor_staff_id=db.admin_staff_id,
                record=record, reason=None,
            )

    _revoke(ids[0])  # one biometric consent still active → no purge yet
    with tenant_session(schema) as s:
        actions = list(s.scalars(select(AuditLog.action)).all())
    assert actions.count("biometrics.purged") == 0

    _revoke(ids[1])  # last one revoked → purge fires exactly once
    with tenant_session(schema) as s:
        actions = list(s.scalars(select(AuditLog.action)).all())
    assert actions.count("biometrics.purged") == 1


def test_revoking_enforcement_consent_does_not_purge(
    db, new_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = MagicMock(return_value=0)
    monkeypatch.setattr(consent_service, "purge_biometric_data", spy)
    consent_id = _make_consent(new_workspace.schema_name, ConsentType.enforcement)

    with tenant_session(new_workspace.schema_name) as s:
        record = consent_service.get_consent(s, consent_id)
        assert record is not None
        consent_service.revoke_consent(
            s, workspace_id=new_workspace.id, actor_staff_id=db.admin_staff_id,
            record=record, reason=None,
        )
    spy.assert_not_called()

    with tenant_session(new_workspace.schema_name) as s:
        actions = set(s.scalars(select(AuditLog.action)).all())
    assert "biometrics.purged" not in actions
