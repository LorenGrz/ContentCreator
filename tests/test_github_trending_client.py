from __future__ import annotations

import responses

import config
from ingestion.github_trending_client import fetch_github_trending_signals

SAMPLE_SEARCH_RESPONSE = {
    "total_count": 2,
    "items": [
        {
            "full_name": "agent-org/super-agent",
            "html_url": "https://github.com/agent-org/super-agent",
            "stargazers_count": 1250,
            "forks_count": 95,
            "description": "Autonomous developer agent for automating refactors and tests.",
            "language": "Python",
            "topics": ["ai", "agent", "developer-tools", "automation"],
            "created_at": "2026-09-20T10:00:00Z",
        },
        {
            "full_name": "vision-labs/flow-edit",
            "html_url": "https://github.com/vision-labs/flow-edit",
            "stargazers_count": 840,
            "forks_count": 42,
            "description": "Real-time diffusion pipeline with interactive canvas.",
            "language": "Rust",
            "topics": ["ai", "diffusion", "canvas"],
            "created_at": "2026-09-22T14:30:00Z",
        },
    ],
}


@responses.activate
def test_fetch_github_trending_signals_parses_items(monkeypatch):
    monkeypatch.setattr(config, "get_parameter", lambda _name: "ghp_fake_token")
    responses.add(
        responses.GET,
        "https://api.github.com/search/repositories",
        json=SAMPLE_SEARCH_RESPONSE,
        status=200,
    )

    signals = fetch_github_trending_signals(limit=2)

    assert len(signals) == 2
    first = signals[0]
    assert first.source == "github_trending"
    assert first.type == "repo"
    assert "agent-org/super-agent" in first.title
    assert "1250" in first.title
    assert "Autonomous developer agent" in first.summary
    assert "Lenguaje: Python" in first.summary
    assert first.url == "https://github.com/agent-org/super-agent"
    assert first.raw["stars"] == 1250
    assert first.raw["forks"] == 95

    # Check authorization header
    call = responses.calls[0]
    assert call.request.headers.get("Authorization") == "Bearer ghp_fake_token"


@responses.activate
def test_fetch_github_trending_signals_limit_zero():
    signals = fetch_github_trending_signals(limit=0)
    assert signals == []


@responses.activate
def test_fetch_github_trending_signals_custom_query():
    responses.add(
        responses.GET,
        "https://api.github.com/search/repositories",
        json=SAMPLE_SEARCH_RESPONSE,
        status=200,
    )

    import urllib.parse

    fetch_github_trending_signals(limit=1, query="stars:>500 topic:rust")
    call = responses.calls[0]
    assert "stars:>500 topic:rust" in urllib.parse.unquote_plus(call.request.url)
