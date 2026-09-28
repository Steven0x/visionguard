"""Slice 6: offender-key normalization heuristic."""

from __future__ import annotations

import pytest

from api.app.services.offender import offender_key


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://instagram.com/someuser", "instagram:@someuser"),
        ("https://www.instagram.com/SomeUser/", "instagram:@someuser"),
        ("https://x.com/@handle/status/123", "twitter:@handle"),
        ("https://twitter.com/handle", "twitter:@handle"),
        ("https://www.tiktok.com/@creator/video/9", "tiktok:@creator"),
        ("https://onlyfans.com/star", "onlyfans:@star"),
        ("https://www.etsy.com/shop/CoolShop/listing/1", "etsy:coolshop"),
        ("https://ebay.com/usr/Seller123", "ebay:seller123"),
        ("https://ebay.com/itm/thing?_ssn=bobstore", "ebay:bobstore"),
        ("https://randomblog.example/post/x", "domain:randomblog.example"),
        ("https://www.randomblog.example/", "domain:randomblog.example"),
        # Reddit/YouTube: the account is NOT the first path segment — key on the real account, and
        # fall back to domain for non-account URLs (so distinct offenders never collapse).
        ("https://reddit.com/user/alice/comments/1", "reddit:@alice"),
        ("https://www.reddit.com/u/bob", "reddit:@bob"),
        ("https://reddit.com/r/pics/comments/9", "domain:reddit.com"),
        ("https://youtube.com/@chan/videos", "youtube:@chan"),
        ("https://www.youtube.com/channel/UC123", "youtube:@uc123"),
        ("https://youtube.com/watch?v=abc", "domain:youtube.com"),
        (None, None),
        ("not a url", None),
    ],
)
def test_offender_key(url: str | None, expected: str | None) -> None:
    assert offender_key(url) == expected
