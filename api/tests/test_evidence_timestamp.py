"""RFC 3161 timestamp verification (api/app/evidence_ts.py).

Covers the deterministic `fake` token and — when the `[capture]` extra is installed — the real
`rfc3161-client` path: recorded freetsa.org and sigstore tokens that must verify against the
pinned roots, a *forged* self-anchored token that must be REJECTED (CLAUDE.md #6 trust
anchoring), tamper rejection, and the timeStamping-EKU requirement on the signer.

Fixtures in `fixtures/` were recorded over `REAL_MANIFEST`:
- `freetsa_token.tsr`, `sigstore_token.tsr` — real tokens from those TSAs.
- `forged_token.tsr` — a structurally valid token signed by a *self-made* CA + TSA cert (openssl
  `ts`), both embedded in the token. It parses and its signer even carries the timeStamping EKU,
  so it is the exact attack the pinned-root anchoring must defeat.
Regenerate the real ones by POSTing a request built over `REAL_MANIFEST` to each TSA.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from api.app.evidence_ts import _FAKE_PREFIX, verify_timestamp

# Must match the bytes the recorded tokens were stamped over.
REAL_MANIFEST = b"visionguard-evidence-manifest-fixture-v1"
_FIX = Path(__file__).parent / "fixtures"


def test_fake_token_verifies_over_its_manifest() -> None:
    manifest = b"some-evidence-manifest"
    token = _FAKE_PREFIX + hashlib.sha256(manifest).digest()
    assert verify_timestamp(token, manifest) is True
    assert verify_timestamp(token, manifest + b"tampered") is False


@pytest.mark.parametrize("fixture", ["freetsa_token.tsr", "sigstore_token.tsr"])
def test_recorded_real_tsa_token_verifies(fixture: str) -> None:
    pytest.importorskip("rfc3161_client", reason="real TSA path needs the [capture] extra")
    token = (_FIX / fixture).read_bytes()
    assert verify_timestamp(token, REAL_MANIFEST) is True


@pytest.mark.parametrize("fixture", ["freetsa_token.tsr", "sigstore_token.tsr"])
def test_recorded_real_tsa_token_rejects_tampered_manifest(fixture: str) -> None:
    pytest.importorskip("rfc3161_client", reason="real TSA path needs the [capture] extra")
    token = (_FIX / fixture).read_bytes()
    assert verify_timestamp(token, REAL_MANIFEST + b"x") is False
    assert verify_timestamp(token, b"") is False


def test_forged_self_anchored_token_is_rejected() -> None:
    """A token signed by a self-made CA embedded in the token must FAIL: trust is anchored to
    the pinned roots, not the token's own CA (CLAUDE.md #6)."""
    pytest.importorskip("rfc3161_client", reason="real TSA path needs the [capture] extra")
    forged = (_FIX / "forged_token.tsr").read_bytes()
    # Sanity: it really is a parseable token over REAL_MANIFEST (so rejection is about trust,
    # not a parse error) — and its signer even carries the timeStamping EKU.
    from cryptography import x509
    from rfc3161_client import decode_timestamp_response

    from api.app.evidence_ts import _signing_cert

    response = decode_timestamp_response(forged)
    certs = [x509.load_der_x509_certificate(c) for c in response.signed_data.certificates]
    assert _signing_cert(certs) is not None  # has a timeStamping-EKU signer
    assert verify_timestamp(forged, REAL_MANIFEST) is False


def test_signing_cert_requires_timestamping_eku() -> None:
    pytest.importorskip("rfc3161_client", reason="needs cryptography/rfc3161-client")
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    from api.app.evidence_ts import _signing_cert

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "no-eku")])
    base = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime(2020, 1, 1))
        .not_valid_after(dt.datetime(2040, 1, 1))
    )
    no_eku = base.sign(key, hashes.SHA256())
    with pytest.raises(ValueError, match="timeStamping"):
        _signing_cert([no_eku])

    with_eku = base.add_extension(
        x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]), critical=True
    ).sign(key, hashes.SHA256())
    assert _signing_cert([with_eku]) is with_eku
