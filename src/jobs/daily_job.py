"""Daily orchestration: ingest -> dedup -> significance -> generate -> store
-> notify.

One EventBridge Scheduler tick a day lands here (via ``handler.py``); ``POST
/run`` hits the same function. Every stage guards its own failure: a broken
source or a Telegram hiccup degrades the run, it doesn't sink it.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def run(reason: str = "unknown", user_note: str = "") -> dict:
    import config
    from delivery.telegram_client import send_draft
    from generation.llm_client import generate_drafts
    from generation.significance import evaluate as evaluate_significance
    from ingestion.github_client import fetch_github_signals
    from ingestion.hackernews_client import fetch_hackernews_signals
    from storage.repository import Repository
    from timeutils import today_local_iso

    day = today_local_iso()
    signals = []
    errors: dict[str, str] = {}

    sources = [("github", fetch_github_signals)]
    if config.CALENDAR_ENABLED:
        from ingestion.calendar_client import fetch_calendar_signals

        sources.append(("calendar", fetch_calendar_signals))
    if config.X_ENABLED:
        from ingestion.x_client import fetch_x_signals

        sources.append(("x", fetch_x_signals))

    for name, fetch in sources:
        try:
            signals.extend(fetch())
        except Exception as exc:  # noqa: BLE001 — one source failing must not sink the run
            log.exception("%s ingestion failed", name)
            errors[name] = f"{type(exc).__name__}: {exc}"

    has_personal = any(s.source in ("github", "calendar") for s in signals)
    if config.ALWAYS_TECH_NEWS or not has_personal:
        try:
            signals.extend(fetch_hackernews_signals(limit=config.HACKERNEWS_LIMIT))
        except Exception as exc:  # noqa: BLE001
            log.exception("hackernews ingestion failed")
            errors["hackernews"] = f"{type(exc).__name__}: {exc}"

    repo = Repository()
    for signal in signals:
        repo.put_signal(signal)

    by_source: dict[str, int] = {}
    for signal in signals:
        by_source[signal.source] = by_source.get(signal.source, 0) + 1

    # --- generate ----------------------------------------------------------
    drafts = []
    user_note = (user_note or "").strip()
    significance = evaluate_significance(signals)
    if signals or user_note:
        recent_topics = repo.recent_topic_tags(day, config.DEDUP_LOOKBACK_DAYS)
        try:
            drafts = generate_drafts(
                signals=signals,
                recent_topics=recent_topics,
                target_date=day,
                significance=significance,
                telegram_chat_id=config.TELEGRAM_CHAT_ID,
                user_note=user_note,
                linkedin_always=config.LINKEDIN_ALWAYS,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("draft generation failed")
            errors["generation"] = f"{type(exc).__name__}: {exc}"

    # --- store + notify --------------------------------------------------
    sent = 0
    for draft in drafts:
        repo.put_draft(draft)
        try:
            message_id = send_draft(draft)
        except Exception as exc:  # noqa: BLE001 — a failed send must not lose the stored draft
            log.exception("telegram send failed for %s", draft.sk)
            errors.setdefault("telegram", f"{type(exc).__name__}: {exc}")
            continue
        if message_id:
            draft.telegram_message_id = message_id
            repo.put_draft(draft)
            sent += 1

    result = {
        "status": "ok",
        "reason": reason,
        "day": day,
        "signals": len(signals),
        "by_source": by_source,
        "drafts": len(drafts),
        "linkedin_worthy": significance.linkedin_worthy,
        "user_note_used": bool(user_note),
        "sent": sent,
        "errors": errors,
    }
    log.info("daily_job: %s", result)
    return result
