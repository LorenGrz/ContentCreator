import pytest

from generation.llm_client import generate_drafts, parse_model_json, to_drafts
from generation.significance import Significance
from storage.models import Signal


def _sig(external_id="c1", **kw) -> Signal:
    base = dict(
        source="github",
        external_id=external_id,
        type="commit",
        title="t",
        activity_date="2026-08-29",
    )
    base.update(kw)
    return Signal(**base)


def test_parse_model_json_extracts_object_with_surrounding_prose():
    raw = 'Sure, here you go:\n```json\n{"tweets": [{"content": "hi"}], "linkedin": null}\n```\n'
    data = parse_model_json(raw)
    assert data["tweets"][0]["content"] == "hi"
    assert data["linkedin"] is None


def test_parse_model_json_raises_without_json():
    with pytest.raises(ValueError):
        parse_model_json("no json here")


def test_to_drafts_maps_tweets_and_linkedin_and_caps_count():
    parsed = {
        "tweets": [
            {"content": "one", "topic_tags": ["Serverless", "sam scaffold"]},
            {"content": "two", "topic_tags": []},
            {"content": "three"},
            {"content": "four"},
            {"content": "five — should be dropped"},
        ],
        "linkedin": {"content": "para 1\n\npara 2", "topic_tags": ["merged-pr"]},
    }
    drafts = to_drafts(
        parsed,
        target_date="2026-08-29",
        signal_keys=["SIGNAL#github#c1"],
        linkedin_keys=["SIGNAL#github#pr1"],
        telegram_chat_id="42",
    )
    tweets = [d for d in drafts if d.platform == "twitter"]
    linkedin = [d for d in drafts if d.platform == "linkedin"]

    assert len(tweets) == 4  # capped at MAX_TWEETS
    assert tweets[0].topic_tags == ["serverless", "sam-scaffold"]
    assert tweets[0].source_signal_keys == ["SIGNAL#github#c1"]
    assert tweets[0].telegram_chat_id == "42"
    assert len(linkedin) == 1
    assert linkedin[0].source_signal_keys == ["SIGNAL#github#pr1"]
    assert all(d.status == "pending" for d in drafts)


def test_to_drafts_keeps_quote_tweet_when_quote_url_matches_an_x_signal():
    parsed = {
        "tweets": [
            {
                "content": "mi ángulo sobre esto",
                "kind": "quote_tweet",
                "quote_url": "https://twitter.com/acme/status/1001",
            }
        ],
        "linkedin": None,
    }
    drafts = to_drafts(
        parsed,
        target_date="2026-08-29",
        signal_keys=[],
        quote_urls={"https://twitter.com/acme/status/1001"},
    )
    assert drafts[0].kind == "quote_tweet"
    assert drafts[0].quote_url == "https://twitter.com/acme/status/1001"


def test_to_drafts_downgrades_quote_tweet_with_unknown_or_missing_url():
    parsed = {
        "tweets": [
            {"content": "a", "kind": "quote_tweet", "quote_url": "https://twitter.com/evil/status/9"},
            {"content": "b", "kind": "quote_tweet"},
            {"content": "c"},
        ],
        "linkedin": None,
    }
    drafts = to_drafts(
        parsed,
        target_date="2026-08-29",
        signal_keys=[],
        quote_urls={"https://twitter.com/acme/status/1001"},
    )
    assert [(d.kind, d.quote_url) for d in drafts] == [
        ("original", ""),
        ("original", ""),
        ("original", ""),
    ]


def test_to_drafts_skips_empty_content_and_missing_linkedin():
    parsed = {"tweets": [{"content": "  "}, {"content": "real"}], "linkedin": None}
    drafts = to_drafts(parsed, target_date="2026-08-29", signal_keys=[])
    assert [d.content for d in drafts] == ["real"]


def test_generate_drafts_wires_prompt_to_model(monkeypatch):
    captured = {}

    def fake_generate(user_message, **kw):
        captured["msg"] = user_message
        return {"tweets": [{"content": "generated"}], "linkedin": None}

    monkeypatch.setattr("generation.llm_client.generate", fake_generate)

    drafts = generate_drafts(
        signals=[_sig(title="Add X")],
        recent_topics=["old-topic"],
        target_date="2026-08-29",
        significance=Significance(linkedin_worthy=False),
        telegram_chat_id="7",
    )
    assert "old-topic" in captured["msg"]
    assert len(drafts) == 1
    assert drafts[0].content == "generated"
    assert drafts[0].source_signal_keys == ["SIGNAL#github#c1"]
