from ingestion.calendar_client import fetch_calendar_signals


class _FakeExec:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeEvents:
    def __init__(self, payload):
        self._payload = payload
        self.list_kwargs = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return _FakeExec(self._payload)


class _FakeService:
    def __init__(self, payload):
        self._events = _FakeEvents(payload)

    def events(self):
        return self._events


def test_maps_events_skips_declined_and_passes_day_window():
    payload = {
        "items": [
            {
                "id": "e1",
                "summary": "Deploy review",
                "description": "notes",
                "htmlLink": "https://cal/e1",
                "status": "confirmed",
                "start": {"dateTime": "2026-08-30T14:00:00-03:00"},
            },
            {
                "id": "e2",
                "summary": "Declined meeting",
                "start": {"dateTime": "2026-08-30T15:00:00-03:00"},
                "attendees": [{"self": True, "responseStatus": "declined"}],
            },
            {"id": "e3", "summary": "All-day offsite", "start": {"date": "2026-08-30"}},
        ]
    }
    service = _FakeService(payload)

    signals = fetch_calendar_signals(day="2026-08-30", service=service)

    assert sorted(s.external_id for s in signals) == ["e1", "e3"]

    e1 = next(s for s in signals if s.external_id == "e1")
    assert e1.source == "calendar" and e1.type == "event"
    assert e1.title == "Deploy review"
    assert e1.activity_date == "2026-08-30"
    assert e1.url == "https://cal/e1"

    kwargs = service.events().list_kwargs
    assert kwargs["singleEvents"] is True
    assert kwargs["timeMin"].startswith("2026-08-30")
    assert kwargs["timeMax"].startswith("2026-08-31")


def test_missing_summary_falls_back():
    service = _FakeService({"items": [{"id": "x", "start": {"date": "2026-08-30"}}]})
    (signal,) = fetch_calendar_signals(day="2026-08-30", service=service)
    assert signal.title == "(sin título)"
