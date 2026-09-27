"""Ingestion of trending AI papers and open-weights models from Hugging Face."""

from __future__ import annotations

import hashlib
import logging

import requests

import config
from storage.models import Signal
from timeutils import today_local_iso

log = logging.getLogger(__name__)

_TIMEOUT = 10
_PAPERS_URL = "https://huggingface.co/api/daily_papers"
_MODELS_URL = "https://huggingface.co/api/models"


def fetch_huggingface_signals(
    *,
    limit: int | None = None,
    session: requests.Session | None = None,
) -> list[Signal]:
    """Fetch top daily AI papers and trending open-source models from Hugging Face."""
    max_items = limit if limit is not None else config.HUGGINGFACE_LIMIT
    if max_items <= 0:
        return []

    http = session or requests.Session()
    headers = {"User-Agent": "ContentCreatorBot/1.0"}
    day = today_local_iso()
    signals: list[Signal] = []

    # 1. Daily Papers
    try:
        resp = http.get(_PAPERS_URL, headers=headers, timeout=_TIMEOUT)
        if resp.ok:
            papers_data = resp.json()
            if isinstance(papers_data, list):
                # Sort papers by upvotes descending
                sorted_papers = sorted(
                    papers_data,
                    key=lambda p: (p.get("paper") or {}).get("upvotes", 0)
                    if isinstance(p, dict)
                    else 0,
                    reverse=True,
                )
                paper_quota = max(1, max_items - 1) if max_items > 1 else 1
                for item in sorted_papers[:paper_quota]:
                    paper = item.get("paper", {}) if isinstance(item, dict) else {}
                    paper_id = paper.get("id") or item.get("title", "")
                    title = paper.get("title") or item.get("title") or "Paper de IA"
                    summary = (paper.get("summary") or "").strip()
                    upvotes = paper.get("upvotes", 0)
                    url = f"https://huggingface.co/papers/{paper_id}" if paper_id else ""
                    ext_id = hashlib.sha256(f"hf_paper_{paper_id}".encode()).hexdigest()[:24]

                    signals.append(
                        Signal(
                            source="huggingface",
                            external_id=ext_id,
                            type="paper",
                            title=f"HF Paper: {title} (👍 {upvotes})",
                            summary=summary[:1000],
                            url=url,
                            occurred_at=paper.get("publishedAt", ""),
                            activity_date=day,
                            raw={
                                "paper_id": paper_id,
                                "upvotes": upvotes,
                                "title": title,
                                "authors": [
                                    a.get("name")
                                    for a in paper.get("authors", [])
                                    if isinstance(a, dict) and a.get("name")
                                ][:5],
                            },
                        )
                    )
    except Exception:
        log.exception("huggingface daily papers ingestion failed")

    # 2. Trending Models
    remaining = max_items - len(signals)
    if remaining > 0:
        try:
            params = {
                "sort": "likes7d",
                "direction": "-1",
                "limit": str(remaining),
            }
            resp = http.get(_MODELS_URL, headers=headers, params=params, timeout=_TIMEOUT)
            if resp.ok:
                models_data = resp.json()
                if isinstance(models_data, list):
                    for m in models_data[:remaining]:
                        model_id = m.get("id") or ""
                        likes = m.get("likes", 0)
                        downloads = m.get("downloads", 0)
                        tags = m.get("tags") or []
                        pipeline = m.get("pipeline_tag") or "general"
                        url = f"https://huggingface.co/{model_id}" if model_id else ""
                        ext_id = hashlib.sha256(f"hf_model_{model_id}".encode()).hexdigest()[:24]

                        summary = (
                            f"Modelo open-source en tendencia. Pipeline: {pipeline}. "
                            f"Descargas: {downloads}. Tags: {', '.join(tags[:6])}"
                        )

                        signals.append(
                            Signal(
                                source="huggingface",
                                external_id=ext_id,
                                type="model",
                                title=f"HF Model: {model_id} (❤️ {likes} likes/semana)",
                                summary=summary[:1000],
                                url=url,
                                occurred_at="",
                                activity_date=day,
                                raw={
                                    "model_id": model_id,
                                    "likes": likes,
                                    "downloads": downloads,
                                    "pipeline": pipeline,
                                    "tags": tags,
                                },
                            )
                        )
        except Exception:
            log.exception("huggingface trending models ingestion failed")

    log.info("huggingface: %d signals ingested", len(signals))
    return signals[:max_items]
