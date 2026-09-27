from __future__ import annotations

import responses

from ingestion.huggingface_client import fetch_huggingface_signals

SAMPLE_PAPERS = [
    {
        "paper": {
            "id": "2409.12345",
            "title": "Reasoning Models with Tree Search",
            "summary": "We introduce a search mechanism over latent thoughts.",
            "upvotes": 42,
            "publishedAt": "2026-09-25T08:00:00Z",
            "authors": [{"name": "Alice Dev"}, {"name": "Bob Researcher"}],
        }
    },
    {
        "paper": {
            "id": "2409.67890",
            "title": "Fast Quantization for MoE Models",
            "summary": "2-bit quantization for trillion-parameter Mixture of Experts.",
            "upvotes": 18,
            "publishedAt": "2026-09-26T12:00:00Z",
            "authors": [{"name": "Charlie Engineer"}],
        }
    },
]

SAMPLE_MODELS = [
    {
        "id": "meta-llama/Llama-3.5-70B-Instruct",
        "likes": 350,
        "downloads": 85000,
        "pipeline_tag": "text-generation",
        "tags": ["llama", "instruction", "nlp"],
    },
    {
        "id": "black-forest-labs/FLUX.2-turbo",
        "likes": 280,
        "downloads": 42000,
        "pipeline_tag": "text-to-image",
        "tags": ["diffusion", "fast"],
    },
]


@responses.activate
def test_fetch_huggingface_signals_papers_and_models():
    responses.add(
        responses.GET,
        "https://huggingface.co/api/daily_papers",
        json=SAMPLE_PAPERS,
        status=200,
    )
    responses.add(
        responses.GET,
        "https://huggingface.co/api/models",
        json=SAMPLE_MODELS,
        status=200,
    )

    signals = fetch_huggingface_signals(limit=3)

    assert len(signals) == 3
    # Check paper signals
    paper_signals = [s for s in signals if s.type == "paper"]
    assert len(paper_signals) >= 1
    p1 = paper_signals[0]
    assert p1.source == "huggingface"
    assert "Reasoning Models with Tree Search" in p1.title
    assert "👍 42" in p1.title
    assert p1.url == "https://huggingface.co/papers/2409.12345"
    assert "latent thoughts" in p1.summary

    # Check model signal
    model_signals = [s for s in signals if s.type == "model"]
    assert len(model_signals) >= 1
    m1 = model_signals[0]
    assert m1.source == "huggingface"
    assert "meta-llama/Llama-3.5-70B-Instruct" in m1.title
    assert "350 likes/semana" in m1.title
    assert m1.url == "https://huggingface.co/meta-llama/Llama-3.5-70B-Instruct"


@responses.activate
def test_fetch_huggingface_signals_limit_zero():
    signals = fetch_huggingface_signals(limit=0)
    assert signals == []


@responses.activate
def test_fetch_huggingface_signals_papers_fail_falls_back_to_models():
    responses.add(
        responses.GET,
        "https://huggingface.co/api/daily_papers",
        status=500,
    )
    responses.add(
        responses.GET,
        "https://huggingface.co/api/models",
        json=SAMPLE_MODELS,
        status=200,
    )

    signals = fetch_huggingface_signals(limit=2)

    assert len(signals) == 2
    assert all(s.type == "model" for s in signals)
