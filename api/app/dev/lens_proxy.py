"""DEV-ONLY reverse-image asset proxy for `make lens-tunnel`.

Local MinIO presigns `localhost` URLs that Google Lens / Yandex can't reach, so a real
reverse-image scan finds nothing. `make lens-tunnel` exposes MinIO through a cloudflared quick
tunnel — but a raw tunnel to MinIO would publish the whole server (every bucket, listings, the
console, writes). This proxy sits between the tunnel and MinIO and allows ONLY what Lens needs:

    GET /<assets-bucket>/<key>?...X-Amz-Signature=...   (a non-expired presigned object GET)

Everything else is refused: any other method, any other bucket (incl. the evidence bucket),
bucket listings, bucket/object sub-resource operations, the console, and unsigned requests. The
proxy forwards the exact path + query and preserves the incoming Host so MinIO can validate the
presigned signature (which was signed against the public tunnel host). It never holds or checks
the signing secret — MinIO does the cryptographic validation; this is an allowlist gate.

Refuses to run unless APP_ENV=dev and MinIO is NOT on default (minioadmin) credentials — default
creds are a universally known signing key, which would make presigned URLs forgeable by anyone
who finds the tunnel. Auto-stops after a short window so a tunnel is never left public.
"""

from __future__ import annotations

import datetime as dt
import http.client
import os
import subprocess
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from api.app.config import Settings, get_settings

PROXY_PORT = int(os.environ.get("VG_LENS_PROXY_PORT", "9009"))
TUNNEL_TTL_SECONDS = int(os.environ.get("VG_LENS_TUNNEL_TTL_SECONDS", str(15 * 60)))
_DEFAULT_CRED = "minioadmin"

# Bucket/object sub-resource operations that must never be reachable through the tunnel (listings,
# ACLs, tagging, multipart, policy, lifecycle, lock/retention, …). A plain object GET has none.
_DISALLOWED_QUERY_OPS = frozenset({
    "list-type", "location", "uploads", "uploadid", "acl", "tagging", "versions", "versioning",
    "delete", "policy", "logging", "website", "cors", "lifecycle", "replication", "encryption",
    "object-lock", "legal-hold", "retention", "notification", "accelerate", "requestpayment",
    "metrics", "analytics", "inventory", "restore", "torrent", "select",
})
# Hop-by-hop headers not copied when relaying MinIO's response back.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
})


@dataclass(frozen=True)
class Decision:
    allowed: bool
    status: int
    reason: str


def authorize(
    method: str, path: str, query: str, *, bucket: str, now: dt.datetime | None = None
) -> Decision:
    """Allow ONLY a non-expired presigned GET of an object in `bucket`. Pure + unit-tested."""
    now = now or dt.datetime.now(dt.UTC)
    if method.upper() not in ("GET", "HEAD"):
        return Decision(False, 405, f"method {method} not allowed (GET only)")

    # Path-style addressing: /<bucket>/<key>. Need a non-empty key — anything else is a listing,
    # the console, the root, or a different bucket.
    segments = path.split("/", 2)
    if len(segments) < 3 or not segments[2]:
        return Decision(False, 403, "not an object request (listing/console/root refused)")
    if segments[1] != bucket:
        return Decision(False, 403, f"bucket {segments[1]!r} not allowed (assets bucket only)")

    params = {k.lower() for k in parse_qs(query, keep_blank_values=True)}
    bad = params & _DISALLOWED_QUERY_OPS
    if bad:
        return Decision(False, 403, f"operation not allowed: {sorted(bad)}")
    if "x-amz-signature" not in params:
        return Decision(False, 403, "unsigned request (no presigned signature)")

    parsed = parse_qs(query, keep_blank_values=True)
    try:
        amz_date = parsed["X-Amz-Date"][0]
        expires = int(parsed["X-Amz-Expires"][0])
        signed_at = dt.datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
    except (KeyError, IndexError, ValueError):
        return Decision(False, 403, "missing or malformed presign expiry")
    if now > signed_at + dt.timedelta(seconds=expires):
        return Decision(False, 403, "presigned URL expired")
    return Decision(True, 200, "ok")


def assert_safe_to_run(settings: Settings) -> None:
    """Refuse outside dev, or when MinIO is on default credentials (forgeable presigns)."""
    if settings.app_env != "dev":
        raise RuntimeError(
            f"lens-tunnel is dev-only; APP_ENV={settings.app_env!r}. Refusing to start."
        )
    if (
        settings.storage_access_key_id == _DEFAULT_CRED
        or settings.storage_secret_access_key == _DEFAULT_CRED
    ):
        raise RuntimeError(
            "MinIO is on default credentials (minioadmin) — a universally known signing key makes "
            "presigned URLs forgeable by anyone who finds the tunnel. Set non-default creds first: "
            "MINIO_ROOT_USER/MINIO_ROOT_PASSWORD (restart MinIO: `docker compose up -d minio "
            "minio-setup`) AND the matching STORAGE_ACCESS_KEY_ID/STORAGE_SECRET_ACCESS_KEY in "
            ".env (restart the worker). Refusing to start."
        )


def _make_handler(bucket: str, minio_endpoint: str) -> type[BaseHTTPRequestHandler]:
    target = urlsplit(minio_endpoint)
    minio_host = target.hostname or "127.0.0.1"
    minio_port = target.port or (443 if target.scheme == "https" else 80)

    class _Handler(BaseHTTPRequestHandler):
        server_version = "vg-lens-proxy/1.0"

        def _handle(self) -> None:
            split = urlsplit(self.path)
            decision = authorize(self.command, split.path, split.query, bucket=bucket)
            if not decision.allowed:
                body = decision.reason.encode()
                self.send_response(decision.status)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                return
            # Forward the EXACT path+query (no re-encoding — the signature covers it) and preserve
            # the incoming Host so MinIO validates the presign against the signed host.
            conn = http.client.HTTPConnection(minio_host, minio_port, timeout=20)
            try:
                conn.request(
                    self.command, self.path, headers={"Host": self.headers.get("Host", "")}
                )
                upstream = conn.getresponse()
                payload = upstream.read()
                self.send_response(upstream.status)
                for name, value in upstream.getheaders():
                    if name.lower() not in _HOP_BY_HOP:
                        self.send_header(name, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            except OSError as exc:
                body = f"upstream error: {type(exc).__name__}".encode()
                self.send_response(502)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            finally:
                conn.close()

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._handle()

        def do_HEAD(self) -> None:  # noqa: N802
            self._handle()

        def _reject_other(self) -> None:
            body = b"method not allowed (GET only)"
            self.send_response(405)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_POST = do_PUT = do_DELETE = do_PATCH = _reject_other  # noqa: N815

        def log_message(self, fmt: str, *args: object) -> None:  # quieter default logging
            return

    return _Handler


def main() -> int:  # pragma: no cover - dev entrypoint (process orchestration)
    settings = get_settings()
    assert_safe_to_run(settings)

    import shutil

    cloudflared = shutil.which("cloudflared")
    if cloudflared is None:
        print("cloudflared not found — install it first (e.g. `brew install cloudflared`).")
        return 1

    handler = _make_handler(settings.storage_bucket, settings.storage_endpoint_url)
    server = ThreadingHTTPServer(("127.0.0.1", PROXY_PORT), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    minutes = TUNNEL_TTL_SECONDS // 60
    print("=" * 78)
    print("⚠️  THE TUNNEL IS PUBLIC WHILE RUNNING. Anyone with the URL can fetch presigned")
    print(f"    objects from the '{settings.storage_bucket}' bucket until it auto-stops.")
    print(f"    Auto-stops after {minutes} min. Press Ctrl-C to stop sooner.")
    print("=" * 78)
    print(f"Guarded proxy on http://127.0.0.1:{PROXY_PORT} → {settings.storage_endpoint_url}")
    print("Copy the printed https://<name>.trycloudflare.com URL into .env as")
    print("  DISCOVERY_ASSET_PUBLIC_BASE_URL=https://<name>.trycloudflare.com")
    print("then restart the worker.\n")

    cmd = [cloudflared, "tunnel", "--url", f"http://localhost:{PROXY_PORT}"]
    proc = subprocess.Popen(cmd)  # noqa: S603 - fixed dev command, resolved path, local only
    try:
        proc.wait(timeout=TUNNEL_TTL_SECONDS)
    except subprocess.TimeoutExpired:
        print(f"\nAuto-stopping the tunnel after {minutes} min.")
    except KeyboardInterrupt:
        print("\nStopping the tunnel.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
