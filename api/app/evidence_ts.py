"""RFC 3161 timestamping over the evidence manifest, behind a backend.

`rfc3161` (prod) tries several TSAs, first answer wins; `fake` (tests/CI) returns a
deterministic token. Neither raises — evidence is still sealed if timestamping fails, marked
`untimestamped` and retried by a beat task.

The real path uses sigstore's `rfc3161-client` (Rust-backed, strict DER). The stored token is
the full DER-encoded `TimeStampResp` (with the TSA's signing chain embedded,
`certReq=True`). Verification re-parses that response and checks the signature over exactly
these manifest bytes against the embedded signing cert — detecting any tampering of the token
or the manifest. (We replaced `rfc3161ng`, which could not verify EC-signed tokens and
mis-encoded the signed attributes as BER so RSA tokens failed too.)

Note: `rfc3161-client` is strict about DER ordering in the response's certificate SET; some
public TSAs (DigiCert, Sectigo) return a non-sorted SET it refuses to parse, so the TSA list
should lead with a compatible TSA (e.g. freetsa.org). Incompatible TSAs are skipped like any
other failure and the next one is tried.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from api.app.config import get_settings

_FAKE_PREFIX = b"vg-fake-tsa-v1:"
_TSA_CONTENT_TYPE = "application/timestamp-query"


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
    """True if the token is a valid timestamp over exactly these manifest bytes."""
    if token.startswith(_FAKE_PREFIX):
        return token == _FAKE_PREFIX + hashlib.sha256(manifest_bytes).digest()
    try:  # pragma: no cover - real TSA path, exercised only with the [capture] extra
        from rfc3161_client import decode_timestamp_response

        response = decode_timestamp_response(token)
        verifier = _build_verifier(response)
        verifier.verify_message(response, manifest_bytes)
        return True
    except Exception:
        return False


def _build_verifier(response: Any) -> Any:  # pragma: no cover - real TSA path
    """Build a Verifier trusting the signing chain embedded in the response.

    The TSA cert is in the token (`certReq=True` at request time), so verification is
    self-contained: the signer (the non-CA leaf) must chain to the embedded CA(s) and its
    signature must cover the manifest. Pinning the TSA's out-of-band root is a future hardening.
    """
    from cryptography import x509
    from rfc3161_client import VerifierBuilder

    certs = [x509.load_der_x509_certificate(c) for c in response.signed_data.certificates]

    def _is_ca(cert: x509.Certificate) -> bool:
        try:
            return cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
        except x509.ExtensionNotFound:
            return False

    leaf = next(c for c in certs if not _is_ca(c))
    builder = VerifierBuilder().tsa_certificate(leaf)
    for ca in (c for c in certs if _is_ca(c)):
        builder = builder.add_root_certificate(ca)
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
            if not verify_timestamp(resp.content, manifest_bytes):
                raise ValueError("token failed self-verification")
            return TimestampResult(
                token=resp.content,
                tsa_url=url,
                tsa_time=response.tst_info.gen_time,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001 - try the next TSA
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    return TimestampResult(None, None, None, " | ".join(errors))
