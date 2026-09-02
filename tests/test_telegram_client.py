import json

import responses

import delivery.telegram_client as tg
from storage.models import Draft

_BASE = "https://api.telegram.org/botTEST"


def _capture(sink):
    """Return a _send_message stand-in that appends (text, kwargs)."""

    def _fn(cid, text, s=None, **kw):
        sink.append((text, kw))

    return _fn


def _draft(**kw) -> Draft:
    base = dict(
        platform="twitter",
        content="shipped the ingestion layer today",
        target_date="2026-08-29",
        topic_tags=["ingestion", "github-api"],
        draft_id="deadbeef",
    )
    base.update(kw)
    return Draft(**base)


class FakeRepo:
    """In-memory stand-in for Repository — enough for the Telegram flow."""

    def __init__(self, drafts=None, state=None):
        self.drafts = {(d.target_date, d.sk): d for d in (drafts or [])}
        self.state = dict(state) if state else None
        self.content_updates = []

    def get_draft(self, target_date, sk):
        return self.drafts.get((target_date, sk))

    def update_draft_status(self, target_date, sk, status, decided_at):
        d = self.drafts.get((target_date, sk))
        if d and d.status == "pending":
            d.status = status
            d.decided_at = decided_at
        return d

    def update_draft_content(self, target_date, sk, content, edited_at):
        d = self.drafts.get((target_date, sk))
        if d:
            d.content = content
            d.edited_at = edited_at
        self.content_updates.append((sk, content))
        return d

    def get_chat_state(self, chat_id):
        return self.state

    def set_chat_state(self, chat_id, **attrs):
        self.state = attrs

    def clear_chat_state(self, chat_id):
        self.state = {"mode": "idle"}


# --- send_draft ----------------------------------------------------------


def test_send_draft_posts_message_with_two_buttons(monkeypatch):
    monkeypatch.setattr(tg, "_token", lambda: "TEST")
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            f"{_BASE}/sendMessage",
            json={"ok": True, "result": {"message_id": 555}},
        )
        message_id = tg.send_draft(_draft(), chat_id="123")

        assert message_id == 555
        payload = json.loads(rsps.calls[0].request.body)
        assert payload["chat_id"] == "123"
        buttons = payload["reply_markup"]["inline_keyboard"][0]
        assert buttons[0]["callback_data"] == "a:2026-08-29:t:deadbeef"
        assert buttons[1]["callback_data"] == "d:2026-08-29:t:deadbeef"


def test_send_draft_noop_without_chat_id(monkeypatch):
    monkeypatch.setattr(tg, "_token", lambda: "TEST")
    monkeypatch.setattr(tg.config, "TELEGRAM_CHAT_ID", "")
    assert tg.send_draft(_draft()) is None


# --- callback path -----------------------------------------------------


def _cb(data, cid=6891166315, mid=555):
    return {"callback_query": {"id": "cq1", "data": data,
                               "message": {"chat": {"id": cid}, "message_id": mid}}}


def test_approve_sends_ready_text_with_copy_and_edit_buttons(monkeypatch):
    sent = []
    monkeypatch.setattr(tg, "_call", lambda m, p, s=None: {"ok": True})
    monkeypatch.setattr(tg, "_send_message", _capture(sent))
    repo = FakeRepo(drafts=[_draft(content="shipped the storage layer")])

    out = tg.handle_update(_cb("a:2026-08-29:t:deadbeef"), repo=repo)

    assert out["status"] == "approved"
    assert repo.drafts[("2026-08-29", "DRAFT#twitter#deadbeef")].status == "approved"
    assert repo.state is None  # approve no longer forces an edit session
    text, kw = sent[0]
    assert text == "shipped the storage layer"
    kb = kw["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["copy_text"]["text"] == "shipped the storage layer"
    assert kb[0][1]["url"].startswith("https://twitter.com/intent/tweet?text=")
    assert kb[1][0]["callback_data"] == "e:2026-08-29:t:deadbeef"


def test_quote_tweet_draft_formats_with_quote_label_and_source():
    draft = _draft(
        content="mi comentario",
        kind="quote_tweet",
        quote_url="https://twitter.com/acme/status/1001",
    )
    text = tg._format(draft)
    assert "🔁 Quote tweet" in text
    assert "citando: https://twitter.com/acme/status/1001" in text


def test_quote_tweet_keyboard_opens_x_intent_with_url_and_original_link():
    draft = _draft(
        content="mi comentario",
        kind="quote_tweet",
        quote_url="https://twitter.com/acme/status/1001",
    )
    kb = tg._result_keyboard(draft)["inline_keyboard"]
    open_in_x = kb[0][-1]
    assert open_in_x["text"] == "✍️ Abrir en X"
    assert open_in_x["url"].startswith("https://twitter.com/intent/tweet?text=")
    assert "url=https%3A%2F%2Ftwitter.com%2Facme%2Fstatus%2F1001" in open_in_x["url"]
    assert kb[1] == [
        {"text": "🔗 Ver tweet original", "url": "https://twitter.com/acme/status/1001"}
    ]
    assert kb[2][0]["callback_data"] == "e:2026-08-29:t:deadbeef"


def test_approve_long_tweet_omits_copy_button_keeps_open_in_x(monkeypatch):
    sent = []
    monkeypatch.setattr(tg, "_call", lambda m, p, s=None: {"ok": True})
    monkeypatch.setattr(tg, "_send_message", _capture(sent))
    long_text = "x" * 270
    repo = FakeRepo(drafts=[_draft(content=long_text)])

    tg.handle_update(_cb("a:2026-08-29:t:deadbeef"), repo=repo)

    kb = sent[0][1]["reply_markup"]["inline_keyboard"]
    assert all("copy_text" not in b for b in kb[0])
    assert kb[0][0]["url"].startswith("https://twitter.com/intent/tweet?text=")


def test_edit_button_opens_session(monkeypatch):
    sent = []
    monkeypatch.setattr(tg, "_call", lambda m, p, s=None: {"ok": True})
    monkeypatch.setattr(tg, "_send_message", lambda cid, text, s=None, **kw: sent.append(text))
    repo = FakeRepo(drafts=[_draft(status="approved")])

    out = tg.handle_update(_cb("e:2026-08-29:t:deadbeef"), repo=repo)

    assert out["action"] == "e"
    assert repo.state["mode"] == "awaiting_edit"
    assert repo.state["draft_sk"] == "DRAFT#twitter#deadbeef"
    assert "Mandame el ajuste" in sent[0]


def test_discard_marks_draft_and_clears_session(monkeypatch):
    monkeypatch.setattr(tg, "_call", lambda m, p, s=None: {"ok": True})
    monkeypatch.setattr(tg, "_send_message", lambda *a, **kw: None)
    repo = FakeRepo(drafts=[_draft()], state={"mode": "awaiting_edit", "draft_sk": "x"})

    out = tg.handle_update(_cb("d:2026-08-29:t:deadbeef"), repo=repo)

    assert out["status"] == "discarded"
    assert repo.state == {"mode": "idle"}  # session closed


def test_legacy_keep_button_just_closes_session(monkeypatch):
    sent = []
    monkeypatch.setattr(tg, "_call", lambda m, p, s=None: {"ok": True})
    monkeypatch.setattr(tg, "_send_message", lambda cid, text, s=None, **kw: sent.append(text))
    repo = FakeRepo(state={"mode": "awaiting_edit", "draft_sk": "x"})

    tg.handle_update(_cb("k:2026-08-29:t:deadbeef"), repo=repo)

    assert sent == ["✅ Listo."]
    assert repo.state == {"mode": "idle"}


def test_handle_update_ignores_unknown_update_type():
    assert tg.handle_update({"edited_message": {"text": "hi"}})["handled"] is False


def test_handle_update_ignores_bad_callback_data(monkeypatch):
    assert tg.handle_update({"callback_query": {"id": "x", "data": "garbage"}})["handled"] is False


# --- message path ----------------------------------------------------


def _msg(text, chat_id=6891166315):
    return {"message": {"text": text, "chat": {"id": chat_id, "type": "private"}}}


def _fresh_state():
    from datetime import UTC, datetime

    return {
        "mode": "awaiting_edit",
        "draft_date": "2026-08-29",
        "draft_sk": "DRAFT#twitter#deadbeef",
        "platform": "twitter",
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def test_message_without_session_triggers_run_with_note(monkeypatch):
    monkeypatch.setattr(tg.config, "TELEGRAM_CHAT_ID", "6891166315")
    sent = []
    monkeypatch.setattr(tg, "_send_message", lambda cid, text, s=None, **kw: sent.append(text))
    calls = {}

    def fake_run(reason="unknown", user_note=""):
        calls.update(reason=reason, user_note=user_note)
        return {"drafts": 2, "errors": {}}

    monkeypatch.setattr("jobs.daily_job.run", fake_run)

    out = tg.handle_update(_msg("algo sobre el refactor de hoy"), repo=FakeRepo())

    assert out["action"] == "run"
    assert calls == {"reason": "telegram", "user_note": "algo sobre el refactor de hoy"}
    assert sent == ["✍️ Generando borradores…"]


def test_slash_run_triggers_run_without_note(monkeypatch):
    monkeypatch.setattr(tg.config, "TELEGRAM_CHAT_ID", "6891166315")
    monkeypatch.setattr(tg, "_send_message", lambda *a, **kw: None)
    calls = {}

    def fake_run(reason="unknown", user_note=""):
        calls["user_note"] = user_note
        return {"drafts": 1, "errors": {}}

    monkeypatch.setattr("jobs.daily_job.run", fake_run)
    tg.handle_update(_msg("/run"), repo=FakeRepo())
    assert calls == {"user_note": ""}


def test_start_command_sends_usage_and_does_not_run(monkeypatch):
    monkeypatch.setattr(tg.config, "TELEGRAM_CHAT_ID", "6891166315")
    sent = []
    monkeypatch.setattr(tg, "_send_message", lambda cid, text, s=None, **kw: sent.append(text))
    monkeypatch.setattr(
        "jobs.daily_job.run",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("run must not be called")),
    )

    out = tg.handle_update(_msg("/start"), repo=FakeRepo())
    assert out["action"] == "usage"
    assert len(sent) == 1 and "automática cada mañana" in sent[0]


def test_message_in_edit_session_revises_and_resends_with_buttons(monkeypatch):
    monkeypatch.setattr(tg.config, "TELEGRAM_CHAT_ID", "6891166315")
    sent = []
    monkeypatch.setattr(tg, "_send_message", _capture(sent))
    monkeypatch.setattr(
        "generation.llm_client.revise",
        lambda content, instructions, platform="twitter": f"[revisado: {instructions}]",
    )
    repo = FakeRepo(drafts=[_draft(status="approved")], state=_fresh_state())

    out = tg.handle_update(_msg("hacelo más corto y sacá el emoji"), repo=repo)

    assert out["action"] == "edit"
    assert repo.content_updates == [
        ("DRAFT#twitter#deadbeef", "[revisado: hacelo más corto y sacá el emoji]")
    ]
    text, kw = sent[0]
    assert text == "[revisado: hacelo más corto y sacá el emoji]"
    kb = kw["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["copy_text"]["text"] == "[revisado: hacelo más corto y sacá el emoji]"
    assert kb[1][0]["callback_data"] == "e:2026-08-29:t:deadbeef"
    assert repo.state["mode"] == "awaiting_edit"  # session stays open to iterate


def test_finalize_word_closes_session(monkeypatch):
    monkeypatch.setattr(tg.config, "TELEGRAM_CHAT_ID", "6891166315")
    sent = []
    monkeypatch.setattr(tg, "_send_message", lambda cid, text, s=None, **kw: sent.append(text))
    monkeypatch.setattr(
        "generation.llm_client.revise",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("revise must not run")),
    )
    repo = FakeRepo(
        drafts=[_draft(content="the final one", status="approved")],
        state=_fresh_state(),
    )

    out = tg.handle_update(_msg("listo"), repo=repo)

    assert out["action"] == "finalize"
    assert sent == ["✅ Listo, quedó guardado."]
    assert repo.state == {"mode": "idle"}  # session closed


def test_message_from_other_chat_is_ignored(monkeypatch):
    monkeypatch.setattr(tg.config, "TELEGRAM_CHAT_ID", "6891166315")
    monkeypatch.setattr(
        "jobs.daily_job.run",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("run must not be called")),
    )
    out = tg.handle_update(_msg("hola", chat_id=999999), repo=FakeRepo())
    assert out["handled"] is False
    assert out["why"] == "unauthorised chat"
