"""Google Calendar ingestion.

Runtime auth is an OAuth2 refresh-token flow (no browser): the client id /
secret / refresh token live in SSM. ``scripts/google_oauth_bootstrap.py``
mints the refresh token once, locally.

The Google API client is created lazily and can be injected for tests
(``fetch_calendar_signals(..., service=fake)``).
"""

from __future__ import annotations

import logging

import config
from storage.models import Signal
from timeutils import day_bounds_utc, local_date_of, today_local_iso

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _build_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=config.get_parameter(config.PARAM_GOOGLE_REFRESH_TOKEN),
        client_id=config.get_parameter(config.PARAM_GOOGLE_CLIENT_ID),
        client_secret=config.get_parameter(config.PARAM_GOOGLE_CLIENT_SECRET),
        token_uri=_TOKEN_URI,
        scopes=_SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def fetch_calendar_signals(
    day: str | None = None,
    *,
    service=None,
    calendar_id: str = "primary",
) -> list[Signal]:
    day = day or today_local_iso()
    service = service or _build_service()
    time_min, time_max = day_bounds_utc(day)

    resp = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )
    signals = _events_to_signals(resp.get("items", []), day)
    log.info("calendar: %d events for %s", len(signals), day)
    return signals


def _events_to_signals(items: list[dict], day: str) -> list[Signal]:
    signals: list[Signal] = []
    for ev in items:
        if _self_declined(ev):
            continue
        start = ev.get("start", {})
        start_at = start.get("dateTime") or start.get("date") or ""
        activity_date = local_date_of(start_at) if "T" in start_at else (start_at or day)
        summary = ev.get("summary") or "(sin título)"
        signals.append(
            Signal(
                source="calendar",
                external_id=ev.get("id", ""),
                type="event",
                title=summary[:200],
                summary=(ev.get("description") or "")[:1000],
                url=ev.get("htmlLink", ""),
                occurred_at=start_at,
                activity_date=activity_date,
                raw={
                    "status": ev.get("status"),
                    "recurringEventId": ev.get("recurringEventId"),
                    "allDay": "date" in start,
                },
            )
        )
    return signals


def _self_declined(ev: dict) -> bool:
    return any(
        att.get("self") and att.get("responseStatus") == "declined"
        for att in ev.get("attendees", [])
    )
