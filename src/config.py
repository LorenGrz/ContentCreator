"""Central configuration: environment variables, constants, and small helpers
for reading secrets from SSM Parameter Store.

Everything here is import-safe with no side effects so tests can import any
module without AWS credentials. AWS clients are created lazily on first use.
"""

from __future__ import annotations

import functools
import os

# --- Core resources -------------------------------------------------------

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Single DynamoDB table (generic pk/sk). Defaults match the SAM stack.
TABLE_NAME = os.environ.get("TABLE_NAME", "content-creator")

# Bedrock model for draft generation — same family as `prioria`.
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

# --- SSM Parameter Store -------------------------------------------------

# All secrets live under this prefix as SecureString parameters (free tier;
# Secrets Manager would cost ~$0.40/secret/month). See README.
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/content-creator")

PARAM_GITHUB_TOKEN = f"{SSM_PREFIX}/github-token"
PARAM_GOOGLE_CLIENT_ID = f"{SSM_PREFIX}/google-client-id"
PARAM_GOOGLE_CLIENT_SECRET = f"{SSM_PREFIX}/google-client-secret"
PARAM_GOOGLE_REFRESH_TOKEN = f"{SSM_PREFIX}/google-refresh-token"
PARAM_TELEGRAM_BOT_TOKEN = f"{SSM_PREFIX}/telegram-bot-token"

# --- Behaviour tuning --------------------------------------------------

# IANA timezone used to bucket activity into "days" and to schedule delivery.
LOCAL_TZ = os.environ.get("LOCAL_TZ", "America/Argentina/Buenos_Aires")

# How far back to look when collecting recent draft topics for dedup.
DEDUP_LOOKBACK_DAYS = int(os.environ.get("DEDUP_LOOKBACK_DAYS", "14"))

# Activity ingestion window (hours before "now") for GitHub / Calendar.
INGEST_LOOKBACK_HOURS = int(os.environ.get("INGEST_LOOKBACK_HOURS", "36"))

GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "LorenGrz")

# Google Calendar is an optional source. Disable it (CALENDAR_ENABLED=false)
# when there's no Google Cloud OAuth client to back it — the daily job then
# runs on GitHub alone (plus the Hacker News fallback).
CALENDAR_ENABLED = os.environ.get("CALENDAR_ENABLED", "true").strip().lower() == "true"

# Always pull a few Hacker News stories, even when there IS personal activity,
# so there's always at least one "mundo tech" tweet. Set false to make Hacker
# News a pure no-activity fallback again.
ALWAYS_TECH_NEWS = os.environ.get("ALWAYS_TECH_NEWS", "true").strip().lower() == "true"
HACKERNEWS_LIMIT = int(os.environ.get("HACKERNEWS_LIMIT", "4"))

# X / Twitter is an optional news source: a handful of accounts read through a
# Nitter RSS bridge (no API key, no cost). Off by default — Nitter instances
# are flaky, so it's opt-in. When a draft rides on one of these tweets the
# generator proposes a *quote tweet* (Lorenzo's take + the original's link)
# instead of an original post.
X_ENABLED = os.environ.get("X_ENABLED", "false").strip().lower() == "true"
X_HANDLES = [
    h.strip().lstrip("@")
    for h in os.environ.get("X_HANDLES", "").split(",")
    if h.strip()
]
# Tried in order until one answers; first working instance wins per run.
X_NITTER_BASES = [
    b.strip().rstrip("/")
    for b in os.environ.get(
        "X_NITTER_BASES", "https://nitter.net,https://nitter.poast.org"
    ).split(",")
    if b.strip()
]
X_LIMIT = int(os.environ.get("X_LIMIT", "5"))
X_INGEST_LOOKBACK_HOURS = int(os.environ.get("X_INGEST_LOOKBACK_HOURS", "36"))

# Telegram chat that receives the drafts (the user's own DM with the bot).
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Shared secret echoed by Telegram in the X-Telegram-Bot-Api-Secret-Token
# header on every webhook call; rejects forged callbacks.
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


# --- SSM helper -------------------------------------------------------


@functools.lru_cache(maxsize=32)
def get_parameter(name: str, *, decrypt: bool = True) -> str:
    """Fetch a single SSM parameter value. Cached for the lifetime of a warm
    Lambda container. Raises if the parameter does not exist."""
    import boto3

    client = boto3.client("ssm", region_name=AWS_REGION)
    resp = client.get_parameter(Name=name, WithDecryption=decrypt)
    return resp["Parameter"]["Value"]
