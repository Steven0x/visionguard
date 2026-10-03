"""RFC 3161 timestamping over the evidence manifest, behind a backend.

`rfc3161` (prod) tries several TSAs, first answer wins; `fake` (tests/CI) returns a
deterministic token. Neither raises — evidence is still sealed if timestamping fails, marked
`untimestamped` and retried by a beat task.

The real path uses sigstore's `rfc3161-client` (Rust-backed, strict DER). The stored token is
the full DER-encoded `TimeStampResp` (with the TSA's signing cert embedded, `certReq=True`).

Trust is anchored to **roots pinned in the repo** (`evidence_roots/tsa_pinned_roots.pem`), NOT
to the CA embedded in the token. This matters for chain-of-custody (CLAUDE.md #6): if we trusted
the embedded CA, anyone who could write to the evidence store could mint a token with a self-made
CA + signing cert and have it "verify", backdating or re-pointing evidence at will. Verification
therefore: (1) picks the signing cert in the token that carries the `timeStamping` EKU, (2)
requires it to chain to a pinned root (through pinned intermediates), and (3) checks the signature
covers exactly these manifest bytes. Adding a TSA means pinning its root here. At request time we
also check the TSA echoed our nonce (replay/substitution defence during acquisition).

Note: `rfc3161-client` is strict about DER ordering in the response's certificate SET; some
public TSAs (DigiCert, Sectigo, Apple) return a non-sorted SET it refuses to parse, so the TSA
list is the two we pin and have verified end-to-end (freetsa.org and sigstore). Incompatible
TSAs are skipped like any other failure and the next one is tried.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from api.app.config import get_settings

_FAKE_PREFIX = b"vg-fake-tsa-v1:"
_TSA_CONTENT_TYPE = "application/timestamp-query"
_ROOTS_DIR = Path(__file__).parent / "evidence_roots"


@dataclass
class TimestampResult:
    token: bytes | None
    tsa_url: str | None
    tsa_time: datetime | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.token is not None


def get_timestamp(manifest_bytes: bytes) -> TimestampResult:
    settings = get_settings()
    if settings.tsa_backend == "fake":
        token = _FAKE_PREFIX + hashlib.sha256(manifest_bytes).digest()
        return TimestampResult(token=token, tsa_url="fake-tsa", tsa_time=datetime.now(UTC),
                               error=None)
    return _rfc3161_timestamp(manifest_bytes, settings.tsa_url_list)


def verify_timestamp(token: bytes, manifest_bytes: bytes) -> bool:
    """True if the token is a valid timestamp over exactly these manifest bytes, signed by a
    TSA that chains to a pinned root."""
    if token.startswith(_FAKE_PREFIX):
        return token == _FAKE_PREFIX + hashlib.sha256(manifest_bytes).digest()
    try:  # pragma: no cover - real TSA path, exercised only with the [capture] extra
        from rfc3161_client import decode_timestamp_response

        response = decode_timestamp_response(token)
        _build_verifier(response).verify_message(response, manifest_bytes)
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _pinned_certs() -> tuple[list[Any], list[Any]]:  # pragma: no cover - real TSA path
    from cryptography import x509

    def _load(name: str) -> list[Any]:
        path = _ROOTS_DIR / name
        return x509.load_pem_x509_certificates(path.read_bytes()) if path.exists() else []

    return _load("tsa_pinned_roots.pem"), _load("tsa_pinned_intermediates.pem")


def _signing_cert(certs: list[Any]) -> Any:  # pragma: no cover - real TSA path
    """The cert that signed the token: the one bearing the timeStamping EKU. Reject if absent —
    a timestamp signer MUST carry id-kp-timeStamping (RFC 3161 §2.3)."""
    from cryptography import x509
    from cryptography.x509.oid import ExtendedKeyUsageOID

    for cert in certs:
        try:
            eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        except x509.ExtensionNotFound:
            continue
        if ExtendedKeyUsageOID.TIME_STAMPING in eku:
            return cert
    raise ValueError("token has no signing cert with the timeStamping EKU")


def _build_verifier(response: Any) -> Any:  # pragma: no cover - real TSA path
    """Build a Verifier that trusts only the pinned roots. The signing leaf comes from the token
    (TSAs rotate signing certs) but it must chain to a root we shipped, not to the token's own CA.
    """
    from cryptography import x509
    from rfc3161_client import VerifierBuilder

    certs = [x509.load_der_x509_certificate(c) for c in response.signed_data.certificates]
    leaf = _signing_cert(certs)
    roots, intermediates = _pinned_certs()
    if not roots:
        raise ValueError("no pinned TSA roots available ([capture] extra / evidence_roots)")
    builder = VerifierBuilder().tsa_certificate(leaf)
    for root in roots:
        builder = builder.add_root_certificate(root)
    for intermediate in intermediates:
        builder = builder.add_intermediate_certificate(intermediate)
    return builder.build()


def _rfc3161_timestamp(
    manifest_bytes: bytes, tsa_urls: list[str]
) -> TimestampResult:  # pragma: no cover - real TSA path
    try:
        import httpx
        from rfc3161_client import TimestampRequestBuilder, decode_timestamp_response
    except ImportError:
        return TimestampResult(None, None, None, "rfc3161-client not installed ([capture] extra)")
    request = TimestampRequestBuilder().data(manifest_bytes).build()
    errors = []
    for url in tsa_urls:
        try:
            resp = httpx.post(
                url,
                content=request.as_bytes(),
                headers={"Content-Type": _TSA_CONTENT_TYPE},
                timeout=20,
            )
            resp.raise_for_status()
            # Parse to surface a bad/unsupported response now (and read the TSA time), but
            # store the raw DER so verification re-parses exactly what the TSA returned.
            response = decode_timestamp_response(resp.content)
            if response.tst_info.nonce != request.nonce:
                raise ValueError("TSA response nonce does not match the request")
            if not verify_timestamp(resp.content, manifest_bytes):
                raise ValueError("token failed verification against the pinned TSA roots")
            return TimestampResult(
                token=resp.content,
                tsa_url=url,
                tsa_time=response.tst_info.gen_time,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001 - try the next TSA
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    return TimestampResult(None, None, None, " | ".join(errors))
