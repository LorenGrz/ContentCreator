from datetime import UTC, datetime, timedelta

import responses

import config
from ingestion.github_client import fetch_github_signals

_EVENTS_URL = "https://api.github.com/users/LorenGrz/events"


def _events():
    now = datetime.now(UTC)
    recent = (now - timedelta(hours=2)).isoformat()
    old = (now - timedelta(days=200)).isoformat()
    return [
        {
            "type": "PushEvent",
            "created_at": recent,
            "repo": {"name": "LorenGrz/content-creator"},
            "payload": {
                "commits": [
                    {
                        "sha": "abc123def4567",
                        "message": "Add ingestion layer\n\nbody",
                        "distinct": True,
                    },
                    {"sha": "dup000", "message": "merge branch", "distinct": False},
                ]
            },
        },
        {
            "type": "PullRequestEvent",
            "created_at": recent,
            "repo": {"name": "LorenGrz/x"},
            "payload": {
                "action": "closed",
                "number": 7,
                "pull_request": {
                    "title": "Ship feature",
                    "merged": True,
                    "html_url": "https://github.com/LorenGrz/x/pull/7",
                    "body": "desc",
                },
            },
        },
        {
            "type": "CreateEvent",
            "created_at": recent,
            "repo": {"name": "LorenGrz/new-thing"},
            "payload": {"ref_type": "repository", "description": "a fresh repo"},
        },
        {"type": "WatchEvent", "created_at": recent, "repo": {"name": "z/z"}, "payload": {}},
        {
            "type": "PushEvent",
            "created_at": old,
            "repo": {"name": "LorenGrz/old"},
            "payload": {"commits": [{"sha": "old1", "message": "old", "distinct": True}]},
        },
    ]


@responses.activate
def test_maps_events_and_drops_stale_and_noise(monkeypatch):
    monkeypatch.setattr(config, "get_parameter", lambda *a, **k: "tok")
    responses.add(responses.GET, _EVENTS_URL, json=_events(), status=200)

    signals = fetch_github_signals(owner="LorenGrz", lookback_hours=24)

    assert sorted(s.type for s in signals) == ["commit", "new_repo", "pr"]

    commit = next(s for s in signals if s.type == "commit")
    assert commit.external_id == "abc123def456"  # sha truncated to 12
    assert commit.title == "Add ingestion layer"
    assert commit.url == "https://github.com/LorenGrz/content-creator/commit/abc123def4567"

    pr = next(s for s in signals if s.type == "pr")
    assert pr.external_id == "pr-LorenGrz/x-7"
    assert pr.title.startswith("[merged]")

    new_repo = next(s for s in signals if s.type == "new_repo")
    assert new_repo.external_id == "repo-LorenGrz/new-thing"


@responses.activate
def test_reads_token_from_ssm_when_not_passed(monkeypatch):
    calls = {}

    def fake_get_parameter(name, **kwargs):
        calls["name"] = name
        return "tok"

    monkeypatch.setattr(config, "get_parameter", fake_get_parameter)
    responses.add(responses.GET, _EVENTS_URL, json=[], status=200)

    fetch_github_signals(owner="LorenGrz")

    assert calls["name"] == config.PARAM_GITHUB_TOKEN
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"
