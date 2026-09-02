from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest
import responses

from ingestion.x_client import fetch_x_signals

_BASES = ["https://nitter.test", "https://nitter.backup"]
_NOW = datetime.now(UTC)


def _rss(*items: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<channel><title>feed</title>{''.join(items)}</channel></rss>"
    )


def _item(text, *, handle, status_id, hours_ago=1, base=_BASES[0]):
    when = _NOW - timedelta(hours=hours_ago)
    return (
        "<item>"
        f"<title>{text}</title>"
        f"<dc:creator>@{handle}</dc:creator>"
        f"<pubDate>{format_datetime(when, usegmt=True)}</pubDate>"
        f"<link>{base}/{handle}/status/{status_id}#m</link>"
        "</item>"
    )


def _feed(base, handle, body, status=200):
    responses.add(
        responses.GET,
        f"{base}/{handle}/rss",
        body=body,
        status=status,
        content_type="application/xml",
    )


@responses.activate
def test_returns_only_recent_original_tweets():
    body = _rss(
        _item("Lambda SnapStart for Python is GA", handle="aws", status_id="1001"),
        _item("RT by @aws: reshared take", handle="someone", status_id="1002"),
        _item("ancient announcement", handle="aws", status_id="1003", hours_ago=24 * 20),
    )
    _feed(_BASES[0], "aws", body)

    signals = fetch_x_signals(handles=["aws"], nitter_bases=_BASES, limit=5, lookback_hours=36)

    assert len(signals) == 1
    s = signals[0]
    assert s.source == "x" and s.type == "tweet"
    assert s.title == "Lambda SnapStart for Python is GA"
    assert s.url == "https://twitter.com/aws/status/1001"
    assert s.external_id == "1001"
    assert s.raw == {"handle": "aws", "author": "@aws"}


@responses.activate
def test_falls_back_to_next_nitter_instance():
    body = _rss(_item("only on the backup", handle="vercel", status_id="2001", base=_BASES[1]))
    _feed(_BASES[0], "vercel", "", status=502)
    _feed(_BASES[1], "vercel", body)

    signals = fetch_x_signals(handles=["vercel"], nitter_bases=_BASES, limit=5, lookback_hours=36)

    assert [s.url for s in signals] == ["https://twitter.com/vercel/status/2001"]


@responses.activate
def test_raises_when_every_instance_is_down():
    for base in _BASES:
        _feed(base, "aws", "", status=503)

    with pytest.raises(RuntimeError, match="no working Nitter instance"):
        fetch_x_signals(handles=["aws"], nitter_bases=_BASES, limit=5, lookback_hours=36)


@responses.activate
def test_limit_is_per_handle():
    body = _rss(
        _item("first", handle="aws", status_id="3001", hours_ago=1),
        _item("second", handle="aws", status_id="3002", hours_ago=2),
        _item("third", handle="aws", status_id="3003", hours_ago=3),
    )
    _feed(_BASES[0], "aws", body)

    signals = fetch_x_signals(handles=["aws"], nitter_bases=_BASES, limit=2, lookback_hours=36)

    assert [s.title for s in signals] == ["first", "second"]


def test_no_handles_returns_empty_without_network():
    assert fetch_x_signals(handles=[], nitter_bases=_BASES) == []
