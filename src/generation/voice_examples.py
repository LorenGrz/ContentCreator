"""The voice bank: a few hand-written examples that teach the model how
Lorenzo actually writes. Few-shot, hardcoded on purpose — small enough that an
embeddings/RAG store would be over-engineering at this stage (see README).

REPLACE THE PLACEHOLDERS with 4-6 real posts each, in your own voice, before
relying on generated output. Keep them short, specific, first person, no
hashtags, no "excited to announce" filler.
"""

from __future__ import annotations

# One or two sentences describing the tone, in addition to the examples below.
VOICE_NOTES = (
    "Primera persona, español rioplatense, directo y técnico. Sin hashtags, "
    "sin emojis salvo que aporten, sin frases de marketing ('thrilled to', "
    "'game changer'). Contás qué hiciste y por qué importa, con un detalle "
    "concreto. Está bien admitir dudas o cosas que salieron mal."
)

# Tweets: <= 280 chars, one idea, concrete.
TWITTER_EXAMPLES: list[str] = [
    "TODO: reemplazar — tweet real 1 sobre un commit/feature del día",
    "TODO: reemplazar — tweet real 2, un aprendizaje puntual",
    "TODO: reemplazar — tweet real 3, una reflexión sobre una noticia tech",
    "TODO: reemplazar — tweet real 4, algo que salió mal y cómo lo resolviste",
]

# LinkedIn: 3-6 short paragraphs, still first person, still specific.
LINKEDIN_EXAMPLES: list[str] = [
    "TODO: reemplazar — post real de LinkedIn sobre un PR grande mergeado, "
    "qué problema resolvía y qué decisiones de arquitectura tomaste",
    "TODO: reemplazar — post real de LinkedIn anunciando un repo/proyecto "
    "nuevo, el problema que ataca y el stack",
]


def has_real_examples() -> bool:
    """True once the placeholders have been replaced — lets the pipeline warn
    instead of shipping TODO-flavoured drafts."""
    return not any(
        ex.startswith("TODO: reemplazar")
        for ex in (*TWITTER_EXAMPLES, *LINKEDIN_EXAMPLES)
    )
