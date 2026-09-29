"""Boot-time deployment readiness: object lock + session advisory-lock support are verified,
and the app refuses to start if either fails."""

from __future__ import annotations

import types
from typing import cast

import pytest

from api.app.config import Settings
from api.app.obs import readiness
from api.app.obs.readiness import supports_session_advisory_lock, verify_deployed_readiness


def _deployed() -> Settings:
    # Only .is_deployed is read; a namespace stands in for a full deployed Settings.
    return cast(Settings, types.SimpleNamespace(is_deployed=True))


def test_noop_when_not_deployed() -> None:
    # Default test settings are not a deployment → returns without touching storage/DB.
    verify_deployed_readiness(cast(Settings, types.SimpleNamespace(is_deployed=False)))


def test_raises_when_object_lock_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "api.app.storage.evidence.get_evidence_storage",
        lambda: types.SimpleNamespace(verify_object_lock=lambda: False),
    )
    monkeypatch.setattr(readiness, "supports_session_advisory_lock", lambda: True)
    with pytest.raises(RuntimeError, match="object lock"):
        verify_deployed_readiness(_deployed())


def test_raises_when_advisory_lock_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "api.app.storage.evidence.get_evidence_storage",
        lambda: types.SimpleNamespace(verify_object_lock=lambda: True),
    )
    monkeypatch.setattr(readiness, "supports_session_advisory_lock", lambda: False)
    with pytest.raises(RuntimeError, match="advisory"):
        verify_deployed_readiness(_deployed())


def test_passes_when_both_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "api.app.storage.evidence.get_evidence_storage",
        lambda: types.SimpleNamespace(verify_object_lock=lambda: True),
    )
    monkeypatch.setattr(readiness, "supports_session_advisory_lock", lambda: True)
    verify_deployed_readiness(_deployed())


def test_real_db_supports_session_advisory_lock(db: object) -> None:
    # The test DB is a direct connection (not a transaction pooler), so the probe passes.
    assert supports_session_advisory_lock() is True
