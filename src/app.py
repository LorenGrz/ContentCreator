"""FastAPI app for the HTTP surface of the bot.

Routes:
    GET  /health            liveness probe
    GET  /drafts?date=...    inspect stored drafts for a day (default: today, local tz)
    POST /run                manually trigger the daily job (same code path as the schedule)
    POST /telegram/webhook   Telegram callback for the Approve / Discard inline buttons

The daily job itself is driven by EventBridge Scheduler and dispatched in
``handler.py`` before the event ever reaches this app.
"""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Query

import config
from storage.repository import Repository
from timeutils import today_local_iso

app = FastAPI(title="content-creator", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "content-creator"}


@app.get("/drafts")
def list_drafts(date: str | None = Query(default=None)) -> dict:
    target = date or today_local_iso()
    drafts = Repository().list_drafts_for_date(target)
    return {
        "date": target,
        "count": len(drafts),
        "drafts": [d.to_item() for d in drafts],
    }


@app.post("/run")
def run_daily_job() -> dict:
    # Lazy import: keeps app import cheap and avoids pulling the LLM stack
    # into the webhook path.
    from jobs.daily_job import run

    return run(reason="manual /run")


@app.post("/telegram/webhook")
async def telegram_webhook(
    update: dict,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    if (
        not config.TELEGRAM_WEBHOOK_SECRET
        or x_telegram_bot_api_secret_token != config.TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403, detail="bad secret token")

    from delivery.telegram_client import handle_update

    return handle_update(update)
