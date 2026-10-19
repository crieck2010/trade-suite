"""Licensing & storage ethics for press content (spec §9).

The press listener is a private research store on Charlie's machine,
not a republishing surface.  The rules below are load-bearing and are
enforced by the shape of the archive schema itself:

**We store** — headline, the RSS summary snippet the publisher chose to
syndicate, the canonical URL, the publisher name, and timestamps.
That is the minimum needed to classify, score, dedupe, and audit.

**We never store** — full article text, paywalled content, or anything
scraped from an article page.  If a feed stops offering a field, we go
without it; we do not go fetch the article.

**Redistribution** is limited to derived statistics: counts,
frequencies, tone aggregates, and the momentum state.  Headlines and
snippets stay inside the local archive and the local dashboards; they
are never republished, exported as a corpus, or used to train anything.

This mirrors the posture of ``trade_sentiment`` (headlines/chatter
references, not a content mirror) and exists as a module — not just a
README paragraph — so any future code that touches storage has one
place to check first.
"""

from __future__ import annotations

STORED_FIELDS = (
    "headline (title)",
    "RSS summary snippet",
    "canonical URL",
    "publisher name",
    "published / observed / recorded timestamps",
    "derived tone score and keyword hits",
)

NEVER_STORED = (
    "full article text",
    "paywalled content",
    "anything scraped from an article page",
)

REDISTRIBUTION = "derived statistics only (counts, tone aggregates, momentum state)"


def storage_policy() -> dict:
    """Machine-readable statement of the storage rules above."""
    return {
        "stored": list(STORED_FIELDS),
        "never_stored": list(NEVER_STORED),
        "redistribution": REDISTRIBUTION,
        "surface": "private local research archive; not a republishing surface",
    }
