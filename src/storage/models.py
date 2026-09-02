"""Domain records persisted in the single DynamoDB table.

Table shape: generic ``pk`` / ``sk`` string keys.

    Signal  pk = DATE#<yyyy-mm-dd>   sk = SIGNAL#<source>#<external_id>
    Draft   pk = DATE#<yyyy-mm-dd>   sk = DRAFT#<platform>#<uuid>

Both partitioned by the *activity/target date* (local tz), never the ingest
time, so a day's worth of signals and drafts sit in one partition.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

SIGNAL_SOURCES = ("github", "calendar", "hackernews", "x")
SIGNAL_TYPES = ("commit", "pr", "new_repo", "event", "story", "tweet")

PLATFORMS = ("twitter", "linkedin")
DRAFT_STATUSES = ("pending", "approved", "discarded")
# "original" = a post written from scratch. "quote_tweet" = Lorenzo's comment
# on someone else's tweet; ``Draft.quote_url`` then holds that tweet's URL.
DRAFT_KINDS = ("original", "quote_tweet")

_RAW_MAX_CHARS = 4000


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def date_pk(date: str) -> str:
    """``2026-08-30`` -> ``DATE#2026-08-30``."""
    return f"DATE#{date}"


@dataclass
class Signal:
    source: str
    external_id: str
    type: str
    title: str
    activity_date: str  # yyyy-mm-dd, local tz -> partition key
    summary: str = ""
    url: str = ""
    occurred_at: str = ""  # ISO8601 of the underlying event
    raw: dict = field(default_factory=dict)
    ingested_at: str = field(default_factory=_now_iso)

    @property
    def pk(self) -> str:
        return date_pk(self.activity_date)

    @property
    def sk(self) -> str:
        return f"SIGNAL#{self.source}#{self.external_id}"

    def to_item(self) -> dict:
        item = {"pk": self.pk, "sk": self.sk, **asdict(self)}
        # DynamoDB rejects overly large / non-serialisable blobs; keep raw small.
        item["raw"] = _truncate_raw(self.raw)
        return item

    @classmethod
    def from_item(cls, item: dict) -> Signal:
        return cls(
            source=item["source"],
            external_id=item["external_id"],
            type=item["type"],
            title=item["title"],
            activity_date=item["activity_date"],
            summary=item.get("summary", ""),
            url=item.get("url", ""),
            occurred_at=item.get("occurred_at", ""),
            raw=item.get("raw", {}),
            ingested_at=item.get("ingested_at", ""),
        )


@dataclass
class Draft:
    platform: str
    content: str
    target_date: str  # yyyy-mm-dd -> partition key
    status: str = "pending"
    kind: str = "original"
    quote_url: str = ""  # the tweet being quoted, when kind == "quote_tweet"
    topic_tags: list[str] = field(default_factory=list)
    source_signal_keys: list[str] = field(default_factory=list)
    telegram_chat_id: str = ""
    telegram_message_id: int | None = None
    draft_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=_now_iso)
    decided_at: str | None = None
    edited_at: str | None = None

    @property
    def pk(self) -> str:
        return date_pk(self.target_date)

    @property
    def sk(self) -> str:
        return f"DRAFT#{self.platform}#{self.draft_id}"

    def to_item(self) -> dict:
        item = {"pk": self.pk, "sk": self.sk, **asdict(self)}
        # boto3's resource layer cannot serialise None — drop empty optionals.
        return {k: v for k, v in item.items() if v is not None}

    @classmethod
    def from_item(cls, item: dict) -> Draft:
        msg_id = item.get("telegram_message_id")
        return cls(
            platform=item["platform"],
            content=item["content"],
            target_date=item["target_date"],
            status=item.get("status", "pending"),
            kind=item.get("kind", "original"),
            quote_url=item.get("quote_url", ""),
            topic_tags=list(item.get("topic_tags", [])),
            source_signal_keys=list(item.get("source_signal_keys", [])),
            telegram_chat_id=item.get("telegram_chat_id", ""),
            telegram_message_id=int(msg_id) if msg_id is not None else None,
            draft_id=item["draft_id"],
            created_at=item.get("created_at", ""),
            decided_at=item.get("decided_at"),
            edited_at=item.get("edited_at"),
        )


def _truncate_raw(raw: dict) -> dict:
    import json

    encoded = json.dumps(raw, ensure_ascii=False, default=str)
    if len(encoded) <= _RAW_MAX_CHARS:
        return json.loads(encoded)
    return {"_truncated": True, "preview": encoded[:_RAW_MAX_CHARS]}
