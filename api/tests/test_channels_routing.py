"""Channel registry conforms to the claims matrix: never DMCA/email for trademark/likeness."""

from __future__ import annotations

import pytest

from api.app.db.session import public_session
from api.app.notices_matrix import method_allowed_for_claim
from api.app.services.channels import ChannelNotFound, list_channels, route_for
from api.tests.conftest import Fixtures


def test_every_seeded_channel_conforms_to_matrix(db: Fixtures) -> None:
    with public_session() as session:
        channels = list_channels(session)
    assert channels, "channels should be seeded by the public migration"
    for c in channels:
        assert method_allowed_for_claim(c.claim_type, str(c.method)), (
            f"seed violates matrix: {c.platform} {c.claim_type} via {c.method}"
        )


def test_trademark_and_likeness_never_route_to_email() -> None:
    # The load-bearing matrix rule (CLAUDE.md #4): no DMCA/email for trademark or likeness.
    assert not method_allowed_for_claim("trademark", "email")
    assert not method_allowed_for_claim("likeness", "email")
    assert method_allowed_for_claim("copyright", "email")


def test_no_email_channel_exists_for_trademark_or_likeness(db: Fixtures) -> None:
    with public_session() as session:
        channels = list_channels(session)
    offenders = [
        c for c in channels
        if str(c.method) == "email" and c.claim_type in ("trademark", "likeness")
    ]
    assert offenders == []


def test_route_for_copyright_email_resolves(db: Fixtures) -> None:
    with public_session() as session:
        channel = route_for(session, platform="generic_host", claim_type="copyright")
    assert str(channel.method) == "email"


def test_route_for_unknown_pairing_raises(db: Fixtures) -> None:
    with public_session() as session, pytest.raises(ChannelNotFound):
        route_for(session, platform="instagram", claim_type="trademark")
