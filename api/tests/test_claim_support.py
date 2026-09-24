"""Claim-support derivation from the (draft) claims matrix."""

from __future__ import annotations

from datetime import date, timedelta

from api.app.db.session import tenant_session
from api.app.models.public import Workspace
from api.app.models.rights import (
    AgentAuthorization,
    ConsentRecord,
    ConsentType,
    RecordStatus,
    RightsRecord,
    RightsStatus,
    RightsType,
)
from api.app.models.subjects import Subject
from api.app.services.claim_support import (
    claim_support,
    subject_enforcement,
)

_TODAY = date(2026, 1, 1)


def _support(
    schema: str,
    *,
    rights: tuple[dict, ...] = (),
    enforcement_consent: bool = False,
    workspace_auth: bool = False,
    subject_auth: bool = False,
):
    with tenant_session(schema) as s:
        subject = Subject(legal_name="s")
        s.add(subject)
        s.flush()
        for spec in rights:
            s.add(
                RightsRecord(
                    subject_id=subject.id,
                    file_key="k",
                    file_name="f.pdf",
                    content_type="application/pdf",
                    **spec,
                )
            )
        if enforcement_consent:
            s.add(
                ConsentRecord(
                    subject_id=subject.id,
                    type=ConsentType.enforcement,
                    file_key="k",
                    file_name="c.pdf",
                    content_type="application/pdf",
                    signer_name="x",
                    signed_date=_TODAY,
                    status=RecordStatus.active,
                )
            )
        if workspace_auth:
            s.add(AgentAuthorization(subject_id=None, signer_name="a", authorized_date=_TODAY))
        if subject_auth:
            s.add(
                AgentAuthorization(
                    subject_id=subject.id, signer_name="a", authorized_date=_TODAY
                )
            )
        s.flush()
        support = {c.claim_type: c.supported for c in claim_support(s, subject)}
        return support, subject_enforcement(s, subject)["enforceable"]


def test_nothing_supported_without_authorization(db, new_workspace: Workspace) -> None:
    support, enforceable = _support(
        new_workspace.schema_name,
        rights=({"type": RightsType.self_owned_declaration},),
        enforcement_consent=True,
    )
    assert enforceable is False
    assert not any(support.values())


def test_management_agreement_alone_does_not_support_copyright(
    db, new_workspace: Workspace
) -> None:
    support, _ = _support(
        new_workspace.schema_name,
        rights=({"type": RightsType.management_agreement},),
        workspace_auth=True,
    )
    assert support["copyright"] is False


def test_photographer_license_requires_enforcement_right_flag(
    db, new_workspace: Workspace
) -> None:
    no_flag, _ = _support(
        new_workspace.schema_name,
        rights=({"type": RightsType.photographer_license, "grants_enforcement_right": False},),
        workspace_auth=True,
    )
    assert no_flag["copyright"] is False

    with_flag, _ = _support(
        new_workspace.schema_name,
        rights=({"type": RightsType.photographer_license, "grants_enforcement_right": True},),
        workspace_auth=True,
    )
    assert with_flag["copyright"] is True


def test_ownership_records_support_copyright(db, new_workspace: Workspace) -> None:
    for rtype in (RightsType.self_owned_declaration, RightsType.copyright_registration):
        support, _ = _support(
            new_workspace.schema_name, rights=({"type": rtype},), workspace_auth=True
        )
        assert support["copyright"] is True


def test_expired_or_revoked_rights_do_not_support_copyright(
    db, new_workspace: Workspace
) -> None:
    expired, _ = _support(
        new_workspace.schema_name,
        rights=(
            {
                "type": RightsType.self_owned_declaration,
                "expires_on": _TODAY - timedelta(days=1),
            },
        ),
        workspace_auth=True,
    )
    assert expired["copyright"] is False

    revoked, _ = _support(
        new_workspace.schema_name,
        rights=(
            {"type": RightsType.copyright_registration, "status": RightsStatus.revoked},
        ),
        workspace_auth=True,
    )
    assert revoked["copyright"] is False


def test_enforcement_consent_supports_likeness_family(db, new_workspace: Workspace) -> None:
    support, _ = _support(
        new_workspace.schema_name, enforcement_consent=True, subject_auth=True
    )
    assert support["likeness"] is True
    assert support["ncii"] is True
    assert support["impersonation"] is True
    assert support["copyright"] is False  # no ownership record


def test_trademark_never_supported_in_people_mode(db, new_workspace: Workspace) -> None:
    support, _ = _support(
        new_workspace.schema_name,
        rights=({"type": RightsType.self_owned_declaration},),
        enforcement_consent=True,
        workspace_auth=True,
    )
    assert support["trademark"] is False


def test_subject_level_authorization_enables_enforcement(
    db, new_workspace: Workspace
) -> None:
    _, enforceable = _support(new_workspace.schema_name, subject_auth=True)
    assert enforceable is True


def test_subject_level_auth_does_not_leak_to_other_subject(
    db, new_workspace: Workspace
) -> None:
    with tenant_session(new_workspace.schema_name) as s:
        x = Subject(legal_name="X")
        y = Subject(legal_name="Y")
        s.add_all([x, y])
        s.flush()
        s.add(AgentAuthorization(subject_id=x.id, signer_name="a", authorized_date=_TODAY))
        s.flush()
        assert subject_enforcement(s, x)["enforceable"] is True
        assert subject_enforcement(s, y)["enforceable"] is False
        assert not any(c.supported for c in claim_support(s, y))
