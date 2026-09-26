"""RFC 3161 timestamping over the evidence manifest, behind a backend.

`rfc3161` (prod) tries several TSAs, first answer wins; `fake` (tests/CI) returns a
deterministic token. Neither raises — evidence is still sealed if timestamping fails, marked
`untimestamped` and retried by a beat task.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from api.app.config import get_settings

_FAKE_PREFIX = b"vg-fake-tsa-v1:"


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
        import rfc3161ng

        rfc3161ng.check_timestamp(token, data=manifest_bytes, hashname="sha256")
        return True
    except Exception:
        return False


def _rfc3161_timestamp(
    manifest_bytes: bytes, tsa_urls: list[str]
) -> TimestampResult:  # pragma: no cover - real TSA path
    try:
        import rfc3161ng
    except ImportError:
        return TimestampResult(None, None, None, "rfc3161ng not installed ([capture] extra)")
    errors = []
    for url in tsa_urls:
        try:
            ts = rfc3161ng.RemoteTimestamper(
                url, hashname="sha256", include_tsa_certificate=True, timeout=20
            )
            token = ts.timestamp(data=manifest_bytes)
            rfc3161ng.check_timestamp(token, data=manifest_bytes, hashname="sha256")
            tsa_time = rfc3161ng.get_timestamp(token)
            return TimestampResult(token=token, tsa_url=url, tsa_time=tsa_time, error=None)
        except Exception as exc:  # noqa: BLE001 - try the next TSA
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    return TimestampResult(None, None, None, " | ".join(errors))
