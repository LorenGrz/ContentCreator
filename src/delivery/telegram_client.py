"""Telegram delivery.

Outbound: ``send_draft`` posts a draft with *Aprobar* / *Descartar* buttons;
``send_text`` sends a plain line.

Flow it implements: the bot posts a draft with **Aprobar** / **Descartar**.
Tap Aprobar and it replies with the text on its own message plus **📋 Copiar**
(clipboard), **✍️ Abrir en X** (pre-filled compose window) and **✍️ Editar**.
Editar opens a rewrite loop — send an instruction, Bedrock rewrites the draft,
the new version comes back with the same buttons; "listo" closes the loop.
Nothing is ever posted automatically.

Inbound: ``handle_update`` dispatches on update type:

* ``callback_query`` — ``a`` approve (→ result message + buttons), ``d``
  discard, ``e`` open the edit loop, ``k`` legacy "Dejalo así" (just closes).
* ``message`` with text, **from the configured chat only**:
  - edit loop open — text is a rewrite instruction; otherwise
  - run the daily job now with the text as ``user_note``.
  ``/start`` / ``/help`` print usage; ``/run`` runs with no note.

``app.py`` validates the ``X-Telegram-Bot-Api-Secret-Token`` header first, so
forged updates never reach here. Callback data is
``<a|d|e|k>:<date>:<t|l>:<draft_id>`` (fits Telegram's 64-byte limit).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from urllib.parse import quote

import requests

import config

log = logging.getLogger(__name__)

_API = "https://api.telegram.org"
_TIMEOUT = 10
_PLATFORM_CODE = {"twitter": "t", "linkedin": "l"}
_CODE_PLATFORM = {v: k for k, v in _PLATFORM_CODE.items()}

# How long an edit session stays open after the last activity.
_EDIT_TTL_SECONDS = 2 * 3600
# Text that closes an edit session, leaving the draft as-is.
_FINALIZE_WORDS = {
    "ok", "okay", "listo", "dale", "así está", "asi esta", "así está bien",
    "asi esta bien", "está bien", "esta bien", "dejalo así", "dejalo asi",
    "perfecto", "va así", "va asi",
}

_USAGE = (
    "Escribime qué querés que borronee y lo genero al toque "
    '(ej: "algo sobre el refactor de storage de hoy"). '
    "Sin texto, uso tu actividad de GitHub del día. "
    "Igual te llega una tanda automática cada mañana."
)


def _token() -> str:
    return config.get_parameter(config.PARAM_TELEGRAM_BOT_TOKEN)


def _call(method: str, payload: dict, session: requests.Session | None = None) -> dict:
    http = session or requests
    resp = http.post(f"{_API}/bot{_token()}/{method}", json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _send_message(
    chat_id: str,
    text: str,
    session: requests.Session | None = None,
    *,
    reply_markup: dict | None = None,
) -> dict:
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _call("sendMessage", payload, session)


def send_text(
    text: str,
    *,
    chat_id: str | None = None,
    session: requests.Session | None = None,
) -> None:
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    if not chat_id:
        log.warning("TELEGRAM_CHAT_ID not set; dropping message %r", text[:60])
        return
    _send_message(str(chat_id), text, session)


def _is_quote(draft) -> bool:
    return getattr(draft, "kind", "original") == "quote_tweet" and bool(
        getattr(draft, "quote_url", "")
    )


def _format(draft) -> str:
    if draft.platform != "twitter":
        label = "💼 LinkedIn"
        if getattr(draft, "high_signal", False):
            label += " · ⭐ muy relevante"
    elif _is_quote(draft):
        label = "🔁 Quote tweet"
    else:
        label = "🐦 Twitter"
    tags = f"\n\n<i>{', '.join(draft.topic_tags)}</i>" if draft.topic_tags else ""
    body = draft.content.replace("<", "&lt;").replace(">", "&gt;")
    quoting = f"\n\n<i>citando: {draft.quote_url}</i>" if _is_quote(draft) else ""
    return f"<b>{label}</b> — {draft.target_date}\n\n{body}{quoting}{tags}"


def _suffix(draft) -> str:
    return f"{draft.target_date}:{_PLATFORM_CODE.get(draft.platform, 't')}:{draft.draft_id}"


def send_draft(
    draft,
    *,
    chat_id: str | None = None,
    session: requests.Session | None = None,
) -> int | None:
    """Post one draft with Aprobar / Descartar buttons. Returns the Telegram
    message id (store it on the draft) or ``None`` if no chat is configured."""
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    if not chat_id:
        log.warning("TELEGRAM_CHAT_ID not set; skipping send for %s", draft.sk)
        return None

    suffix = _suffix(draft)
    resp = _call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": _format(draft),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "✅ Aprobar", "callback_data": f"a:{suffix}"},
                        {"text": "🗑 Descartar", "callback_data": f"d:{suffix}"},
                    ]
                ]
            },
        },
        session,
    )
    return (resp.get("result") or {}).get("message_id")


# --------------------------------------------------------------------------


def handle_update(update: dict, *, repo=None, session: requests.Session | None = None) -> dict:
    if update.get("callback_query"):
        return _handle_callback(update["callback_query"], repo=repo, session=session)
    if update.get("message"):
        return _handle_message(update["message"], repo=repo, session=session)
    return {"ok": True, "handled": False, "why": "unsupported update type"}


def _get_repo(repo):
    if repo is not None:
        return repo
    from storage.repository import Repository

    return Repository()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _edit_session(repo, chat_id: str) -> dict | None:
    """Return the open edit-session state for this chat, or ``None`` if there
    is none / it's stale."""
    state = repo.get_chat_state(chat_id)
    if not state or state.get("mode") != "awaiting_edit":
        return None
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(state["updated_at"])).total_seconds()
    except (KeyError, ValueError):
        return None
    return state if 0 <= age <= _EDIT_TTL_SECONDS else None


_COPY_MAX = 256  # Telegram's cap on copy_text.text


def _result_keyboard(draft) -> dict:
    """Buttons on an approved / revised draft: copy it, open a pre-filled
    compose window, or reopen the edit loop."""
    row = []
    if len(draft.content) <= _COPY_MAX:
        row.append({"text": "📋 Copiar", "copy_text": {"text": draft.content}})
    encoded = quote(draft.content, safe="")
    if draft.platform == "twitter" and _is_quote(draft):
        # text + url of a tweet -> X's compose window opens as a quote tweet.
        quoted = quote(draft.quote_url, safe="")
        row.append(
            {"text": "✍️ Abrir en X",
             "url": f"https://twitter.com/intent/tweet?text={encoded}&url={quoted}"}
        )
    elif draft.platform == "twitter":
        row.append({"text": "✍️ Abrir en X", "url": f"https://twitter.com/intent/tweet?text={encoded}"})
    else:
        row.append(
            {"text": "💼 Abrir LinkedIn",
             "url": f"https://www.linkedin.com/feed/?shareActive=true&text={encoded}"}
        )
    rows = [row] if row else []
    if _is_quote(draft):
        rows.append([{"text": "🔗 Ver tweet original", "url": draft.quote_url}])
    rows.append([{"text": "✍️ Editar", "callback_data": f"e:{_suffix(draft)}"}])
    return {"inline_keyboard": rows}


def _send_result(chat_id: str, draft, session) -> None:
    """The draft on its own message, ready to copy, with the action buttons."""
    _send_message(str(chat_id), draft.content, session, reply_markup=_result_keyboard(draft))


def _handle_message(message: dict, *, repo=None, session: requests.Session | None = None) -> dict:
    text = (message.get("text") or "").strip()
    chat_id = str((message.get("chat") or {}).get("id", ""))

    if not config.TELEGRAM_CHAT_ID or chat_id != str(config.TELEGRAM_CHAT_ID):
        log.warning("ignoring message from unauthorised chat %s", chat_id)
        return {"ok": True, "handled": False, "why": "unauthorised chat"}

    repo = _get_repo(repo)
    state = _edit_session(repo, chat_id)

    # --- inside an edit session -------------------------------------------
    if state:
        if not text or text.lower() in _FINALIZE_WORDS:
            repo.clear_chat_state(chat_id)
            _send_message(chat_id, "✅ Listo, quedó guardado.", session)
            return {"ok": True, "handled": True, "action": "finalize"}

        draft = repo.get_draft(state["draft_date"], state["draft_sk"])
        if not draft:
            repo.clear_chat_state(chat_id)
            _send_message(chat_id, "No encuentro ese borrador; empezá de nuevo.", session)
            return {"ok": True, "handled": True, "action": "edit", "found": False}

        from generation.llm_client import revise

        new_text = revise(draft.content, text, platform=draft.platform)
        repo.update_draft_content(state["draft_date"], state["draft_sk"], new_text, _now())
        repo.set_chat_state(
            chat_id,
            mode="awaiting_edit",
            draft_date=state["draft_date"],
            draft_sk=state["draft_sk"],
            platform=draft.platform,
            updated_at=_now(),
        )
        draft.content = new_text
        _send_result(chat_id, draft, session)
        _send_message(chat_id, 'Otro ajuste, o "listo" para cerrar.', session)
        return {"ok": True, "handled": True, "action": "edit", "found": True}

    # --- no session: generate --------------------------------------------
    if not text or text.lower() in ("/start", "/help"):
        _send_message(chat_id, _USAGE, session)
        return {"ok": True, "handled": True, "action": "usage"}

    note = "" if text.lower() in ("/run", "/generar") else text
    _send_message(chat_id, "✍️ Generando borradores…", session)

    from jobs.daily_job import run

    result = run(reason="telegram", user_note=note)
    if result.get("errors"):
        _send_message(chat_id, f"⚠️ Terminé con errores: {result['errors']}", session)
    elif not result.get("drafts"):
        _send_message(chat_id, "No encontré nada para borronear esta vez.", session)

    return {"ok": True, "handled": True, "action": "run", "result": result}


def _safe(fn) -> None:
    """Run a Telegram side-effect, swallowing any error (already logged)."""
    try:
        fn()
    except Exception:  # noqa: BLE001
        log.warning("telegram side-effect failed", exc_info=True)


def _strip_buttons(cq_message: dict, session) -> None:
    chat = (cq_message.get("chat") or {}).get("id")
    mid = cq_message.get("message_id")
    if chat and mid:
        _call(
            "editMessageReplyMarkup",
            {"chat_id": chat, "message_id": mid, "reply_markup": {"inline_keyboard": []}},
            session,
        )


def _handle_callback(cq: dict, *, repo=None, session: requests.Session | None = None) -> dict:
    parts = cq.get("data", "").split(":", 3)
    if len(parts) != 4 or parts[0] not in ("a", "d", "e", "k"):
        log.warning("unrecognised callback data: %r", cq.get("data"))
        return {"ok": True, "handled": False, "why": "bad callback data"}

    action, target_date, pcode, draft_id = parts
    platform = _CODE_PLATFORM.get(pcode, "twitter")
    sk = f"DRAFT#{platform}#{draft_id}"
    cq_message = cq.get("message") or {}
    chat_id = str((cq_message.get("chat") or {}).get("id", "")) or config.TELEGRAM_CHAT_ID
    repo = _get_repo(repo)

    ack = "Listo"
    strip = action in ("a", "d")  # the Aprobar/Descartar row is spent; keep result-msg buttons
    followups: list[dict] = []
    result = {"ok": True, "handled": True, "sk": sk, "action": action}

    if action == "a":
        draft = repo.update_draft_status(target_date, sk, "approved", _now())
        status = draft.status if draft else "approved"
        ack = f"Marcado como {status}"
        result["status"] = status
        if draft and draft.status == "approved":
            # The ready-to-paste text + Copiar / Abrir en X / Editar buttons.
            followups.append({"text": draft.content, "reply_markup": _result_keyboard(draft)})
        elif draft:
            followups.append({"text": f"Ese borrador ya estaba {draft.status}."})

    elif action == "d":
        draft = repo.update_draft_status(target_date, sk, "discarded", _now())
        result["status"] = draft.status if draft else "discarded"
        ack = f"Marcado como {result['status']}"
        repo.clear_chat_state(str(chat_id))
        followups.append({"text": "🗑 Descartado."})

    elif action == "e":  # open the edit loop on demand
        draft = repo.get_draft(target_date, sk)
        if not draft:
            ack = "No lo encuentro"
            followups.append({"text": "No encuentro ese borrador."})
        else:
            repo.set_chat_state(
                str(chat_id),
                mode="awaiting_edit",
                draft_date=target_date,
                draft_sk=sk,
                platform=platform,
                updated_at=_now(),
            )
            ack = "Editando"
            followups.append(
                {"text": '✍️ Mandame el ajuste (tono, largo, agregá o sacá algo). '
                         'Cuando estés, escribí "listo".'}
            )

    else:  # "k" — legacy "Dejalo así" button on older messages
        repo.clear_chat_state(str(chat_id))
        followups.append({"text": "✅ Listo."})

    # Telegram side-effects — the DB change is already done, so each is
    # isolated: one failing (e.g. a stale callback id) must not skip the rest
    # or 500 the webhook.
    _safe(lambda: _call(
        "answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": ack}, session
    ))
    if strip:
        _safe(lambda: _strip_buttons(cq_message, session))
    for fp in followups:
        _safe(lambda fp=fp: _send_message(
            str(chat_id), fp["text"], session, reply_markup=fp.get("reply_markup")
        ))

    log.info("callback %s on %s", action, sk)
    return result
