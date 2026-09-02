from generation.significance import evaluate
from storage.models import Signal


def _sig(**kw) -> Signal:
    base = dict(
        source="github",
        external_id="x",
        type="commit",
        title="t",
        activity_date="2026-08-29",
    )
    base.update(kw)
    return Signal(**base)


def test_only_commits_is_not_linkedin_worthy():
    verdict = evaluate(
        [_sig(type="commit", external_id="c1"), _sig(type="commit", external_id="c2")]
    )
    assert verdict.linkedin_worthy is False
    assert verdict.reasons == []


def test_merged_pr_is_worthy():
    pr = _sig(type="pr", external_id="pr-1", title="[merged] Ship X", raw={"state": "merged"})
    verdict = evaluate([_sig(type="commit", external_id="c1"), pr])
    assert verdict.linkedin_worthy is True
    assert pr.sk in verdict.highlight_keys
    assert any("merged PR" in r for r in verdict.reasons)


def test_opened_pr_is_not_worthy():
    pr = _sig(type="pr", external_id="pr-2", title="[opened] WIP", raw={"state": "opened"})
    assert evaluate([pr]).linkedin_worthy is False


def test_new_repo_is_worthy():
    repo = _sig(type="new_repo", external_id="repo-x", title="New repo: LorenGrz/thing")
    assert evaluate([repo]).linkedin_worthy is True


def test_calendar_keyword_event_is_worthy_but_plain_meeting_is_not():
    talk = Signal(
        source="calendar",
        external_id="e1",
        type="event",
        title="Charla sobre serverless en la meetup",
        activity_date="2026-08-29",
    )
    standup = Signal(
        source="calendar",
        external_id="e2",
        type="event",
        title="Daily standup",
        activity_date="2026-08-29",
    )
    verdict = evaluate([talk, standup])
    assert verdict.linkedin_worthy is True
    assert talk.sk in verdict.highlight_keys
    assert standup.sk not in verdict.highlight_keys
