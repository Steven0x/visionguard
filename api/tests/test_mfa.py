"""Server-side MFA enforcement: when CLERK_REQUIRE_MFA is set, a session without a verified
second factor (Clerk `fva` claim) is rejected. Dev/test (require_mfa off) is unaffected."""

from __future__ import annotations

import pytest

from api.app.auth.clerk import AuthError, make_test_token, verify_token
from api.app.config import Settings


def _settings(require_mfa: bool) -> Settings:
    # Blank ALLOWED_ORIGINS disables the azp check so these tests isolate the MFA behaviour.
    return Settings(
        app_env="test", auth_test_mode=True, allowed_origins="", clerk_require_mfa=require_mfa
    )


def test_token_without_fva_rejected_when_mfa_required() -> None:
    settings = _settings(require_mfa=True)
    token = make_test_token("admin_user", mfa=None)  # no fva claim at all
    with pytest.raises(AuthError, match="multi-factor"):
        verify_token(token, settings)


def test_token_with_unverified_second_factor_rejected() -> None:
    settings = _settings(require_mfa=True)
    token = make_test_token("admin_user", mfa=False)  # fva second factor = -1
    with pytest.raises(AuthError, match="multi-factor"):
        verify_token(token, settings)


def test_token_with_verified_mfa_accepted() -> None:
    settings = _settings(require_mfa=True)
    token = make_test_token("admin_user", mfa=True)
    claims = verify_token(token, settings)
    assert claims.subject == "admin_user" and claims.mfa_verified is True


def test_default_dev_path_unaffected() -> None:
    settings = _settings(require_mfa=False)
    claims = verify_token(make_test_token("admin_user"), settings)
    assert claims.subject == "admin_user" and claims.mfa_verified is False
