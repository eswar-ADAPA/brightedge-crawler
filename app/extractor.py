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


def _meta(soup: BeautifulSoup, **attrs: str) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


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
            # some sites embed multiple JSON objects or trailing commas; skip
            continue
        if isinstance(parsed, list):
            out.extend(x for x in parsed if isinstance(x, dict))
        elif isinstance(parsed, dict):
            out.append(parsed)
    return out


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
    # Fallback: strip script/style and take visible text
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
        _meta(soup, attrs={"name": "description"}),
        og.get("description"),
        tw.get("description"),
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
        _meta(soup, attrs={"name": "author"}),
        og.get("article:author"),
        next(
            (
                (ld.get("author") or {}).get("name")
                if isinstance(ld.get("author"), dict)
                else (ld.get("author") if isinstance(ld.get("author"), str) else None)
                for ld in json_ld
                if "author" in ld
            ),
            None,
        ),
    )

    published = _first(
        _meta(soup, attrs={"property": "article:published_time"}),
        _meta(soup, attrs={"name": "pubdate"}),
        next((ld.get("datePublished") for ld in json_ld if "datePublished" in ld), None),
    )

    page_type = _first(
        og.get("type"),
        next((ld.get("@type") if isinstance(ld.get("@type"), str) else None for ld in json_ld), None),
    )

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
