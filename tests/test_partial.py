"""Unit tests for the anti-bot stub detection in main._detect_partial."""
from __future__ import annotations

from app.extractor import extract
from app.main import _detect_partial

from .fixtures import (
    ANTI_BOT_STUB_HTML,
    ARTICLE_HTML_WITH_GRAPH,
    PRODUCT_HTML,
)


def test_amazon_style_stub_is_flagged_partial():
    meta = extract(
        "https://www.amazon.com/foo",
        "https://www.amazon.com/foo",
        ANTI_BOT_STUB_HTML,
    )
    reason = _detect_partial(meta)
    assert reason is not None
    assert "thin_content" in reason


def test_real_article_is_not_flagged():
    meta = extract(
        "https://news.example/ai",
        "https://news.example/ai",
        ARTICLE_HTML_WITH_GRAPH,
    )
    assert _detect_partial(meta) is None


def test_real_product_page_is_not_flagged():
    meta = extract(
        "https://example.shop/toaster",
        "https://example.shop/toaster",
        PRODUCT_HTML,
    )
    assert _detect_partial(meta) is None
