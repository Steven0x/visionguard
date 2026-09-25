"""SSRF guards: URL scheme/port validation and IP allow-listing. Pure and unit-tested."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


class SsrfError(Exception):
    """Raised when a URL/target is not safe to fetch."""


_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443}
# Cloud metadata endpoints (IPv4 link-local + AWS IMDS IPv6).
_METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}


def validate_url(url: str) -> tuple[str, str, int]:
    """Return (scheme, host, port) if the URL is http(s) on port 80/443, else raise."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SsrfError(f"scheme not allowed: {scheme or '(none)'}")
    host = parts.hostname
    if not host:
        raise SsrfError("missing host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise SsrfError("invalid port") from exc
    if port not in _ALLOWED_PORTS:
        raise SsrfError(f"port not allowed: {port}")
    return scheme, host, port


def is_ip_allowed(ip_str: str) -> bool:
    """Allow only globally-routable public IPs (blocks private/loopback/link-local/CGNAT/
    multicast/reserved/ULA and cloud-metadata addresses)."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) and judge the embedded v4.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return is_ip_allowed(str(ip.ipv4_mapped))
    if ip in _METADATA_IPS:
        return False
    # is_global is False for private, loopback, link-local, CGNAT, ULA, reserved, etc.
    if not ip.is_global:
        return False
    if ip.is_multicast:
        return False
    return True


def require_allowed_ip(ip_str: str) -> None:
    if not is_ip_allowed(ip_str):
        raise SsrfError(f"blocked IP address: {ip_str}")
