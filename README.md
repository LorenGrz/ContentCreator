# content-creator

Serverless bot that reads **real GitHub activity** (and optionally Google
Calendar), drafts short **Twitter** posts and a **LinkedIn** post, stores
them, and sends them to a **Telegram** chat with *Approve* / *Discard*
buttons.

Every day it also pulls a few Hacker News stories, so at least one tweet
always riffs on something from the tech world — even on days with GitHub
activity (`AlwaysTechNews`, on by default).

There's also **at least one LinkedIn draft every run** (`LinkedinAlways`, on
by default): a rule-based significance gate (merged PR, new repo, milestone
calendar event) decides whether it's framed as a substantial post — labelled
`💼 LinkedIn · ⭐ muy relevante` in Telegram — or a short honest reflection on
the day. Set `LinkedinAlways=false` to get the LinkedIn draft only on
high-signal days.

It can also follow a few **X / Twitter accounts** through a Nitter RSS bridge
(`XEnabled`, **off by default** — Nitter instances are flaky). When a draft
rides on one of those tweets, the generator proposes a **quote tweet** —
Lorenzo's short take plus a link to the original — instead of an original
post. In Telegram that draft shows a `🔁 Quote tweet` label, an **✍️ Abrir en
X** button that opens the compose window as a quote (`text` + `url`), and a
`🔗 Ver tweet original` link. The model may only quote a URL that matches a
tweet actually ingested this run; anything else is downgraded to an original.

It runs two ways:

- **once a day** on a schedule (EventBridge), and
- **on demand** — send the bot a Telegram message and it drafts now; the
  message text is passed to the model as steering (`user_note`), so
  "escribí algo sobre el refactor de hoy" works. `/start` / `/help` print
  usage; `/run` triggers a plain run with no note.

**No auto-posting.** The bot only prepares drafts; publishing is manual.

### The review flow (Telegram)

1. A draft arrives with **✅ Aprobar** / **🗑 Descartar**.
2. **Aprobar** → the draft comes back on its own message with **📋 Copiar**
   (clipboard), **✍️ Abrir en X** (opens the X compose window with the text
   pre-filled) and **✍️ Editar**.
3. **Editar** → send a plain-language change ("más corto", "sacá el emoji",
   "sumá el link del repo"); Bedrock rewrites it and the new version comes
   back with the same buttons. Repeat as needed; `listo` / `ok` closes it.
4. Copy or "Abrir en X", review, and post it yourself. Nothing is posted
   automatically.

(`📋 Copiar` uses Telegram's `copy_text` button, capped at 256 chars; a
longer tweet just gets "Abrir en X" plus the selectable message text.)

## Stack

- **Python 3.13**, AWS Lambda `arm64`, single monolithic function
- **FastAPI + Mangum** for the HTTP surface (`handler.py` routes EventBridge
  Scheduler events straight to the daily job, everything else to FastAPI)
- **DynamoDB** — one table, `PAY_PER_REQUEST`, generic `pk`/`sk`, no GSI
- **Amazon Bedrock** (`strands-agents`) for draft generation — same pattern as
  `prioria`
- **SSM Parameter Store** (SecureString) for secrets — not Secrets Manager
  (that would cost ~$0.40/secret/month)
- **SAM** for packaging/deploy; no Docker for local dev (`moto` for storage
  tests, real AWS for Bedrock/deploy iteration)

## Layout

```
template.yaml            SAM: table, function, HTTP API, daily schedule, scoped IAM
samconfig.toml
mise.toml                pins python 3.13 (so `sam build` packages the right wheels)
requirements-dev.txt     src/requirements.txt + pytest, moto, ruff, uvicorn
src/
  requirements.txt       Lambda runtime deps (must live in the CodeUri dir for SAM)
  handler.py             Lambda entrypoint: schedule -> daily_job, HTTP -> Mangum(app)
  app.py                 FastAPI: /health, /drafts, /run, /telegram/webhook
  config.py              env vars, constants, SSM parameter reader
  timeutils.py           local-day <-> UTC/RFC3339 conversions
  jobs/daily_job.py      orchestrator: ingest -> dedup -> significance -> generate -> store -> notify
  ingestion/
    github_client.py     commits / PRs / new repos from the events feed             [done]
    calendar_client.py   Google Calendar events, OAuth2 refresh-token auth          [done]
    hackernews_client.py top stories, no-auth; always-on tech-news source           [done]
    x_client.py          followed X accounts via Nitter RSS; opt-in (X_ENABLED)      [done]
  generation/
    voice_examples.py    hardcoded few-shot voice bank (REPLACE the placeholders)  [done]
    prompts.py           system prompt + per-day user message builder              [done]
    significance.py      rule-based "is today a high-signal LinkedIn day?"          [done]
    llm_client.py        Strands Agent + Bedrock; parse reply -> Draft rows         [done]
  delivery/telegram_client.py   send drafts + dispatch taps / on-demand messages   [done]
  storage/
    models.py            Signal, Draft dataclasses + key scheme
    repository.py        DynamoDB access (put/query/idempotent status update)
scripts/
  google_oauth_bootstrap.py   one-time local flow to mint a Calendar refresh token [done]
tests/
  test_repository.py       storage round-trips against moto
  test_app_health.py       FastAPI smoke
  test_github_client.py     events -> signals, stale/noise dropped, token from SSM
  test_calendar_client.py   event mapping, declined skip, day-window params
  test_hackernews_client.py story filtering + limit
  test_x_client.py         Nitter RSS -> signals, RT/stale drop, instance fallback
  test_significance.py      LinkedIn gate: merged PR / new repo / keyword event
  test_prompts.py           prompt carries signals, recent topics, reflection mode
  test_llm_client.py        tolerant JSON parse, reply -> Draft mapping, wiring
  test_telegram_client.py   send payload + callback -> idempotent status flip
```

## Data model (single table `content-creator`)

| Record | pk | sk |
| --- | --- | --- |
| Signal (raw activity) | `DATE#<yyyy-mm-dd>` | `SIGNAL#<source>#<external_id>` |
| Draft (generated post) | `DATE#<yyyy-mm-dd>` | `DRAFT#<platform>#<uuid>` |
| Chat state (edit session) | `CHAT#<chat_id>` | `STATE` |

The chat-state row tracks an open Telegram *edit session* (`mode`,
`draft_sk`, `draft_date`, `updated_at`); "closing" it overwrites `mode` with
`idle` rather than deleting (the role has no `DeleteItem`).

Partitioned by the **activity/target date** (local tz), not ingest time, so a
day's signals and drafts live in one partition. Topic dedup = query the last
~14 `DATE#` partitions for existing `Draft.topic_tags` and pass them to the
prompt as "angles already covered, don't repeat".

## Commands

```bash
# one-time: 3.13 venv (matches the Lambda runtime; `mise install` provides 3.13)
mise install
"$(mise where python)/bin/python" -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

.venv/bin/python -m pytest -q          # tests (no AWS, no Docker)
.venv/bin/ruff check .                 # lint
.venv/bin/uvicorn app:app --reload --app-dir src   # run HTTP surface locally

sam validate --lint
sam build                              # no --use-container; needs python3.13 on PATH (mise.toml)
sam deploy --parameter-overrides \
  TelegramWebhookSecret=<random> TelegramChatId=<your-chat-id>
```

### Secrets (create before first real run)

GitHub-only mode (`CalendarEnabled=false`, the default) needs just two:

```bash
aws ssm put-parameter --type SecureString --name /content-creator/github-token       --value ...
aws ssm put-parameter --type SecureString --name /content-creator/telegram-bot-token --value ...
```

To follow X accounts, no secret is needed — just deploy with
`XEnabled=true XHandles=aws,vercel,...` (optionally override `XNitterBases`
with instances you trust and `XLimit`).

To also ingest Google Calendar, add the three below (the last comes from
`scripts/google_oauth_bootstrap.py`) and deploy with `CalendarEnabled=true`:

```bash
aws ssm put-parameter --type SecureString --name /content-creator/google-client-id     --value ...
aws ssm put-parameter --type SecureString --name /content-creator/google-client-secret --value ...
aws ssm put-parameter --type SecureString --name /content-creator/google-refresh-token --value ...
```

### Wire up Telegram

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d url="<ApiBaseUrl>/telegram/webhook" \
  -d secret_token="<TelegramWebhookSecret>"
```

## Architecture decisions

- **One Lambda, not a fleet.** Single-user, ~1 scheduled run/day plus a few
  webhook calls. Splitting would add cold starts and IAM surface for nothing.
- **No GSI.** Every read is a `Query` on one `DATE#` partition or a short loop
  over recent dates. A topic-tag GSI would be premature optimisation.
- **SSM over Secrets Manager** — cost. Standard parameters are free.
- **Idempotent decision write.** `update_draft_status` only flips a still
  `pending` draft (conditional write), so a double-tap on a Telegram button
  can't overwrite the first decision.
- **`raw` signal payloads truncated** to ~4 KB before storage.
- **Least-privilege IAM**: DynamoDB actions scoped to the exact table ARN, SSM
  to `/content-creator/*`, Bedrock to the Claude Haiku model family + the
  configured inference profile.

## Milestones

1. **Scaffold + storage** — done. Structure, `config`, `handler`, `app`
   (`/health`), `storage/` with `moto` tests, `template.yaml`.
2. _(folded into 1)_
3. **Ingestion** — done. `github_client` (events feed -> commit/pr/new_repo
   signals), `calendar_client` (OAuth2 refresh token, declined events skipped;
   gated by `CALENDAR_ENABLED`, off by default), `hackernews_client` (no-auth
   fallback), `x_client` (Nitter RSS -> `tweet` signals with canonical
   `twitter.com` URLs; gated by `X_ENABLED`, off by default; retweets and
   out-of-window tweets dropped; tries each `X_NITTER_BASES` instance in
   order). HTTP mocked in tests.
4. **Google OAuth bootstrap** — done. `scripts/google_oauth_bootstrap.py`
   runs the desktop OAuth flow once and writes client id / secret / refresh
   token to SSM (`--dry-run` to inspect first). Only needed if you turn
   Calendar on.
5. **Generation** — done. `voice_examples` (hardcoded few-shot, **placeholders
   to replace by hand**), `prompts` (system prompt + JSON output contract +
   per-day user message), `significance` (rule-based LinkedIn gate),
   `llm_client` (Strands + Bedrock, tolerant JSON parse, reply -> `Draft`).
   Dedup reuses `Repository.recent_topic_tags`.
6. **daily_job** — done. ingest -> persist signals -> `significance.evaluate`
   -> `recent_topic_tags` -> `generate_drafts` -> persist drafts -> Telegram.
   Each stage's failure is captured in `errors`, not fatal.
7. **Telegram delivery** — done. `send_draft` posts with ✅/🗑 buttons.
   `handle_update` dispatches:
   - `callback_query` `a` — mark `approved`, reply with the text on its own
     message + `📋 Copiar` / `✍️ Abrir en X` / `✍️ Editar` (`_result_keyboard`).
   - `callback_query` `d` — mark `discarded`, close any edit session.
   - `callback_query` `e` — open the edit loop.
   - `callback_query` `k` — legacy "Dejalo así" on old messages: just closes.
   - `message` from the configured chat — if an edit loop is open, the text is
     a rewrite instruction → `llm_client.revise` rewrites the draft, saves it,
     re-sends with the buttons, loop stays open (`listo`/`ok`/`dale` closes);
     otherwise runs the job on demand with the text as `user_note`.
   Callback data `<a|d|e|k>:<date>:<t|l>:<draft_id>` (64-byte limit). Messages
   from other chat ids are ignored.
8. **Full `template.yaml`** — schedule + HTTP API + scoped IAM + 14-day log
   retention + outputs. No change needed after 7.
9. **README polish** + verification runbook — this file.

### Known limitation

The on-demand run and the edit rewrite both call Bedrock synchronously inside
the webhook request. A few seconds with Haiku, but if it ever exceeds the API
Gateway 30s integration timeout, Telegram retries the webhook and you get a
duplicate batch (or a duplicate edit). If that shows up in practice, move the
work to an async self-invoke (`lambda:InvokeFunction` on itself + immediate
200).

### Before the first real run

- Replace the `TODO: reemplazar` placeholders in
  `src/generation/voice_examples.py` with real posts in your voice
  (`voice_examples.has_real_examples()` returns `True` once done).
- Create the SSM parameters (see Secrets above) — two for GitHub-only mode.
- `sam deploy` (Calendar off by default), then point the Telegram webhook at
  the `ApiBaseUrl` output.
- Request Bedrock model access for the Haiku model in the deploy region.
- Google Calendar is optional and off by default; enable it later with the
  three `google-*` params + `CalendarEnabled=true`.

## Deferred (explicitly out of MVP)

- Google Photos (blocked by the Apr-2025 Library API restriction; Picker API
  needs manual per-session interaction).
- Voice bank via embeddings/RAG — starts hardcoded.
- Engagement tracking via the X API.
- Auto-publishing to X / LinkedIn.

## Verification (current state)

```
.venv/bin/python -m pytest -q   # 49 passed
.venv/bin/ruff check .          # clean
sam validate --lint             # valid SAM template
sam build                       # Build Succeeded (arm64 wheels)
```

**Deployed and verified end-to-end** (stack `content-creator-dev`, us-east-1):
`GET /health` → 200; a scheduled run drove `daily_job` live —
`by_source {github: 6, hackernews: 4}` → Bedrock → `drafts: 3, sent: 3,
errors: {}` (one draft riffs on an HN story). Approve → text re-sent with
`copy_text` + X-intent + Editar buttons (Telegram accepted the payload);
an edit instruction ran `llm_client.revise` and rewrote the stored draft.
HTTP API uses the
`$default` stage so the Lambda sees `/health`, not `/prod/health`.

Manual re-check:

```bash
aws lambda invoke --function-name content-creator --payload '{"source":"aws.scheduler"}' out.json
#   -> expect Signal + Draft items in DynamoDB and a Telegram message with buttons
# tap Approve/Discard, then confirm the Draft's `status` changed in DynamoDB
```

Still generic until the voice bank is filled: `src/generation/voice_examples.py`
placeholders. `boto3` is bundled although the Lambda runtime ships it; kept for
local parity, drop from `src/requirements.txt` if package size bites.
