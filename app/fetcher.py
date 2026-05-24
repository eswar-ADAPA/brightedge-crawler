"""HTTP fetcher with sane defaults for crawling."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from . import robots

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
}


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    html: str
    content_type: str
    elapsed_ms: int


class FetchError(Exception):
    pass


class RobotsDisallowed(FetchError):
    """Raised when robots.txt forbids fetching the URL."""


async def fetch(
    url: str,
    *,
    timeout_s: float = 15.0,
    max_bytes: int = 5_000_000,
    retries: int = 2,
    respect_robots: bool = True,
) -> FetchResult:
    if respect_robots:
        allowed = await robots.is_allowed(url, DEFAULT_UA)
        if not allowed:
            raise RobotsDisallowed(f"robots.txt disallows fetching {url}")

    last_exc: Exception | None = None
    backoff = 0.5
    # Try HTTP/2 first; fall back to HTTP/1.1 on stream reset (some sites — e.g.
    # blog.rei.com behind Akamai — RST_STREAM HTTP/2 from non-browser clients).
    for attempt in range(retries + 1):
        use_http2 = attempt == 0
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout_s,
                headers=DEFAULT_HEADERS,
                http2=use_http2,
            ) as client:
                started = asyncio.get_event_loop().time()
                resp = await client.get(url)
                elapsed = int((asyncio.get_event_loop().time() - started) * 1000)
                ct = resp.headers.get("content-type", "") or ""
                body = resp.content[:max_bytes]
                # Some sites omit content-type or return application/octet-stream
                # for anti-bot responses; only reject if it is clearly binary
                # AND the payload doesn't sniff as HTML.
                lower_ct = ct.lower()
                looks_html = body[:512].lstrip().lower().startswith(
                    (b"<!doctype", b"<html", b"<?xml", b"<head", b"<body")
                )
                if (
                    lower_ct
                    and "html" not in lower_ct
                    and "xml" not in lower_ct
                    and not looks_html
                ):
                    raise FetchError(f"non-html content-type: {ct!r}")
                try:
                    html = body.decode(resp.encoding or "utf-8", errors="replace")
                except LookupError:
                    html = body.decode("utf-8", errors="replace")
                return FetchResult(
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    html=html,
                    content_type=ct,
                    elapsed_ms=elapsed,
                )
        except (httpx.HTTPError, FetchError) as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(backoff)
                backoff *= 2
            else:
                break
    # Most "blank" failures on real sites are anti-bot middleware (Akamai,
    # Cloudflare, PerimeterX) closing the connection. Surface a clearer hint
    # so callers can route the URL to a headless-browser tier.
    cls = type(last_exc).__name__ if last_exc else "Unknown"
    detail = str(last_exc) or "(no message — likely anti-bot drop or TLS fingerprint block)"
    raise FetchError(f"failed to fetch {url}: {cls}: {detail}") from last_exc
