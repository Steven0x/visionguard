"""Slice 6: no two OPEN cases for the same subject + URL; terminal cases don't block re-file."""

from __future__ import annotations

import pytest

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseStatus
from api.app.models.discovery import DiscoveryCandidate
from api.app.models.public import Workspace
from api.app.models.subjects import Subject
from api.app.services import cases as svc
from api.app.services.cases import DuplicateOpenCase

from .reviewhelpers import add_candidate, make_subject


def _open(schema: str, ws_id: int, candidate_id: int, subject_id: int, claim: str = "likeness"):
    with tenant_session(schema) as session:
        subject = session.get(Subject, subject_id)
        candidate = session.get(DiscoveryCandidate, candidate_id)
        assert subject is not None and candidate is not None
        return svc.open_case_from_candidate(
            session,
            workspace_id=ws_id,
            actor_staff_id=None,
            subject=subject,
            candidate=candidate,
            claim_type=claim,
        ).id


def test_duplicate_open_case_blocked(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    cid = add_candidate(schema, subject_id, source_url="https://dup.example/x")
    _open(schema, new_workspace.id, cid, subject_id)
    with pytest.raises(DuplicateOpenCase):
        _open(schema, new_workspace.id, cid, subject_id)


def test_duplicate_race_hits_index_and_raises_duplicate_not_integrityerror(
    new_workspace: Workspace, monkeypatch
) -> None:
    """When the pre-check misses a concurrent open (simulated by forcing it False), the partial
    unique index must still stop the insert and surface as DuplicateOpenCase, not a raw 500."""
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    cid = add_candidate(schema, subject_id, source_url="https://race.example/x")
    _open(schema, new_workspace.id, cid, subject_id)  # first open, committed

    # Simulate the racing opener whose SELECT ran before the first row was visible.
    monkeypatch.setattr(svc, "open_case_exists", lambda *a, **k: False)
    with pytest.raises(DuplicateOpenCase):
        _open(schema, new_workspace.id, cid, subject_id)


def test_refile_allowed_after_withdrawn(new_workspace: Workspace) -> None:
    schema = new_workspace.schema_name
    subject_id = make_subject(schema, enforcement_consent=True)
    cid = add_candidate(schema, subject_id, source_url="https://re.example/x")
    case_id = _open(schema, new_workspace.id, cid, subject_id)

    # Drive to withdrawn, then re-file under a different (supported) claim.
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        svc.transition(
            session,
            workspace_id=new_workspace.id,
            actor_staff_id=None,
            case=case,
            to_status=CaseStatus.filed,
        )
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        svc.transition(
            session,
            workspace_id=new_workspace.id,
            actor_staff_id=None,
            case=case,
            to_status=CaseStatus.withdrawn,
            note="wrong claim",
        )
    with tenant_session(schema) as session:
        case = session.get(Case, case_id)
        assert case is not None
        new_case = svc.refile(
            session,
            workspace_id=new_workspace.id,
            actor_staff_id=None,
            case=case,
            new_claim_type="ncii",
            note="refile",
        )
        new_id = new_case.id

    with tenant_session(schema) as session:
        reloaded = session.get(Case, new_id)
        old_case = session.get(Case, case_id)
        assert reloaded is not None and reloaded.status == CaseStatus.confirmed
        assert reloaded.claim_type == "ncii" and reloaded.candidate_id == cid
        assert old_case is not None and old_case.status == CaseStatus.withdrawn
