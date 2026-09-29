"""The log scrubber must strip secrets, PII and sensitive URL detail from every log line,
including uvicorn/gunicorn access logs (CLAUDE.md #6/#7)."""

from __future__ import annotations

import logging

from api.app.obs.logging import SERVER_LOGGERS, ScrubbingFilter, configure_logging, scrub


def test_scrub_redacts_bearer_and_jwt() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhZG1pbiJ9.c2ln"
    out = scrub(f"auth header Bearer {jwt} used")
    assert jwt not in out
    assert "Bearer [REDACTED]" in out
    assert scrub(f"token={jwt}") == "token=[REDACTED_JWT]"


def test_scrub_redacts_email() -> None:
    assert "alice@example.com" not in scrub("user alice@example.com signed in")
    assert "[REDACTED_EMAIL]" in scrub("user alice@example.com signed in")


def test_scrub_redacts_whole_url_including_host() -> None:
    out = scrub("fetched https://victim-name.leak-tube.example/videos/x?token=abc")
    assert out == "fetched [REDACTED_URL]"
    assert "victim-name" not in out and "leak-tube.example" not in out and "token=abc" not in out


def test_scrub_redacts_scheme_less_host_and_path() -> None:
    out = scrub("saw leak-tube.example/videos/victim in results")
    assert out == "saw [REDACTED_URL] in results"
    assert "victim" not in out


def test_filter_rewrites_record_message() -> None:
    rec = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "hit %s for %s", ("https://x.example/a/b", "e@x.com"), None
    )
    assert ScrubbingFilter().filter(rec) is True
    msg = rec.getMessage()
    assert msg == "hit [REDACTED_URL] for [REDACTED_EMAIL]"


def test_access_log_line_with_query_is_scrubbed() -> None:
    configure_logging()
    # configure_logging owns the root handlers, so capture with our own handler on top of it.
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    root = logging.getLogger()
    root.addHandler(_Capture())
    try:
        access = logging.getLogger("uvicorn.access")
        # Mimic uvicorn's access record: the full request line lands in the message.
        access.info('%s - "%s %s HTTP/1.1" %d', "1.2.3.4", "GET", "/cases?email=v@x.com", 200)
    finally:
        root.handlers = [h for h in root.handlers if not isinstance(h, _Capture)]
    joined = " ".join(r.getMessage() for r in captured)
    assert "v@x.com" not in joined
    assert "[REDACTED_EMAIL]" in joined


def test_server_loggers_have_the_filter() -> None:
    configure_logging()
    for name in SERVER_LOGGERS:
        assert any(isinstance(f, ScrubbingFilter) for f in logging.getLogger(name).filters)
