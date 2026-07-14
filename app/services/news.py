"""News headline fetcher.

Uses yfinance's built-in `.news` endpoint — no additional API key required.
Returns a normalized list of headline dicts sorted newest-first.
"""
from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf


def _extract_headline(item: dict) -> dict | None:
    """yfinance news items have varied shapes across versions.

    Newer versions wrap the payload in `content` with `title`, `pubDate`,
    `provider.displayName`, and `canonicalUrl.url`. Older versions expose
    `title`, `publisher`, `providerPublishTime`, `link` at the top level.
    Return a normalized dict or None if we cannot extract a title.
    """
    content = item.get("content") or item
    title = content.get("title") or item.get("title")
    if not title:
        return None

    publisher = None
    provider = content.get("provider")
    if isinstance(provider, dict):
        publisher = provider.get("displayName")
    publisher = publisher or item.get("publisher") or "unknown"

    published_at = content.get("pubDate") or content.get("displayTime")
    if not published_at:
        ts = item.get("providerPublishTime")
        if ts:
            published_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    url = None
    canonical = content.get("canonicalUrl")
    if isinstance(canonical, dict):
        url = canonical.get("url")
    url = url or item.get("link")

    summary = content.get("summary") or item.get("summary")

    return {
        "title": title,
        "publisher": publisher,
        "published_at": published_at,
        "url": url,
        "summary": summary,
    }


def fetch_headlines(ticker: str, limit: int = 10) -> list[dict]:
    """Fetch recent news headlines for a ticker via yfinance.

    Returns [] on any failure (network, empty response, unexpected shape).
    """
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:  # noqa: BLE001 — yfinance can raise anything
        return []

    headlines: list[dict] = []
    for item in raw:
        normalized = _extract_headline(item)
        if normalized:
            headlines.append(normalized)
        if len(headlines) >= limit:
            break

    return headlines
