"""Unit tests for app.extractor."""
from __future__ import annotations

from app.extractor import extract, flatten_json_ld

from .fixtures import (
    ANTI_BOT_STUB_HTML,
    ARTICLE_HTML_WITH_GRAPH,
    PLAIN_HTML_NO_STRUCTURED,
    PRODUCT_HTML,
)


def test_extract_basic_meta_from_plain_html():
    """The _meta() bug previously made meta-only pages return no description."""
    meta = extract("https://example.com/x", "https://example.com/x", PLAIN_HTML_NO_STRUCTURED)
    assert meta.title == "Just A Page"
    assert meta.description == "Nothing fancy here, just words on a page."
    assert meta.json_ld == []


def test_extract_product_page_keeps_all_signals():
    meta = extract(
        "https://example.shop/toaster",
        "https://example.shop/toaster",
        PRODUCT_HTML,
    )
    assert meta.title == "Best Toaster Ever"  # OG title beats <title>
    assert meta.description == "Two-slice toaster with 7 shade settings."
    assert meta.canonical == "https://example.shop/toaster"
    assert meta.language == "en"
    assert meta.site_name == "ExampleShop"
    assert meta.page_type in ("product", "Product")
    assert any(ld.get("@type") == "Product" for ld in meta.json_ld)


def test_extract_walks_json_ld_graph_for_author_and_date():
    """@graph-wrapped JSON-LD must be flattened for author/published lookup."""
    meta = extract(
        "https://news.example/ai",
        "https://news.example/ai",
        ARTICLE_HTML_WITH_GRAPH,
    )
    assert meta.author == "Jane Doe"
    assert meta.published == "2025-09-23T08:00:00Z"
    assert meta.page_type in ("NewsArticle", "article")


def test_flatten_json_ld_unwraps_graph():
    blocks = [{"@graph": [{"@type": "A"}, {"@type": "B"}]}, {"@type": "C"}]
    flat = flatten_json_ld(blocks)
    types = {b.get("@type") for b in flat}
    assert types == {"A", "B", "C"}


def test_extract_handles_anti_bot_stub():
    """Stub pages still parse without raising; word_count is just tiny."""
    meta = extract(
        "https://www.amazon.com/foo",
        "https://www.amazon.com/foo",
        ANTI_BOT_STUB_HTML,
    )
    assert meta.title == "Amazon.com"
    assert meta.word_count < 20
    assert not meta.json_ld
