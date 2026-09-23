"""Clerk session-token verification.

In production the token is an RS256 JWT verified against Clerk's JWKS (issuer, optional
audience, and the ``azp`` authorized-party claim against our allowed origins).

When ``AUTH_TEST_MODE`` is on (only permitted in dev/test — enforced in config), tokens are
HS256-signed with a fixed local secret so pytest/CI need no live Clerk. Tests mint tokens
with :func:`make_test_token`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from api.app.config import Settings

# Only ever used when auth_test_mode is true (dev/test). 32+ bytes to satisfy HS256.
TEST_JWT_SECRET = "vg-auth-test-secret-not-for-production-use"  # noqa: S105


class AuthError(Exception):
    """Raised when a token is missing, malformed, or fails verification."""


@dataclass(frozen=True)
class ClerkClaims:
    subject: str
    azp: str | None


@lru_cache(maxsize=8)
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    # Keyed by URL, and lets PyJWKClient cache/rotate signing keys (5-min lifespan) so a
    # Clerk key rotation is picked up without a process restart.
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300)


def _decode(token: str, settings: Settings) -> dict:
    if settings.auth_test_mode:
        return jwt.decode(
            token,
            TEST_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False, "require": ["exp"], "verify_exp": True},
        )

    if not settings.clerk_jwks_url:
        raise AuthError("Clerk JWKS URL is not configured")

    signing_key = _get_jwks_client(settings.clerk_jwks_url).get_signing_key_from_jwt(token)
    options: Any = {}  # PyJWT's Options TypedDict; a plain dict is fine at runtime.
    kwargs: dict[str, Any] = {}
    if settings.clerk_audience:
        kwargs["audience"] = settings.clerk_audience
    else:
        options["verify_aud"] = False
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=settings.clerk_jwt_issuer or None,
        options=options,
        **kwargs,
    )


def verify_token(token: str, settings: Settings) -> ClerkClaims:
    """Verify a Clerk token and return its claims, or raise :class:`AuthError`."""
    try:
        payload = _decode(token, settings)
    except AuthError:
        raise
    except Exception as exc:  # jwt.* errors, key fetch failures, etc.
        raise AuthError(f"token verification failed: {exc}") from exc

    subject = payload.get("sub")
    if not subject:
        raise AuthError("token has no subject")

    # When allowed origins are configured, the authorized-party (azp) claim must be present
    # AND in the list. Absence is a rejection, not a pass — a token minted for another app
    # (or one with azp stripped) must not authenticate here.
    azp = payload.get("azp")
    allowed = settings.allowed_origin_list
    if allowed and (azp is None or azp not in allowed):
        raise AuthError(f"azp {azp!r} is not an allowed origin")

    return ClerkClaims(subject=subject, azp=azp)


def make_test_token(
    clerk_user_id: str, *, azp: str | None = None, expires_in: int = 3600
) -> str:
    """Mint an HS256 token for tests (only valid when AUTH_TEST_MODE is on)."""
    now = int(time.time())
    claims: dict[str, Any] = {"sub": clerk_user_id, "iat": now, "exp": now + expires_in}
    if azp is not None:
        claims["azp"] = azp
    return jwt.encode(claims, TEST_JWT_SECRET, algorithm="HS256")
