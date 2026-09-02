"""Single Lambda entrypoint.

Two kinds of events land here:

* **EventBridge Scheduler** invocations — a bare JSON payload with no
  ``requestContext``. These run the daily job directly.
* **API Gateway (HTTP API) proxy** events — handed to FastAPI via Mangum.
"""

from __future__ import annotations

import logging

import config

logging.getLogger().setLevel(config.LOG_LEVEL)

from mangum import Mangum  # noqa: E402

from app import app  # noqa: E402

_asgi_handler = Mangum(app, lifespan="off")


def _is_http_event(event: dict) -> bool:
    return isinstance(event, dict) and (
        "requestContext" in event or "rawPath" in event or "httpMethod" in event
    )


def handler(event, context):
    if _is_http_event(event):
        return _asgi_handler(event, context)

    # Scheduled / manual invoke -> run the daily job.
    from jobs.daily_job import run

    return run(reason=f"schedule:{(event or {}).get('source', 'unknown')}")
