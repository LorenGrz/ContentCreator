"""Technology-news ingestion from the curated Weekly AI News Digest page."""

from __future__ import annotations

import hashlib
import logging
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

from storage.models import Signal
from timeutils import today_local_iso

log = logging.getLogger(__name__)

DEFAULT_URL = "https://elbruno.github.io/weekly-ai-news-digest/"
_TIMEOUT = 10


class _DigestParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stories: list[dict[str, object]] = []
        self._story: dict[str, object] | None = None
        self._field: str | None = None
        self._lang: str | None = None
        self._buffer: list[str] = []
        self._localized: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "article" and "story-card" in classes:
            self._story = {
                "rank": attributes.get("data-rank", ""),
                "published": attributes.get("data-published", ""),
                "source": attributes.get("data-source", ""),
                "tags": [
                    tag.strip()
                    for tag in (attributes.get("data-tags") or "").split(",")
                    if tag.strip()
                ],
            }
        if self._story is None:
            return
        if tag == "a" and self._field == "title":
            self._story["url"] = urljoin(DEFAULT_URL, attributes.get("href") or "")
        if tag == "div" and "title" in classes:
            self._field = "title"
            self._lang = None
            self._buffer = []
            self._localized = {}
        elif tag == "span" and self._field and attributes.get("data-lang"):
            self._lang = attributes["data-lang"]
            self._buffer = []
        elif tag == "p" and "tldr" in classes:
            self._field = "summary"
            self._lang = None
            self._buffer = []
        elif tag == "p" and "why" in classes:
            self._field = "why"
            self._lang = None
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._field and self._lang:
            self._localized[self._lang] = " ".join("".join(self._buffer).split())
            self._lang = None
            self._buffer = []
        elif self._field and ((tag == "div" and self._field == "title") or tag == "p"):
            text = " ".join("".join(self._buffer).split())
            if self._field == "title":
                self._story[self._field] = (
                    self._localized.get("es") or self._localized.get("en") or text
                )
            elif text or self._localized:
                self._story[self._field] = (
                    self._localized.get("es") or self._localized.get("en") or text
                )
            self._field = None
            self._lang = None
            self._buffer = []
            self._localized = {}
        if tag == "article" and self._story is not None:
            if self._story.get("url") and self._story.get("title"):
                self.stories.append(self._story)
            self._story = None

    def handle_data(self, data: str) -> None:
        if self._field:
            self._buffer.append(data)


def fetch_weekly_ai_news_signals(
    *,
    limit: int = 5,
    url: str = DEFAULT_URL,
    session: requests.Session | None = None,
) -> list[Signal]:
    """Fetch curated stories from the digest and map them to content signals."""
    if limit <= 0:
        return []
    http = session or requests.Session()
    response = http.get(url, timeout=_TIMEOUT)
    response.raise_for_status()

    parser = _DigestParser()
    parser.feed(response.text)
    day = today_local_iso()
    signals: list[Signal] = []
    for story in parser.stories[:limit]:
        story_url = str(story["url"])
        external_id = hashlib.sha256(story_url.encode()).hexdigest()[:24]
        why = str(story.get("why", ""))
        signals.append(
            Signal(
                source="weekly_ai_news_digest",
                external_id=external_id,
                type="story",
                title=str(story["title"])[:200],
                summary=f"{story.get('summary', '')} {why}".strip()[:1000],
                url=story_url,
                occurred_at=str(story.get("published", "")),
                activity_date=day,
                raw={
                    "rank": story.get("rank", ""),
                    "source": story.get("source", ""),
                    "tags": story.get("tags", []),
                    "why": why,
                },
            )
        )
    log.info("weekly_ai_news_digest: %d stories", len(signals))
    return signals
