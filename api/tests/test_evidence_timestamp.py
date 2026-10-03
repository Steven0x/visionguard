"""RFC 3161 timestamp verification (api/app/evidence_ts.py).

Covers both the deterministic `fake` token and — when the `[capture]` extra is installed — a
recorded *real* freetsa.org RFC 3161 token that must verify against its exact manifest bytes
and must be rejected when the manifest is tampered. The fixture was recorded with
`rfc3161-client`; regenerate it by POSTing a request built over `REAL_MANIFEST` to
https://freetsa.org/tsr (see the module docstring in evidence_ts.py).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from api.app.evidence_ts import _FAKE_PREFIX, verify_timestamp

# Must match the bytes the recorded token was stamped over (see fixtures/freetsa_token.tsr).
REAL_MANIFEST = b"visionguard-evidence-manifest-fixture-v1"
_TOKEN_PATH = Path(__file__).parent / "fixtures" / "freetsa_token.tsr"


def test_fake_token_verifies_over_its_manifest() -> None:
    manifest = b"some-evidence-manifest"
    token = _FAKE_PREFIX + hashlib.sha256(manifest).digest()
    assert verify_timestamp(token, manifest) is True
    assert verify_timestamp(token, manifest + b"tampered") is False


def test_recorded_real_tsa_token_verifies() -> None:
    pytest.importorskip("rfc3161_client", reason="real TSA path needs the [capture] extra")
    token = _TOKEN_PATH.read_bytes()
    assert verify_timestamp(token, REAL_MANIFEST) is True


def test_recorded_real_tsa_token_rejects_tampered_manifest() -> None:
    pytest.importorskip("rfc3161_client", reason="real TSA path needs the [capture] extra")
    token = _TOKEN_PATH.read_bytes()
    assert verify_timestamp(token, REAL_MANIFEST + b"x") is False
    assert verify_timestamp(token, b"") is False
