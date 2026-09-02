"""Hacker News ingestion — the no-auth fallback source.

Used only when there's no personal GitHub/Calendar activity for the day, to
seed a "reflexión tech" tweet. Firebase HN API, no key required.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import requests

from storage.models import Signal
from timeutils import today_local_iso

log = logging.getLogger(__name__)

_BASE = "https://hacker-news.firebaseio.com/v0"
_TIMEOUT = 10


def fetch_hackernews_signals(
    *,
    limit: int = 5,
    session: requests.Session | None = None,
) -> list[Signal]:
    http = session or requests.Session()

    resp = http.get(f"{_BASE}/topstories.json", timeout=_TIMEOUT)
    resp.raise_for_status()
    story_ids = resp.json()[: limit * 3]  # over-fetch; some ids are jobs/polls

    day = today_local_iso()
    signals: list[Signal] = []
    for sid in story_ids:
        if len(signals) >= limit:
            break
        item_resp = http.get(f"{_BASE}/item/{sid}.json", timeout=_TIMEOUT)
        item_resp.raise_for_status()
        item = item_resp.json() or {}
        if item.get("type") != "story" or item.get("dead") or item.get("deleted"):
            continue
        ts = item.get("time")
        occurred = datetime.fromtimestamp(ts, tz=UTC).isoformat() if ts else ""
        signals.append(
            Signal(
                source="hackernews",
                external_id=str(sid),
                type="story",
                title=(item.get("title") or "")[:200],
                summary="",
                url=item.get("url") or f"https://news.ycombinator.com/item?id={sid}",
                occurred_at=occurred,
                activity_date=day,
                raw={
                    "score": item.get("score"),
                    "by": item.get("by"),
                    "descendants": item.get("descendants"),
                },
            )
        )

    log.info("hackernews: %d stories", len(signals))
    return signals
