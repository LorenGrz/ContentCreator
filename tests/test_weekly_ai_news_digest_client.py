import responses

from ingestion.weekly_ai_news_digest_client import fetch_weekly_ai_news_signals

_URL = "https://elbruno.github.io/weekly-ai-news-digest/"


@responses.activate
def test_extracts_curated_story_fields():
    responses.add(
        responses.GET,
        _URL,
        body="""
        <article class="story-card" data-rank="1" data-published="2026-09-21"
                 data-tags="Agents,Automation" data-source="Microsoft Developer">
          <div class="title"><a href="/story"><span class="lang-text"
            data-lang="en">English title</span>
            <span class="lang-text" data-lang="es">Título en español</span></a></div>
          <p class="tldr"><span>Resumen de la noticia.</span></p>
          <p class="why">Por qué importa: es útil para equipos.</p>
        </article>
        """,
        status=200,
    )

    signals = fetch_weekly_ai_news_signals(limit=1)

    assert len(signals) == 1
    assert signals[0].source == "weekly_ai_news_digest"
    assert signals[0].title == "Título en español"
    assert signals[0].summary == "Resumen de la noticia. Por qué importa: es útil para equipos."
    assert signals[0].url == "https://elbruno.github.io/story"
    assert signals[0].raw["tags"] == ["Agents", "Automation"]


@responses.activate
def test_respects_limit_and_skips_incomplete_cards():
    responses.add(
        responses.GET,
        _URL,
        body="""
        <article class="story-card" data-rank="1"><div class="title">Incomplete</div></article>
        <article class="story-card" data-rank="2"><div class="title"><a href="/two">
          <span class="lang-text" data-lang="en">Second</span></a></div>
          <p class="tldr">Summary</p></article>
        <article class="story-card" data-rank="3"><div class="title"><a href="/three">
          <span class="lang-text" data-lang="en">Third</span></a></div>
          <p class="tldr">Summary</p></article>
        """,
        status=200,
    )

    signals = fetch_weekly_ai_news_signals(limit=1)

    assert [signal.title for signal in signals] == ["Second"]


@responses.activate
def test_caps_microsoft_and_ensures_vendor_diversity():
    responses.add(
        responses.GET,
        _URL,
        body="""
        <article class="story-card" data-rank="1"
                 data-source="Microsoft Developer" data-tags="copilot">
          <div class="title"><a href="/copilot1">
            <span class="lang-text" data-lang="en">Copilot Feature 1</span></a></div>
          <p class="tldr">Summary 1</p>
        </article>
        <article class="story-card" data-rank="2"
                 data-source="Microsoft Developer" data-tags="azure">
          <div class="title"><a href="/azure1">
            <span class="lang-text" data-lang="en">Azure Update</span></a></div>
          <p class="tldr">Summary 2</p>
        </article>
        <article class="story-card" data-rank="3"
                 data-source="TechCrunch" data-tags="Claude,Anthropic">
          <div class="title"><a href="/claude1">
            <span class="lang-text" data-lang="en">Claude Sonnet 5</span></a></div>
          <p class="tldr">Summary 3</p>
        </article>
        <article class="story-card" data-rank="4"
                 data-source="TechCrunch" data-tags="OpenAI">
          <div class="title"><a href="/openai1">
            <span class="lang-text" data-lang="en">OpenAI Model</span></a></div>
          <p class="tldr">Summary 4</p>
        </article>
        """,
        status=200,
    )

    signals = fetch_weekly_ai_news_signals(limit=3)

    titles = [s.title for s in signals]
    # Selects Copilot 1, Claude Sonnet 5, OpenAI Model, skipping the 2nd Microsoft/Azure story
    assert len(signals) == 3
    assert titles == ["Copilot Feature 1", "Claude Sonnet 5", "OpenAI Model"]
