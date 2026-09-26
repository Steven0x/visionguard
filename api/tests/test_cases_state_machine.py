"""Slice 6: the case state machine — every legal edge works, every illegal pair is rejected,
filing preconditions are re-checked, withdrawn needs a note, and concurrent moves can't race.

All cases live in one shared workspace (a fresh tenant schema per parametrization would be slow
and can exhaust Postgres shared memory); each test builds its own subject + case.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from api.app.db.session import tenant_session
from api.app.models.cases import Case, CaseEvent, CaseEventKind, CaseStatus
from api.app.models.public import Workspace
from api.app.services import cases as svc
from api.app.services.cases import (
    TRANSITIONS,
    CaseConflict,
    CasePreconditionFailed,
    IllegalTransition,
)
from api.app.services.workspaces import create_workspace_with_access
from api.tests.conftest import Fixtures

from .casehelpers import make_case
from .reviewhelpers import make_subject

_ALL = list(CaseStatus)
_LEGAL: set[tuple[CaseStatus, CaseStatus]] = {
    (f, t) for f, tos in TRANSITIONS.items() for t in tos
}
_ILLEGAL: list[tuple[CaseStatus, CaseStatus]] = [
    (f, t) for f in _ALL for t in _ALL if f != t and (f, t) not in _LEGAL
]


@pytest.fixture(scope="module")
def ws(db: Fixtures) -> Workspace:
    slug = f"sm-{uuid.uuid4().hex[:8]}"
    return create_workspace_with_access(name=slug, creator_staff_id=db.admin_staff_id, slug=slug)


def _transition(ws: Workspace, case_id: int, to: CaseStatus, *, note: str | None = None) -> Case:
    with tenant_session(ws.schema_name) as session:
        case = session.get(Case, case_id)
        assert case is not None
        return svc.transition(
            session, workspace_id=ws.id, actor_staff_id=None, case=case, to_status=to, note=note
        )


@pytest.mark.parametrize(("from_status", "to_status"), _ILLEGAL)
def test_illegal_transitions_are_rejected(
    ws: Workspace, from_status: CaseStatus, to_status: CaseStatus
) -> None:
    subject_id = make_subject(ws.schema_name, enforcement_consent=True)
    case_id = make_case(ws.schema_name, subject_id, status=from_status)
    with pytest.raises(IllegalTransition):
        _transition(ws, case_id, to_status, note="n")


@pytest.mark.parametrize(("from_status", "to_status"), sorted(_LEGAL))
def test_legal_transitions_succeed_and_write_event(
    ws: Workspace, from_status: CaseStatus, to_status: CaseStatus
) -> None:
    subject_id = make_subject(ws.schema_name, enforcement_consent=True)  # enforceable + likeness
    case_id = make_case(ws.schema_name, subject_id, status=from_status, claim_type="likeness")
    updated = _transition(ws, case_id, to_status, note="n")
    assert updated.status == to_status
    with tenant_session(ws.schema_name) as session:
        events = session.scalars(
            select(CaseEvent).where(
                CaseEvent.case_id == case_id, CaseEvent.kind == CaseEventKind.transition
            )
        ).all()
        assert any(
            e.from_status == from_status.value and e.to_status == to_status.value for e in events
        )


def test_filed_requires_active_authorization(new_workspace: Workspace) -> None:
    # A FRESH workspace: the shared `ws` carries a workspace-level authorization from other
    # tests (which makes every subject enforceable), so the negative case needs a clean schema.
    subject_id = make_subject(new_workspace.schema_name, authorized=False, enforcement_consent=True)
    case_id = make_case(
        new_workspace.schema_name, subject_id, status=CaseStatus.confirmed, claim_type="likeness"
    )
    with pytest.raises(CasePreconditionFailed):
        _transition(new_workspace, case_id, CaseStatus.filed, note="n")


def test_filed_requires_supported_claim(ws: Workspace) -> None:
    # Authorized but no enforcement consent → likeness is NOT supported.
    subject_id = make_subject(ws.schema_name, enforcement_consent=False)
    case_id = make_case(
        ws.schema_name, subject_id, status=CaseStatus.confirmed, claim_type="likeness"
    )
    with pytest.raises(CasePreconditionFailed):
        _transition(ws, case_id, CaseStatus.filed, note="n")


def test_withdraw_requires_a_note(ws: Workspace) -> None:
    subject_id = make_subject(ws.schema_name, enforcement_consent=True)
    case_id = make_case(ws.schema_name, subject_id, status=CaseStatus.filed, claim_type="likeness")
    with pytest.raises(CasePreconditionFailed):
        _transition(ws, case_id, CaseStatus.withdrawn, note=None)
    assert _transition(ws, case_id, CaseStatus.withdrawn, note="wrong claim").status == (
        CaseStatus.withdrawn
    )


def test_concurrent_transition_conflict(ws: Workspace) -> None:
    subject_id = make_subject(ws.schema_name, enforcement_consent=True)
    case_id = make_case(
        ws.schema_name, subject_id, status=CaseStatus.confirmed, claim_type="likeness"
    )
    with tenant_session(ws.schema_name) as session_a:
        case = session_a.get(Case, case_id)
        assert case is not None  # in-memory status is still 'confirmed'
        # Another actor advances the row in a separate committed transaction.
        with tenant_session(ws.schema_name) as session_b:
            other = session_b.get(Case, case_id)
            assert other is not None
            other.status = CaseStatus.filed
        with pytest.raises(CaseConflict):
            svc.transition(
                session_a,
                workspace_id=ws.id,
                actor_staff_id=None,
                case=case,
                to_status=CaseStatus.filed,
                note="n",
            )
