from storage.models import Draft, Signal
from storage.repository import Repository


def _repo(table):
    return Repository(table=table)


def test_put_and_list_signals_for_date(dynamodb_table):
    repo = _repo(dynamodb_table)
    repo.put_signal(
        Signal(
            source="github",
            external_id="abc123",
            type="commit",
            title="Fix null check",
            activity_date="2026-08-29",
            url="https://github.com/x/y/commit/abc123",
        )
    )
    repo.put_signal(
        Signal(
            source="calendar",
            external_id="evt-1",
            type="event",
            title="Deploy review",
            activity_date="2026-08-29",
        )
    )
    repo.put_signal(
        Signal(
            source="github",
            external_id="other",
            type="commit",
            title="Different day",
            activity_date="2026-08-28",
        )
    )

    signals = repo.list_signals_for_date("2026-08-29")

    assert {s.external_id for s in signals} == {"abc123", "evt-1"}
    assert all(s.pk == "DATE#2026-08-29" for s in signals)


def test_signal_raw_is_truncated(dynamodb_table):
    repo = _repo(dynamodb_table)
    repo.put_signal(
        Signal(
            source="github",
            external_id="big",
            type="commit",
            title="huge payload",
            activity_date="2026-08-29",
            raw={"blob": "x" * 10_000},
        )
    )
    (signal,) = repo.list_signals_for_date("2026-08-29")
    assert signal.raw.get("_truncated") is True


def test_draft_round_trip_and_optional_none_is_dropped(dynamodb_table):
    repo = _repo(dynamodb_table)
    draft = Draft(
        platform="twitter",
        content="shipped a thing today",
        target_date="2026-08-30",
        topic_tags=["dynamodb", "sam"],
        source_signal_keys=["SIGNAL#github#abc123"],
    )
    repo.put_draft(draft)

    stored = repo.get_draft("2026-08-30", draft.sk)
    assert stored is not None
    assert stored.content == "shipped a thing today"
    assert stored.status == "pending"
    assert stored.telegram_message_id is None
    assert stored.topic_tags == ["dynamodb", "sam"]


def test_recent_topic_tags_dedups_across_days(dynamodb_table):
    repo = _repo(dynamodb_table)
    repo.put_draft(
        Draft(platform="twitter", content="a", target_date="2026-08-30", topic_tags=["sam", "iam"])
    )
    repo.put_draft(
        Draft(
            platform="twitter", content="b", target_date="2026-08-25", topic_tags=["iam", "bedrock"]
        )
    )
    repo.put_draft(
        Draft(platform="twitter", content="c", target_date="2026-08-10", topic_tags=["old"])
    )

    tags = repo.recent_topic_tags("2026-08-30", days=14)

    assert set(tags) == {"sam", "iam", "bedrock"}
    assert "old" not in tags  # outside the 14-day window


def test_update_draft_status_is_idempotent(dynamodb_table):
    repo = _repo(dynamodb_table)
    draft = Draft(platform="linkedin", content="milestone", target_date="2026-08-30")
    repo.put_draft(draft)

    first = repo.update_draft_status(
        "2026-08-30", draft.sk, "approved", "2026-08-30T10:00:00+00:00"
    )
    assert first is not None and first.status == "approved"
    assert first.decided_at == "2026-08-30T10:00:00+00:00"

    # Second tap (e.g. user double-clicks Discard) must not overwrite.
    second = repo.update_draft_status(
        "2026-08-30", draft.sk, "discarded", "2026-08-30T10:05:00+00:00"
    )
    assert second is not None and second.status == "approved"


def test_update_draft_status_missing_draft_returns_none(dynamodb_table):
    repo = _repo(dynamodb_table)
    result = repo.update_draft_status(
        "2026-08-30", "DRAFT#twitter#nope", "approved", "2026-08-30T10:00:00+00:00"
    )
    assert result is None
