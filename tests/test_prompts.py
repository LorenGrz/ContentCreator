import json

from generation.prompts import SYSTEM_PROMPT, build_user_message
from storage.models import Signal


def _sig(source="github", **kw) -> Signal:
    base = dict(
        source=source,
        external_id="x",
        type="commit",
        title="t",
        activity_date="2026-08-29",
    )
    base.update(kw)
    return Signal(**base)


def test_system_prompt_states_json_shape_and_no_autopost():
    assert '"tweets"' in SYSTEM_PROMPT
    assert "JSON" in SYSTEM_PROMPT
    assert "revise y publique a mano" in SYSTEM_PROMPT


def test_system_prompt_describes_quote_tweet_option():
    assert "quote_tweet" in SYSTEM_PROMPT
    assert "quote_url" in SYSTEM_PROMPT


def test_x_signal_asks_for_a_quote_tweet():
    msg = build_user_message(
        signals=[
            _sig(title="Add repo layer", external_id="c1"),
            _sig(
                source="x",
                type="tweet",
                title="Big framework release",
                external_id="1001",
                url="https://twitter.com/acme/status/1001",
            ),
        ],
        recent_topics=[],
        target_date="2026-08-29",
        want_linkedin=False,
    )
    data = json.loads(msg)
    assert data["mode"] == "personal_activity"
    assert "quote_tweet" in data["instructions"]
    assert data["signals"][1]["url"] == "https://twitter.com/acme/status/1001"


def test_user_message_carries_signals_and_recent_topics():
    msg = build_user_message(
        signals=[_sig(title="Add repository layer", external_id="c1")],
        recent_topics=["dynamodb-single-table", "sam-scaffold"],
        target_date="2026-08-29",
        want_linkedin=False,
    )
    data = json.loads(msg)
    assert data["target_date"] == "2026-08-29"
    assert data["want_linkedin"] is False
    assert data["mode"] == "personal_activity"
    assert data["recent_topics"] == ["dynamodb-single-table", "sam-scaffold"]
    assert data["signals"][0]["title"] == "Add repository layer"


def test_curated_news_only_switches_to_reflection_mode():
    msg = build_user_message(
        signals=[
            _sig(
                source="weekly_ai_news_digest",
                type="story",
                title="Some tech story",
                external_id="s1",
            )
        ],
        recent_topics=[],
        target_date="2026-08-29",
        want_linkedin=False,
    )
    data = json.loads(msg)
    assert data["mode"] == "tech_reflection"
    assert "reflexión" in data["instructions"]


def test_activity_plus_news_always_asks_for_a_tech_news_tweet():
    msg = build_user_message(
        signals=[
            _sig(title="Add repo layer", external_id="c1"),
            _sig(
                source="weekly_ai_news_digest",
                type="story",
                title="Big tech story",
                external_id="s1",
            ),
        ],
        recent_topics=[],
        target_date="2026-08-29",
        want_linkedin=False,
    )
    data = json.loads(msg)
    assert data["mode"] == "personal_activity"
    assert "source: weekly_ai_news_digest" in data["instructions"]
    assert "SIEMPRE al menos 1 tweet" in data["instructions"]


def test_user_note_included_and_switches_mode_when_no_signals():
    msg = build_user_message(
        signals=[],
        recent_topics=[],
        target_date="2026-08-29",
        want_linkedin=False,
        user_note="escribí algo sobre el refactor de storage",
    )
    data = json.loads(msg)
    assert data["mode"] == "user_note_only"
    assert data["user_note"] == "escribí algo sobre el refactor de storage"
    assert "user_note" in data["instructions"]


def test_user_note_with_signals_keeps_activity_mode():
    msg = build_user_message(
        signals=[_sig(title="Add repo layer", external_id="c1")],
        recent_topics=[],
        target_date="2026-08-29",
        want_linkedin=False,
        user_note="enfocate en el aprendizaje, no en el feature",
    )
    data = json.loads(msg)
    assert data["mode"] == "personal_activity"
    assert data["user_note"] == "enfocate en el aprendizaje, no en el feature"


def test_linkedin_always_on_adds_daily_reflection_nudge():
    msg = build_user_message(
        signals=[_sig(title="pequeño ajuste", external_id="c1")],
        recent_topics=[],
        target_date="2026-08-29",
        want_linkedin=True,
        linkedin_high_signal=False,
    )
    data = json.loads(msg)
    assert data["want_linkedin"] is True
    assert data["linkedin_high_signal"] is False
    assert "reflexión breve del día" in data["instructions"]


def test_linkedin_high_signal_skips_the_reflection_nudge():
    pr = _sig(type="pr", title="[merged] Ship", external_id="pr1", raw={"state": "merged"})
    msg = build_user_message(
        signals=[pr],
        recent_topics=[],
        target_date="2026-08-29",
        want_linkedin=True,
        linkedin_high_signal=True,
    )
    data = json.loads(msg)
    assert data["linkedin_high_signal"] is True
    assert "reflexión breve del día" not in data["instructions"]


def test_linkedin_rationale_passed_through_when_wanted():
    msg = build_user_message(
        signals=[
            _sig(type="pr", title="[merged] Ship", external_id="pr1", raw={"state": "merged"})
        ],
        recent_topics=[],
        target_date="2026-08-29",
        want_linkedin=True,
        significance_reasons=["merged PR: [merged] Ship"],
    )
    data = json.loads(msg)
    assert data["want_linkedin"] is True
    assert data["linkedin_rationale"] == ["merged PR: [merged] Ship"]
