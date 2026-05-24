"""FastAPI service: GET /classify?url=... → metadata + topics."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .classifier import classify
from .extractor import extract
from .fetcher import FetchError, fetch

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("brightedge.crawler")

app = FastAPI(
    title="BrightEdge Demo Crawler",
    version="0.1.0",
    description=(
        "Fetches a URL, extracts metadata (title, description, OG, JSON-LD, body), "
        "and returns a ranked list of topics."
    ),
)


class TopicScore(BaseModel):
    keyword: str
    confidence: float


class ClassifyResponse(BaseModel):
    url: str
    final_url: str
    domain: str
    status: int
    elapsed_ms: int
    page_category: str
    confidence: float
    topics: list[str]
    structured_topics: list[str]
    keywords: list[TopicScore]
    metadata: dict[str, Any] = Field(
        description="Title, description, OG/Twitter, JSON-LD, headings, body excerpt."
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/classify", response_model=ClassifyResponse)
async def classify_url(
    url: str = Query(..., description="HTTP(S) URL to crawl and classify"),
    body_chars: int = Query(
        2000, ge=0, le=20000, description="Max body characters returned in response"
    ),
) -> ClassifyResponse:
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must start with http:// or https://")

    started = time.time()
    try:
        fr = await fetch(url)
    except FetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    meta = extract(url, fr.final_url, fr.html)
    cls = classify(meta)

    payload = ClassifyResponse(
        url=url,
        final_url=fr.final_url,
        domain=meta.domain,
        status=fr.status,
        elapsed_ms=int((time.time() - started) * 1000),
        page_category=cls.page_category,
        confidence=cls.confidence,
        topics=cls.topics,
        structured_topics=cls.structured_topics,
        keywords=[TopicScore(keyword=k, confidence=c) for k, c in cls.keywords],
        metadata={
            "title": meta.title,
            "description": meta.description,
            "canonical": meta.canonical,
            "language": meta.language,
            "author": meta.author,
            "published": meta.published,
            "site_name": meta.site_name,
            "page_type": meta.page_type,
            "image": meta.image,
            "open_graph": meta.open_graph,
            "twitter": meta.twitter,
            "json_ld_types": [
                ld.get("@type") for ld in meta.json_ld if isinstance(ld, dict)
            ],
            "h1": meta.h1,
            "h2": meta.h2,
            "word_count": meta.word_count,
            "body_excerpt": (meta.body_text or "")[:body_chars],
        },
    )
    log.info(
        "classify domain=%s category=%s topics=%d ms=%d",
        meta.domain,
        cls.page_category,
        len(cls.topics),
        payload.elapsed_ms,
    )
    return payload


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception) -> JSONResponse:  # pragma: no cover
    log.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "internal error"})
