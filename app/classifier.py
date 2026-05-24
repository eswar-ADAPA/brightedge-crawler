"""Topic classification.

Two complementary signals:

1. **Structured signals**: JSON-LD @type, OpenGraph type, breadcrumb categories,
   product attributes, news article section. These are high-precision when present.
2. **Keyword extraction** from title + body using YAKE (unsupervised, language-aware).

The output is a ranked list of topic strings + a coarse `page_category` label.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yake

from .extractor import PageMetadata, flatten_json_ld


# Coarse buckets — small + opinionated. The classifier maps schema.org @type
# and OG type into these.
CATEGORY_MAP = {
    "product": {"Product", "ProductGroup", "IndividualProduct", "product"},
    "article": {
        "Article",
        "NewsArticle",
        "BlogPosting",
        "TechArticle",
        "Report",
        "article",
    },
    "video": {"VideoObject", "video.movie", "video.episode", "video.other"},
    "recipe": {"Recipe"},
    "event": {"Event"},
    "organization": {"Organization", "Corporation", "LocalBusiness"},
    "person": {"Person", "profile"},
    "website": {"WebSite", "website"},
}


@dataclass
class Classification:
    page_category: str
    topics: list[str] = field(default_factory=list)
    structured_topics: list[str] = field(default_factory=list)
    keywords: list[tuple[str, float]] = field(default_factory=list)
    confidence: str = "low"
    signals: dict[str, Any] = field(default_factory=dict)


def _categorize(meta: PageMetadata) -> tuple[str, str]:
    """Return (category, source). source ∈ {schema_org, url_pattern, none}."""
    types: set[str] = set()
    for ld in flatten_json_ld(meta.json_ld):
        t = ld.get("@type")
        if isinstance(t, str):
            types.add(t)
        elif isinstance(t, list):
            types.update(x for x in t if isinstance(x, str))
    if meta.page_type:
        types.add(meta.page_type)

    for category, members in CATEGORY_MAP.items():
        if types & members:
            return category, "schema_org"

    url = meta.final_url.lower()
    if any(seg in url for seg in ("/dp/", "/product/", "/p/", "/buy/")):
        return "product", "url_pattern"
    if any(seg in url for seg in ("/blog/", "/article/", "/news/", "/story/", "/202")):
        return "article", "url_pattern"
    return "other", "none"


def _structured_topics(meta: PageMetadata) -> list[str]:
    topics: list[str] = []
    seen: set[str] = set()

    def add(val: str | None) -> None:
        if not val:
            return
        v = val.strip()
        if not v or len(v) > 80:
            return
        key = v.lower()
        if key in seen:
            return
        seen.add(key)
        topics.append(v)

    for ld in flatten_json_ld(meta.json_ld):
        if not isinstance(ld, dict):
            continue
        # Product attributes
        if ld.get("@type") in {"Product", "ProductGroup"}:
            add(ld.get("category"))
            brand = ld.get("brand")
            if isinstance(brand, dict):
                add(brand.get("name"))
            elif isinstance(brand, str):
                add(brand)
            add(ld.get("name"))
        # Article section / keywords
        if "articleSection" in ld:
            sec = ld["articleSection"]
            if isinstance(sec, list):
                for s in sec:
                    add(str(s))
            else:
                add(str(sec))
        if "keywords" in ld:
            kw = ld["keywords"]
            if isinstance(kw, str):
                for piece in re.split(r"[,;|]", kw):
                    add(piece.strip())
            elif isinstance(kw, list):
                for piece in kw:
                    add(str(piece))
        # Breadcrumbs
        if ld.get("@type") == "BreadcrumbList":
            for item in ld.get("itemListElement", []) or []:
                if isinstance(item, dict):
                    name = item.get("name")
                    if not name:
                        sub = item.get("item")
                        if isinstance(sub, dict):
                            name = sub.get("name")
                    add(name)
    # OG article tags
    for k, v in meta.open_graph.items():
        if k.startswith("article:tag") or k == "article:section":
            add(v)
    # <meta name="keywords">
    return topics


def _keyword_topics(meta: PageMetadata, max_kw: int = 12) -> list[tuple[str, float]]:
    # YAKE: lower score = more relevant. We invert for human-friendly ordering.
    text_parts = [meta.title or "", meta.description or "", meta.body_text or ""]
    text = " ".join(p for p in text_parts if p).strip()
    if not text or len(text.split()) < 8:
        return []
    lang = "en"
    if meta.language:
        lang = meta.language.split("-")[0].lower() or "en"
    extractor = yake.KeywordExtractor(
        lan=lang,
        n=3,
        dedupLim=0.7,
        top=max_kw,
        features=None,
    )
    try:
        results = extractor.extract_keywords(text)
    except Exception:
        return []
    # yake returns (keyword, score) — sort ascending by score (most relevant first)
    results.sort(key=lambda kv: kv[1])
    # invert score into a confidence-like number in [0,1]
    out: list[tuple[str, float]] = []
    for kw, score in results:
        kw = kw.strip()
        if not kw or len(kw) < 3:
            continue
        confidence = 1.0 / (1.0 + score)
        out.append((kw, round(confidence, 3)))
    return out


def _confidence(category_source: str, has_structured: bool, has_keywords: bool) -> str:
    """Map signal availability to a coarse confidence label.

    high  — schema.org told us the category AND we got structured topics
    medium — schema.org told us the category OR we got both kinds of topics
    low   — only URL pattern / keyword fallback
    """
    if category_source == "schema_org" and has_structured:
        return "high"
    if category_source == "schema_org" or (has_structured and has_keywords):
        return "medium"
    return "low"


def classify(meta: PageMetadata) -> Classification:
    category, category_source = _categorize(meta)
    structured = _structured_topics(meta)
    keywords = _keyword_topics(meta)

    # Structured topics first (high precision), then keyphrase topics
    seen: set[str] = set()
    merged: list[str] = []
    for t in structured:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            merged.append(t)
    for kw, _score in keywords:
        key = kw.lower()
        if key not in seen:
            seen.add(key)
            merged.append(kw)

    return Classification(
        page_category=category,
        topics=merged[:20],
        structured_topics=structured,
        keywords=keywords,
        confidence=_confidence(category_source, bool(structured), bool(keywords)),
        signals={
            "category_source": category_source,
            "has_json_ld": bool(meta.json_ld),
            "has_open_graph": bool(meta.open_graph),
            "word_count": meta.word_count,
            "language": meta.language,
        },
    )
