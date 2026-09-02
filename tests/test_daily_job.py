"""Source selection in the daily job — in particular that Calendar is only
touched when CALENDAR_ENABLED is set."""

from __future__ import annotations

import config
import ingestion.github_client as gh
import ingestion.hackernews_client as hn
import jobs.daily_job as daily_job
import storage.repository as repo_mod
from storage.models import Signal


class _FakeRepo:
    def __init__(self):
        self.signals: list[Signal] = []
        self.drafts: list = []

    def put_signal(self, s):
        self.signals.append(s)

    def put_draft(self, d):
        self.drafts.append(d)

    def recent_topic_tags(self, *_a, **_kw):
        return []


def _patch_common(
    monkeypatch, *, calendar_enabled: bool, always_tech_news: bool = False, x_enabled: bool = False
):
    monkeypatch.setattr(config, "CALENDAR_ENABLED", calendar_enabled)
    monkeypatch.setattr(config, "ALWAYS_TECH_NEWS", always_tech_news)
    monkeypatch.setattr(config, "X_ENABLED", x_enabled)
    monkeypatch.setattr(repo_mod, "Repository", lambda: _FakeRepo())
    monkeypatch.setattr(
        gh,
        "fetch_github_signals",
        lambda: [
            Signal(
                source="github",
                external_id="c1",
                type="commit",
                title="Add X",
                activity_date="2026-08-30",
            )
        ],
    )
    monkeypatch.setattr(
        hn,
        "fetch_hackernews_signals",
        lambda **_kw: [
            Signal(
                source="hackernews",
                external_id="hn1",
                type="story",
                title="Some tech story",
                activity_date="2026-08-30",
            )
        ],
    )
    # no drafts / no telegram — keep the run offline
    import generation.llm_client as llm

    monkeypatch.setattr(llm, "generate", lambda *_a, **_kw: {"tweets": [], "linkedin": None})


def test_calendar_skipped_when_disabled(monkeypatch):
    _patch_common(monkeypatch, calendar_enabled=False)

    called = {"calendar": False}
    import ingestion.calendar_client as cal

    monkeypatch.setattr(
        cal,
        "fetch_calendar_signals",
        lambda *_a, **_kw: called.__setitem__("calendar", True) or [],
    )

    result = daily_job.run(reason="test")

    assert called["calendar"] is False
    assert result["by_source"] == {"github": 1}
    assert "calendar" not in result["errors"]


def test_calendar_used_when_enabled(monkeypatch):
    _patch_common(monkeypatch, calendar_enabled=True)

    called = {"calendar": False}
    import ingestion.calendar_client as cal

    monkeypatch.setattr(
        cal,
        "fetch_calendar_signals",
        lambda *_a, **_kw: called.__setitem__("calendar", True) or [],
    )

    daily_job.run(reason="test")

    assert called["calendar"] is True


def test_hackernews_pulled_alongside_activity_when_always_on(monkeypatch):
    _patch_common(monkeypatch, calendar_enabled=False, always_tech_news=True)
    import ingestion.calendar_client as cal

    monkeypatch.setattr(cal, "fetch_calendar_signals", lambda *_a, **_kw: [])

    result = daily_job.run(reason="test")

    assert result["by_source"] == {"github": 1, "hackernews": 1}


def test_linkedin_always_flag_reaches_generation(monkeypatch):
    _patch_common(monkeypatch, calendar_enabled=False)
    monkeypatch.setattr(config, "LINKEDIN_ALWAYS", True)
    import generation.llm_client as llm

    captured = {}
    monkeypatch.setattr(llm, "generate_drafts", lambda **kw: captured.update(kw) or [])

    daily_job.run(reason="test")

    assert captured["linkedin_always"] is True


def test_x_skipped_when_disabled(monkeypatch):
    _patch_common(monkeypatch, calendar_enabled=False, x_enabled=False)
    import ingestion.x_client as x

    called = {"x": False}
    monkeypatch.setattr(
        x, "fetch_x_signals", lambda *_a, **_kw: called.__setitem__("x", True) or []
    )

    result = daily_job.run(reason="test")

    assert called["x"] is False
    assert "x" not in result["by_source"]
    assert "x" not in result["errors"]


def test_x_signals_ingested_when_enabled(monkeypatch):
    _patch_common(monkeypatch, calendar_enabled=False, x_enabled=True)
    import ingestion.x_client as x

    monkeypatch.setattr(
        x,
        "fetch_x_signals",
        lambda *_a, **_kw: [
            Signal(
                source="x",
                external_id="1001",
                type="tweet",
                title="Framework release",
                url="https://twitter.com/acme/status/1001",
                activity_date="2026-08-30",
            )
        ],
    )

    result = daily_job.run(reason="test")

    assert result["by_source"].get("x") == 1
    assert "x" not in result["errors"]


def test_x_failure_is_captured_not_fatal(monkeypatch):
    _patch_common(monkeypatch, calendar_enabled=False, x_enabled=True)
    import ingestion.x_client as x

    def boom(*_a, **_kw):
        raise RuntimeError("no working Nitter instance")

    monkeypatch.setattr(x, "fetch_x_signals", boom)

    result = daily_job.run(reason="test")

    assert result["status"] == "ok"
    assert "no working Nitter instance" in result["errors"]["x"]
    assert result["by_source"] == {"github": 1}


def test_hackernews_is_fallback_only_when_always_off(monkeypatch):
    _patch_common(monkeypatch, calendar_enabled=False, always_tech_news=False)
    import ingestion.calendar_client as cal

    monkeypatch.setattr(cal, "fetch_calendar_signals", lambda *_a, **_kw: [])

    result = daily_job.run(reason="test")

    assert result["by_source"] == {"github": 1}  # no HN because there was activity
