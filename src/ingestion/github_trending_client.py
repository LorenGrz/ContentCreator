"""Ingestion of trending and emerging repositories from GitHub."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta

import requests

import config
from storage.models import Signal
from timeutils import today_local_iso

log = logging.getLogger(__name__)

_TIMEOUT = 10
_SEARCH_URL = "https://api.github.com/search/repositories"


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ContentCreatorBot/1.0",
    }
    token = None
    try:
        token = config.get_parameter(config.PARAM_GITHUB_TOKEN)
    except Exception:
        pass
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_github_trending_signals(
    *,
    limit: int | None = None,
    query: str | None = None,
    days_back: int = 20,
    min_stars: int = 30,
    session: requests.Session | None = None,
) -> list[Signal]:
    """Fetch freshly popular repositories matching tech/AI/automation queries."""
    max_items = limit if limit is not None else config.GITHUB_TRENDING_LIMIT
    if max_items <= 0:
        return []

    search_keywords = (query or config.GITHUB_TRENDING_QUERY).strip()
    # If the caller or config already supplied created/stars filters, use raw query
    if "created:" in search_keywords or "stars:" in search_keywords:
        full_query = search_keywords
    else:
        since_date = (datetime.now(UTC) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        full_query = f"created:>{since_date} stars:>{min_stars} {search_keywords}".strip()

    params = {
        "q": full_query,
        "sort": "stars",
        "order": "desc",
        "per_page": str(min(max_items, 10)),
    }

    http = session or requests.Session()
    response = http.get(
        _SEARCH_URL,
        headers=_github_headers(),
        params=params,
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    items = data.get("items", [])

    day = today_local_iso()
    signals: list[Signal] = []

    for item in items[:max_items]:
        repo_name = item.get("full_name") or "unknown/repo"
        html_url = item.get("html_url") or ""
        stars = item.get("stargazers_count", 0)
        desc = (item.get("description") or "").strip()
        topics = item.get("topics") or []
        language = item.get("language") or ""
        created_at = item.get("created_at") or ""

        external_id = hashlib.sha256(html_url.encode()).hexdigest()[:24]
        summary_parts = []
        if desc:
            summary_parts.append(desc)
        if language:
            summary_parts.append(f"Lenguaje: {language}")
        if topics:
            summary_parts.append(f"Tópicos: {', '.join(topics[:6])}")
        summary_text = " | ".join(summary_parts)[:1000]

        signals.append(
            Signal(
                source="github_trending",
                external_id=external_id,
                type="repo",
                title=f"GitHub Trending: {repo_name} (⭐ {stars})",
                summary=summary_text,
                url=html_url,
                occurred_at=created_at,
                activity_date=day,
                raw={
                    "full_name": repo_name,
                    "stars": stars,
                    "forks": item.get("forks_count", 0),
                    "topics": topics,
                    "language": language,
                    "description": desc,
                },
            )
        )

    log.info("github_trending: %d repos ingested", len(signals))
    return signals
