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
