"""GitHub activity ingestion.

Reads the user's own events feed (``GET /users/{owner}/events``) — one call
covers pushes, PRs and new repos. Authenticated with a PAT from SSM, so it
sees private activity too. Events older than the lookback window are dropped.
"""

from __future__ import annotations

import logging

import requests

import config
from storage.models import Signal
from timeutils import local_date_of, parse_iso, utc_cutoff

log = logging.getLogger(__name__)

_API = "https://api.github.com"
_TIMEOUT = 10
_MAX_PAGES = 3


def fetch_github_signals(
    *,
    owner: str | None = None,
    lookback_hours: int | None = None,
    token: str | None = None,
    session: requests.Session | None = None,
) -> list[Signal]:
    owner = owner or config.GITHUB_OWNER
    lookback_hours = lookback_hours or config.INGEST_LOOKBACK_HOURS
    token = token or config.get_parameter(config.PARAM_GITHUB_TOKEN)
    http = session or requests.Session()
    cutoff = utc_cutoff(lookback_hours)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    signals: list[Signal] = []
    seen: set[str] = set()

    for page in range(1, _MAX_PAGES + 1):
        resp = http.get(
            f"{_API}/users/{owner}/events",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        events = resp.json()
        if not events:
            break

        reached_cutoff = False
        for ev in events:
            created = ev.get("created_at", "")
            if not created:
                continue
            if parse_iso(created) < cutoff:
                reached_cutoff = True
                break
            for sig in _event_to_signals(ev):
                if sig.sk in seen:
                    continue
                seen.add(sig.sk)
                signals.append(sig)

        if reached_cutoff or len(events) < 100:
            break

    log.info("github: %d signals for %s (last %dh)", len(signals), owner, lookback_hours)
    return signals


def _event_to_signals(ev: dict) -> list[Signal]:
    etype = ev.get("type")
    repo = (ev.get("repo") or {}).get("name", "")
    created = ev.get("created_at", "")
    day = local_date_of(created)
    payload = ev.get("payload") or {}

    if etype == "PushEvent":
        out: list[Signal] = []
        for commit in payload.get("commits", []):
            sha = commit.get("sha", "")
            if not sha or commit.get("distinct") is False:
                continue
            message = (commit.get("message") or "").strip()
            out.append(
                Signal(
                    source="github",
                    external_id=sha[:12],
                    type="commit",
                    title=(message.splitlines()[0] if message else f"commit {sha[:7]}")[:200],
                    summary=message[:1000],
                    url=f"https://github.com/{repo}/commit/{sha}" if repo else "",
                    occurred_at=created,
                    activity_date=day,
                    raw={"repo": repo, "sha": sha},
                )
            )
        return out

    if etype == "PullRequestEvent":
        action = payload.get("action")
        pr = payload.get("pull_request") or {}
        number = payload.get("number") or pr.get("number")
        merged = bool(pr.get("merged"))
        if action == "opened" or (action == "closed" and merged):
            state = "merged" if merged else "opened"
            return [
                Signal(
                    source="github",
                    external_id=f"pr-{repo}-{number}",
                    type="pr",
                    title=f"[{state}] {pr.get('title', '')}".strip()[:200],
                    summary=(pr.get("body") or "")[:1000],
                    url=pr.get("html_url", ""),
                    occurred_at=created,
                    activity_date=day,
                    raw={"repo": repo, "number": number, "state": state},
                )
            ]
        return []

    if etype == "CreateEvent" and payload.get("ref_type") == "repository":
        return [
            Signal(
                source="github",
                external_id=f"repo-{repo}",
                type="new_repo",
                title=f"New repo: {repo}"[:200],
                summary=payload.get("description") or "",
                url=f"https://github.com/{repo}" if repo else "",
                occurred_at=created,
                activity_date=day,
                raw={"repo": repo},
            )
        ]

    return []
