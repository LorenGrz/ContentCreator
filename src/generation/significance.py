"""Does the day warrant a LinkedIn post?

Tweets go out every day; LinkedIn only when something genuinely notable
happened. This is a small, explicit rule set — *not* a second LLM call — so
it stays predictable and cheap to tune. Adjust the constants below.

Rules (any one is enough):
  * a pull request was merged
  * a new repository was created
  * a calendar event whose title matches a "milestone" keyword
    (talk, launch, interview, award, …) — plain meetings never qualify
"""

from __future__ import annotations

from dataclasses import dataclass, field

from storage.models import Signal

# Calendar titles that signal something worth a LinkedIn post. Matched
# case-insensitively as substrings, so short stems cover conjugations.
LINKEDIN_EVENT_KEYWORDS: tuple[str, ...] = (
    "charla",
    "talk",
    "conf",
    "meetup",
    "presentaci",
    "demo day",
    "lanzamiento",
    "launch",
    "release",
    "entrevista",
    "interview",
    "workshop",
    "hackathon",
    "premi",
    "award",
    "keynote",
    "podcast",
)


@dataclass
class Significance:
    linkedin_worthy: bool
    reasons: list[str] = field(default_factory=list)
    highlight_keys: list[str] = field(default_factory=list)  # sk of the driving signals


def _event_keyword_hit(title: str) -> str | None:
    low = title.lower()
    for kw in LINKEDIN_EVENT_KEYWORDS:
        if kw in low:
            return kw
    return None


def evaluate(signals: list[Signal]) -> Significance:
    reasons: list[str] = []
    highlights: list[str] = []

    for s in signals:
        if s.source == "github" and s.type == "pr" and s.raw.get("state") == "merged":
            reasons.append(f"merged PR: {s.title}")
            highlights.append(s.sk)
        elif s.source == "github" and s.type == "new_repo":
            reasons.append(f"new repo: {s.title}")
            highlights.append(s.sk)
        elif s.source == "calendar" and s.type == "event":
            kw = _event_keyword_hit(s.title)
            if kw:
                reasons.append(f"calendar milestone ({kw!r}): {s.title}")
                highlights.append(s.sk)

    return Significance(
        linkedin_worthy=bool(reasons),
        reasons=reasons,
        highlight_keys=highlights,
    )
