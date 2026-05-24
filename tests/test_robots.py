"""Unit tests for app.robots — uses monkey-patched fetch to avoid network."""
from __future__ import annotations

import asyncio

import pytest

from app import robots


@pytest.fixture(autouse=True)
def _clear_cache():
    robots.clear_cache()
    yield
    robots.clear_cache()


def _patch_robots_body(monkeypatch, body: str | None) -> None:
    async def fake(_url: str, timeout_s: float = 5.0) -> str | None:
        return body
    monkeypatch.setattr(robots, "_fetch_robots", fake)


def test_allow_when_no_robots_txt(monkeypatch):
    _patch_robots_body(monkeypatch, None)
    assert asyncio.run(robots.is_allowed("https://x.test/a", "TestBot")) is True


def test_disallow_path_for_all_agents(monkeypatch):
    _patch_robots_body(monkeypatch, "User-agent: *\nDisallow: /private/\n")
    assert asyncio.run(robots.is_allowed("https://x.test/private/secret", "TestBot")) is False
    assert asyncio.run(robots.is_allowed("https://x.test/public/page", "TestBot")) is True


def test_allow_when_robots_txt_unparseable(monkeypatch):
    # Conservative default: garbage robots.txt → allow
    _patch_robots_body(monkeypatch, "this is not robots.txt\x00\xff")
    assert asyncio.run(robots.is_allowed("https://x.test/a", "TestBot")) is True
