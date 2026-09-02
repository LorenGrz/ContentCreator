import responses

from ingestion.hackernews_client import fetch_hackernews_signals

_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"


def _item_url(sid):
    return f"https://hacker-news.firebaseio.com/v0/item/{sid}.json"


@responses.activate
def test_returns_only_stories_up_to_limit():
    responses.add(responses.GET, _TOP, json=[1, 2, 3, 4], status=200)
    responses.add(
        responses.GET,
        _item_url(1),
        json={
            "type": "story",
            "title": "AI does thing",
            "url": "https://ex/1",
            "time": 1756500000,
            "score": 120,
        },
    )
    responses.add(
        responses.GET, _item_url(2), json={"type": "job", "title": "We are hiring", "time": 1}
    )
    responses.add(
        responses.GET,
        _item_url(3),
        json={"type": "story", "title": "Automation trend", "time": 1756500002, "score": 80},
    )
    responses.add(
        responses.GET, _item_url(4), json={"type": "story", "title": "Third", "time": 1756500003}
    )

    signals = fetch_hackernews_signals(limit=2)

    assert [s.title for s in signals] == ["AI does thing", "Automation trend"]
    assert signals[0].url == "https://ex/1"
    assert signals[1].url == "https://news.ycombinator.com/item?id=3"  # no url -> HN permalink
    assert all(s.source == "hackernews" and s.type == "story" for s in signals)
    assert signals[0].raw["score"] == 120
