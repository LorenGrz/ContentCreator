"""Bedrock-backed draft generation via the Strands Agents SDK (same pattern as
``prioria``).

Split so the pure parts are unit-testable without AWS:
  * ``parse_model_json``  — tolerant JSON extraction from the model's reply
  * ``to_drafts``         — parsed dict -> ``Draft`` objects
  * ``generate``          — the one function that actually calls Bedrock
  * ``generate_drafts``   — full path, used by the daily job
"""

from __future__ import annotations

import json
import logging
import re

import config
from generation.prompts import (
    MAX_TWEETS,
    REVISE_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_revise_message,
    build_user_message,
)
from generation.significance import Significance
from storage.models import Draft, Signal

log = logging.getLogger(__name__)

TWEET_MAX_CHARS = 280
DEFAULT_TEMPERATURE = 0.6


def parse_model_json(raw: str) -> dict:
    """Pull the first ``{...}`` object out of the model's reply and parse it.
    Raises ``ValueError`` if nothing parseable is there."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in model output: {raw[:200]!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"model output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("model output JSON is not an object")
    return data


def _resolve_quote(entry: dict, valid_quote_urls: set[str]) -> tuple[str, str]:
    """Map an ``(kind, quote_url)`` pair off one tweet entry, falling back to
    ``("original", "")`` unless the model asked for a quote tweet *and* named a
    ``quote_url`` that matches an ingested ``source: x`` signal. Anchoring to
    real signal URLs stops a hallucinated link becoming a clickable button."""
    kind = str(entry.get("kind", "original")).strip().lower()
    quote_url = str(entry.get("quote_url", "")).strip()
    if kind == "quote_tweet" and quote_url in valid_quote_urls:
        return "quote_tweet", quote_url
    if kind == "quote_tweet":
        log.warning("quote_tweet dropped: quote_url %r not an ingested x signal", quote_url)
    return "original", ""


def _clean_tags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for tag in value:
        tag = str(tag).strip().lower().replace(" ", "-")
        if tag and tag not in out:
            out.append(tag)
    return out[:3]


def to_drafts(
    parsed: dict,
    *,
    target_date: str,
    signal_keys: list[str],
    linkedin_keys: list[str] | None = None,
    telegram_chat_id: str = "",
    quote_urls: set[str] | None = None,
    linkedin_high_signal: bool = False,
) -> list[Draft]:
    drafts: list[Draft] = []
    valid_quote_urls = quote_urls or set()

    tweets = parsed.get("tweets") or []
    if not isinstance(tweets, list):
        tweets = []
    for entry in tweets[:MAX_TWEETS]:
        content = str((entry or {}).get("content", "")).strip()
        if not content:
            continue
        if len(content) > TWEET_MAX_CHARS:
            log.warning(
                "tweet over %d chars (%d); keeping for manual edit",
                TWEET_MAX_CHARS,
                len(content),
            )
        kind, quote_url = _resolve_quote((entry or {}), valid_quote_urls)
        drafts.append(
            Draft(
                platform="twitter",
                content=content,
                target_date=target_date,
                kind=kind,
                quote_url=quote_url,
                topic_tags=_clean_tags((entry or {}).get("topic_tags")),
                source_signal_keys=list(signal_keys),
                telegram_chat_id=telegram_chat_id,
            )
        )

    li = parsed.get("linkedin")
    if isinstance(li, dict):
        content = str(li.get("content", "")).strip()
        if content:
            drafts.append(
                Draft(
                    platform="linkedin",
                    content=content,
                    target_date=target_date,
                    high_signal=linkedin_high_signal,
                    topic_tags=_clean_tags(li.get("topic_tags")),
                    source_signal_keys=list(linkedin_keys or signal_keys),
                    telegram_chat_id=telegram_chat_id,
                )
            )

    return drafts


def generate(
    user_message: str,
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    model_id: str | None = None,
) -> dict:
    """Call Bedrock through a Strands agent and return the parsed JSON dict."""
    from strands import Agent
    from strands.models import BedrockModel

    model = BedrockModel(model_id=model_id or config.BEDROCK_MODEL_ID, temperature=temperature)
    agent = Agent(model=model, system_prompt=SYSTEM_PROMPT)
    raw = str(agent(user_message))
    return parse_model_json(raw)


def revise(content: str, instructions: str, *, platform: str, model_id: str | None = None) -> str:
    """Rewrite one approved draft per Lorenzo's instructions. Returns the plain
    final text, ready to paste — no JSON, no wrapper."""
    from strands import Agent
    from strands.models import BedrockModel

    model = BedrockModel(model_id=model_id or config.BEDROCK_MODEL_ID, temperature=0.4)
    agent = Agent(model=model, system_prompt=REVISE_SYSTEM_PROMPT)
    message = build_revise_message(content=content, instructions=instructions, platform=platform)
    text = str(agent(message)).strip().strip('"').strip()
    if platform == "twitter" and len(text) > TWEET_MAX_CHARS:
        log.warning("revised tweet is %d chars (> %d)", len(text), TWEET_MAX_CHARS)
    return text


def generate_drafts(
    *,
    signals: list[Signal],
    recent_topics: list[str],
    target_date: str,
    significance: Significance,
    telegram_chat_id: str = "",
    user_note: str = "",
    linkedin_always: bool = False,
) -> list[Draft]:
    """Build the prompt, call the model, and map the reply to ``Draft`` rows
    (status ``pending``, not yet stored). ``user_note`` is free text Lorenzo
    sent to the bot to steer this run. ``linkedin_always`` forces at least one
    LinkedIn draft even when the significance gate didn't fire."""
    want_linkedin = linkedin_always or significance.linkedin_worthy
    user_message = build_user_message(
        signals=signals,
        recent_topics=recent_topics,
        target_date=target_date,
        want_linkedin=want_linkedin,
        linkedin_high_signal=significance.linkedin_worthy,
        significance_reasons=significance.reasons,
        user_note=user_note,
    )
    parsed = generate(user_message)
    return to_drafts(
        parsed,
        target_date=target_date,
        signal_keys=[s.sk for s in signals],
        linkedin_keys=significance.highlight_keys or None,
        linkedin_high_signal=significance.linkedin_worthy,
        telegram_chat_id=telegram_chat_id,
        quote_urls={s.url for s in signals if s.source == "x" and s.url},
    )
