"""HTML metadata + body extraction."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

try:
    import trafilatura
except Exception:  # pragma: no cover
    trafilatura = None


@dataclass
class PageMetadata:
    url: str
    final_url: str
    domain: str
    title: str | None = None
    description: str | None = None
    canonical: str | None = None
    language: str | None = None
    author: str | None = None
    published: str | None = None
    site_name: str | None = None
    page_type: str | None = None
    image: str | None = None
    open_graph: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    json_ld: list[dict[str, Any]] = field(default_factory=list)
    h1: list[str] = field(default_factory=list)
    h2: list[str] = field(default_factory=list)
    body_text: str = ""
    word_count: int = 0


def _first(*vals: str | None) -> str | None:
    for v in vals:
        if v and v.strip():
            return v.strip()
    return None


def _meta(soup: BeautifulSoup, attrs: dict[str, str]) -> str | None:
    """Return the `content` of the first <meta> tag matching `attrs`."""
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def flatten_json_ld(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Walk @graph entries so callers can treat JSON-LD as a flat list.

    Many sites (CNN, NYT) wrap their JSON-LD in `{"@graph": [...]}` rather
    than emitting top-level objects. Without flattening, downstream lookups
    for @type / author / keywords miss those entries.
    """
    out: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        graph = block.get("@graph")
        if isinstance(graph, list):
            for g in graph:
                if isinstance(g, dict):
                    out.append(g)
        else:
            out.append(block)
    return out


def _collect_json_ld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Some sites embed multiple JSON objects or trailing commas; skip
            continue
        if isinstance(parsed, list):
            out.extend(x for x in parsed if isinstance(x, dict))
        elif isinstance(parsed, dict):
            out.append(parsed)
    return out


def _extract_author(json_ld: list[dict[str, Any]]) -> str | None:
    """Pull an author name out of (flattened) JSON-LD."""
    for ld in flatten_json_ld(json_ld):
        author = ld.get("author")
        if isinstance(author, str) and author.strip():
            return author.strip()
        if isinstance(author, dict):
            name = author.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        if isinstance(author, list):
            for entry in author:
                if isinstance(entry, dict):
                    name = entry.get("name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
                elif isinstance(entry, str) and entry.strip():
                    return entry.strip()
    return None


def _extract_published(json_ld: list[dict[str, Any]]) -> str | None:
    for ld in flatten_json_ld(json_ld):
        v = ld.get("datePublished")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_page_type(json_ld: list[dict[str, Any]]) -> str | None:
    for ld in flatten_json_ld(json_ld):
        t = ld.get("@type")
        if isinstance(t, str) and t.strip():
            return t.strip()
        if isinstance(t, list):
            for entry in t:
                if isinstance(entry, str) and entry.strip():
                    return entry.strip()
    return None


def _extract_body(html: str, soup: BeautifulSoup) -> str:
    if trafilatura is not None:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
        if text and text.strip():
            return text.strip()
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract(url: str, final_url: str, html: str) -> PageMetadata:
    soup = BeautifulSoup(html, "lxml")

    og: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        prop = tag.get("property") or ""
        if prop.startswith("og:") and tag.get("content"):
            og[prop[3:]] = tag["content"].strip()

    tw: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name") or ""
        if name.startswith("twitter:") and tag.get("content"):
            tw[name[8:]] = tag["content"].strip()

    title = _first(
        og.get("title"),
        tw.get("title"),
        soup.title.string if soup.title and soup.title.string else None,
    )

    description = _first(
        _meta(soup, {"name": "description"}),
        og.get("description"),
        tw.get("description"),
        _meta(soup, {"property": "description"}),
    )

    canonical = None
    link = soup.find("link", rel=lambda v: v and "canonical" in v)
    if link and link.get("href"):
        canonical = link["href"].strip()

    language = None
    if soup.html and soup.html.get("lang"):
        language = soup.html["lang"].strip()

    json_ld = _collect_json_ld(soup)

    author = _first(
        _meta(soup, {"name": "author"}),
        og.get("article:author"),
        _extract_author(json_ld),
    )

    published = _first(
        _meta(soup, {"property": "article:published_time"}),
        _meta(soup, {"name": "pubdate"}),
        _extract_published(json_ld),
    )

    page_type = _first(og.get("type"), _extract_page_type(json_ld))

    h1s = [h.get_text(strip=True) for h in soup.find_all("h1")][:10]
    h2s = [h.get_text(strip=True) for h in soup.find_all("h2")][:25]

    body = _extract_body(html, soup)

    return PageMetadata(
        url=url,
        final_url=final_url,
        domain=urlparse(final_url).netloc,
        title=title,
        description=description,
        canonical=canonical,
        language=language,
        author=author,
        published=published,
        site_name=_first(og.get("site_name")),
        page_type=page_type,
        image=_first(og.get("image"), tw.get("image")),
        open_graph=og,
        twitter=tw,
        json_ld=json_ld,
        h1=[x for x in h1s if x],
        h2=[x for x in h2s if x],
        body_text=body,
        word_count=len(body.split()) if body else 0,
    )
