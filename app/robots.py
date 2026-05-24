"""robots.txt check with a small in-memory TTL cache.

Production would push this into Redis (per the design doc), but in-memory
is fine for the demo service.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from urllib import robotparser
from urllib.parse import urlparse

import httpx

CACHE_TTL_SECONDS = 6 * 3600  # 6 hours, per design doc


@dataclass
class _CacheEntry:
    parser: robotparser.RobotFileParser | None
    fetched_at: float


_cache: dict[str, _CacheEntry] = {}


async def _fetch_robots(robots_url: str, timeout_s: float = 5.0) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            resp = await client.get(robots_url)
            if resp.status_code == 200:
                return resp.text
            # 4xx → treat as "no robots.txt", which the spec says means allow all
            return None
    except httpx.HTTPError:
        return None


async def is_allowed(url: str, user_agent: str) -> bool:
    """Return True if `user_agent` is allowed to fetch `url` per robots.txt.

    Conservative defaults: if robots.txt is unreachable or unparseable, allow
    (matches the de facto behavior of major crawlers).
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return True
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    now = time.monotonic()

    entry = _cache.get(robots_url)
    if entry is None or (now - entry.fetched_at) > CACHE_TTL_SECONDS:
        body = await _fetch_robots(robots_url)
        parser: robotparser.RobotFileParser | None
        if body is None:
            parser = None
        else:
            parser = robotparser.RobotFileParser()
            try:
                parser.parse(body.splitlines())
            except Exception:
                parser = None
        entry = _CacheEntry(parser=parser, fetched_at=now)
        _cache[robots_url] = entry

    if entry.parser is None:
        return True
    return entry.parser.can_fetch(user_agent, url)


def clear_cache() -> None:
    """Test helper."""
    _cache.clear()
