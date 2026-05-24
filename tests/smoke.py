"""Smoke test the pipeline against the assignment's three sample URLs.

Usage:
    python -m tests.smoke
"""
from __future__ import annotations

import asyncio
import json
import sys

from app.classifier import classify
from app.extractor import extract
from app.fetcher import FetchError, fetch

URLS = [
    "http://www.amazon.com/Cuisinart-CPT-122-Compact-2-SliceToaster/dp/B009GQ034C/ref=sr_1_1?s=kitchen&ie=UTF8&qid=1431620315&sr=1-1&keywords=toaster",
    "http://blog.rei.com/camp/how-to-introduce-your-indoorsy-friend-to-the-outdoors/",
    "https://www.cnn.com/2025/09/23/tech/google-study-90-percent-tech-jobs-ai",
]


async def one(url: str) -> dict:
    try:
        fr = await fetch(url)
    except FetchError as e:
        return {"url": url, "error": str(e)}
    meta = extract(url, fr.final_url, fr.html)
    cls = classify(meta)
    return {
        "url": url,
        "final_url": fr.final_url,
        "status": fr.status,
        "domain": meta.domain,
        "title": meta.title,
        "description": (meta.description or "")[:160],
        "page_category": cls.page_category,
        "confidence": cls.confidence,
        "topics": cls.topics[:12],
        "structured_topics": cls.structured_topics[:8],
        "top_keywords": [kw for kw, _ in cls.keywords[:8]],
        "word_count": meta.word_count,
        "json_ld_types": [
            ld.get("@type") for ld in meta.json_ld if isinstance(ld, dict)
        ],
    }


async def main() -> int:
    results = []
    for url in URLS:
        print(f"\n=== {url}", file=sys.stderr)
        r = await one(url)
        results.append(r)
        print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
