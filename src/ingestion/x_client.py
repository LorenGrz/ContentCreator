"""X / Twitter ingestion through a Nitter RSS bridge — no API key, no cost.

A short list of accounts (``X_HANDLES``) is read as RSS from whichever Nitter
instance in ``X_NITTER_BASES`` answers first. Each original tweet inside the
lookback window becomes a ``Signal`` with ``source="x"`` / ``type="tweet"``
carrying the *canonical* ``twitter.com`` status URL. Retweets by the followed
account are skipped — we want their own posts to quote, not their reshares.

Nitter is best-effort: instances go down often, so this source is opt-in
(``X_ENABLED``) and a total failure is raised for the daily job to record as a
degraded run, never swallowed silently.
"""

from __future__ import annotations

import html
import logging
import re
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

import config
from storage.models import Signal
from timeutils import local_date_of, utc_cutoff

log = logging.getLogger(__name__)

_TIMEOUT = 10
_DC_CREATOR = "{http://purl.org/dc/elements/1.1/}creator"
_STATUS_RE = re.compile(r"/([A-Za-z0-9_]+)/status/(\d+)")
_TWEET_MAX_CHARS = 280


def fetch_x_signals(
    *,
    handles: list[str] | None = None,
    nitter_bases: list[str] | None = None,
    limit: int | None = None,
    lookback_hours: int | None = None,
    session: requests.Session | None = None,
) -> list[Signal]:
    handles = handles if handles is not None else config.X_HANDLES
    nitter_bases = nitter_bases if nitter_bases is not None else config.X_NITTER_BASES
    limit = limit if limit is not None else config.X_LIMIT
    if lookback_hours is None:
        lookback_hours = config.X_INGEST_LOOKBACK_HOURS

    if not handles:
        log.info("x: no handles configured; skipping")
        return []
    if not nitter_bases:
        raise RuntimeError("x ingestion enabled but X_NITTER_BASES is empty")

    http = session or requests.Session()
    cutoff = utc_cutoff(lookback_hours)
    base = _pick_working_base(http, nitter_bases, handles[0])

    signals: list[Signal] = []
    seen: set[str] = set()
    for handle in handles:
        handle = handle.lstrip("@")
        try:
            body = _get(http, f"{base}/{handle}/rss")
        except requests.RequestException as exc:  # one bad handle must not sink the rest
            log.warning("x: %s feed failed: %s", handle, exc)
            continue

        per_handle = 0
        for item in _parse_items(body):
            if per_handle >= limit:
                break
            if item["is_retweet"]:
                continue
            if item["published"] is None or item["published"] < cutoff:
                continue
            canonical = _canonical_url(item["link"])
            if not canonical:
                continue
            key = f"x#{canonical}"
            if key in seen:
                continue
            seen.add(key)
            occurred = item["published"].isoformat()
            signals.append(
                Signal(
                    source="x",
                    external_id=canonical.rsplit("/", 1)[-1],
                    type="tweet",
                    title=item["text"][:_TWEET_MAX_CHARS],
                    summary="",
                    url=canonical,
                    occurred_at=occurred,
                    activity_date=local_date_of(occurred),
                    raw={"handle": handle, "author": item["author"] or f"@{handle}"},
                )
            )
            per_handle += 1

    log.info("x: %d tweets from %d handle(s) via %s", len(signals), len(handles), base)
    return signals


def _get(http: requests.Session, url: str) -> str:
    resp = http.get(url, timeout=_TIMEOUT, headers={"User-Agent": "content-creator/1.0"})
    resp.raise_for_status()
    return resp.text


def _pick_working_base(http: requests.Session, bases: list[str], probe_handle: str) -> str:
    """Return the first Nitter base whose feed for ``probe_handle`` responds.
    Raises ``RuntimeError`` if none do."""
    errors: list[str] = []
    for base in bases:
        base = base.rstrip("/")
        try:
            _get(http, f"{base}/{probe_handle.lstrip('@')}/rss")
            return base
        except requests.RequestException as exc:
            errors.append(f"{base}: {type(exc).__name__}")
    raise RuntimeError(f"no working Nitter instance ({'; '.join(errors)})")


def _parse_items(body: str) -> list[dict]:
    root = ElementTree.fromstring(body)
    out: list[dict] = []
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        creator = item.findtext(_DC_CREATOR)
        pub_raw = item.findtext("pubDate")
        published = None
        if pub_raw:
            try:
                published = parsedate_to_datetime(pub_raw)
            except (TypeError, ValueError):
                published = None
        out.append(
            {
                "text": title,
                "link": link,
                "author": (creator or "").strip(),
                "published": published,
                "is_retweet": title.startswith("RT by "),
            }
        )
    return out


def _canonical_url(nitter_link: str) -> str:
    """``https://nitter.net/foo/status/123#m`` -> ``https://twitter.com/foo/status/123``."""
    match = _STATUS_RE.search(nitter_link)
    if not match:
        return ""
    user, status_id = match.group(1), match.group(2)
    return f"https://twitter.com/{user}/status/{status_id}"
