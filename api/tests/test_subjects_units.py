"""Unit tests for the pure subject helpers (no DB)."""

from __future__ import annotations

import pytest

from api.app.services.subjects import (
    compute_biometrics_blocked,
    normalize_handles,
    normalize_residence,
    normalize_stage_names,
)


def test_normalize_handles_trims_strips_at_lowercases_and_dedupes() -> None:
    result = normalize_handles(["@JaneDoe", " janedoe ", "IG:@JaneDoe", "", "  "])
    assert result == ["janedoe", "ig:janedoe"]


def test_normalize_handles_preserves_platform_prefix_lowercased() -> None:
    assert normalize_handles(["TW:Foo", "tw:foo"]) == ["tw:foo"]


def test_normalize_handles_does_not_treat_url_scheme_as_platform() -> None:
    # "http://x" must not become platform "http".
    assert normalize_handles(["http://x"]) == ["http://x"]


def test_normalize_stage_names_trims_and_dedupes_preserving_case() -> None:
    assert normalize_stage_names([" Jane ", "Jane", "", "JANE"]) == ["Jane", "JANE"]


def test_normalize_residence() -> None:
    assert normalize_residence(" ca ") == "CA"
    assert normalize_residence("") is None
    assert normalize_residence(None) is None


@pytest.mark.parametrize(
    ("state", "blocked"),
    [
        ("CA", False),  # valid US state outside IL/WA → allowed
        ("NY", False),
        ("IL", True),  # geo-blocked
        ("WA", True),
        (None, True),  # unknown → fail closed
        ("ZZ", True),  # non-US / invalid → fail closed
    ],
)
def test_compute_biometrics_blocked_fails_closed(state: str | None, blocked: bool) -> None:
    assert compute_biometrics_blocked(state) is blocked
