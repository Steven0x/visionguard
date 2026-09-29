"""Security headers + a request body size limit enforced on bytes actually received."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add hardening headers to every response. HSTS only when ``hsts`` (i.e. HTTPS in prod)."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if self._hsts:
            headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class RequestSizeLimitMiddleware:
    """Reject request bodies larger than ``max_bytes`` with 413.

    Enforced on bytes ACTUALLY received (streamed chunks are counted), so a request with a lying
    or absent ``Content-Length`` — e.g. chunked transfer — can't slip a huge body past. A declared
    ``Content-Length`` over the limit is rejected up front as a cheap fast path.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > self.max_bytes:
                    await self._send_413(send)
                    return
            except ValueError:
                pass

        state = {"received": 0, "rejected": False, "response_started": False}

        async def limited_receive() -> Message:
            if state["rejected"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > self.max_bytes:
                    # Signal the downstream app that the client is gone; we answer with 413 below.
                    state["rejected"] = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                state["response_started"] = True
            # Once we've decided to reject, drop the app's output; we own the 413 response.
            if state["rejected"]:
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:  # noqa: BLE001 - a body-read abort surfaces as an app error; make it a 413
            if not state["rejected"]:
                raise
        # Only send our 413 if the app hadn't already begun a response (a streaming handler that
        # started writing before reading the oversized body). Avoids a double response.start.
        if state["rejected"] and not state["response_started"]:
            await self._send_413(send)

    async def _send_413(self, send: Send) -> None:
        body = b'{"detail":"request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
