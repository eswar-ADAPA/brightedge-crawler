"""Unit tests for app.classifier."""
from __future__ import annotations

from app.classifier import classify
from app.extractor import extract

from .fixtures import (
    ARTICLE_HTML_WITH_GRAPH,
    PLAIN_HTML_NO_STRUCTURED,
    PRODUCT_HTML,
)


def _classify(html: str, url: str = "https://example.com/x"):
    return classify(extract(url, url, html))


def test_product_page_classified_via_schema_org():
    cls = _classify(PRODUCT_HTML, "https://example.shop/toaster")
    assert cls.page_category == "product"
    assert cls.signals["category_source"] == "schema_org"
    assert "Kitchen Appliance" in cls.structured_topics
    assert "CrumbCo" in cls.structured_topics


def test_article_with_graph_uses_article_section_as_topics():
    cls = _classify(ARTICLE_HTML_WITH_GRAPH, "https://news.example/ai")
    assert cls.page_category == "article"
    # articleSection values become structured topics
    topics_lower = [t.lower() for t in cls.structured_topics]
    assert "tech" in topics_lower
    assert "business" in topics_lower


def test_url_pattern_fallback_when_no_structured_signal():
    cls = _classify(PLAIN_HTML_NO_STRUCTURED, "https://shop.example/dp/B123")
    assert cls.page_category == "product"
    assert cls.signals["category_source"] == "url_pattern"


def test_confidence_high_when_schema_org_plus_structured_topics():
    cls = _classify(PRODUCT_HTML, "https://example.shop/toaster")
    assert cls.confidence == "high"


def test_confidence_low_when_only_url_pattern():
    cls = _classify(PLAIN_HTML_NO_STRUCTURED, "https://shop.example/dp/B123")
    # No JSON-LD, only URL-pattern category, no structured topics
    assert cls.confidence == "low"


def test_other_when_no_signal_at_all():
    cls = _classify(PLAIN_HTML_NO_STRUCTURED, "https://random.example/foo")
    assert cls.page_category == "other"
    assert cls.signals["category_source"] == "none"
