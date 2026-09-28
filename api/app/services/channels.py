"""Channel registry lookups (Slice 8). Channels are global public reference data; these read
functions accept any session (a tenant session reaches public tables unqualified). Routing obeys
docs/legal/claims-matrix.md — enforced here as defense-in-depth over the validated seed."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.app.models.channels import Channel
from api.app.notices_matrix import method_allowed_for_claim


class ChannelNotFound(Exception):
    """No active channel routes this platform + claim type."""


class MatrixViolation(Exception):
    """The routed channel's method is forbidden for this claim by the claims matrix."""


def route_for(session: Session, *, platform: str, claim_type: str) -> Channel:
    channel = session.scalar(
        select(Channel).where(
            Channel.platform == platform,
            Channel.claim_type == claim_type,
            Channel.active.is_(True),
        )
    )
    if channel is None:
        raise ChannelNotFound(
            f"no active channel for platform {platform!r} + claim {claim_type!r}"
        )
    # Defense-in-depth: never route a claim over a method the matrix forbids (e.g. DMCA/email
    # for trademark/likeness), even if a bad row slipped past the seed guard.
    if not method_allowed_for_claim(claim_type, str(channel.method)):
        raise MatrixViolation(
            f"claim {claim_type!r} may not be routed via {channel.method!r} "
            "(claims matrix): never DMCA/email for trademark or likeness"
        )
    return channel


def list_channels(session: Session) -> list[Channel]:
    return list(
        session.scalars(select(Channel).order_by(Channel.platform, Channel.claim_type)).all()
    )


def get_channel(session: Session, channel_id: int) -> Channel | None:
    return session.get(Channel, channel_id)
