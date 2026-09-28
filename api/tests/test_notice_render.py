"""Safe renderer: whitelisted tokens only, unknown tokens raise, header values sanitized."""

from __future__ import annotations

import pytest

from api.app.services.notice_render import (
    NoticeRenderError,
    missing_elements,
    render,
    sanitize_header_value,
)


def test_render_replaces_known_tokens() -> None:
    out = render("Dear {{platform}}, re {{subject_legal_name}}",
                 {"platform": "Instagram", "subject_legal_name": "Jane Doe"})
    assert out == "Dear Instagram, re Jane Doe"


def test_render_unknown_token_raises() -> None:
    with pytest.raises(NoticeRenderError):
        render("Hello {{os_system}}", {})


def test_render_missing_context_value_raises() -> None:
    # `platform` is whitelisted but absent from the context.
    with pytest.raises(NoticeRenderError):
        render("Hello {{platform}}", {})


def test_sanitize_strips_crlf() -> None:
    assert sanitize_header_value("Takedown\r\nBcc: evil@x") == "TakedownBcc: evil@x"
    assert sanitize_header_value("  spaced  ") == "spaced"


def test_missing_elements_flags_blank_required_fields() -> None:
    ctx = {"agent_name": "Agent", "infringing_urls": "", "work_description": "  "}
    missing = missing_elements(["agent_name", "infringing_urls", "work_description"], ctx)
    assert set(missing) == {"infringing_urls", "work_description"}
    assert missing_elements(None, ctx) == []
