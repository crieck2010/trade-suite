"""Item tone via the suite's shared finance lexicon (spec §4.4).

Polarity comes from ``trade_sentiment``'s deterministic lexicon scorer —
one lexicon, two engines, so tone numbers stay comparable across the
suite.  The sibling import is lazy (inside the functions), following the
``trade_sentiment.adapters`` pattern: importing ``trade_press`` never
requires ``trade_sentiment`` to be importable until scoring is actually
called.  If the lexicon ever moves to a shared home, both engines
re-point in one commit.

The scored item's ``hits`` merge the classifier's theme terms with the
lexicon terms that fired, so one field explains both why the item
belongs to the theme and why it carries the tone it does.
"""

from __future__ import annotations

from .models import PressItem, ScoredPressItem


def _to_mention(item: PressItem):
    """Adapt a press item to the sentiment engine's mention shape."""
    from trade_sentiment.models import Mention

    return Mention(
        id=item.id,
        source=item.source,
        symbol="",  # press items are theme-scoped, never symbol-scoped
        text=f"{item.title}\n{item.summary}".strip(),
        timestamp=item.observed_at,
        author=item.publisher,
        url=item.url,
    )


def score_item(item: PressItem, theme_id: str,
               classifier_hits: tuple[str, ...] = ()) -> ScoredPressItem:
    """Score one classified item's title + summary tone."""
    from trade_sentiment.scoring import score_mentions

    scored = score_mentions([_to_mention(item)])[0]
    hits = tuple(dict.fromkeys((*classifier_hits, *scored.hits)))
    return ScoredPressItem(
        item=item,
        theme_id=theme_id,
        polarity=scored.polarity,
        magnitude=scored.magnitude,
        label=scored.label,
        hits=hits,
    )


def score_items(
    classified: list[tuple[PressItem, tuple[str, ...]]],
    theme_id: str,
) -> list[ScoredPressItem]:
    """Score a batch of (item, classifier hits) pairs for one theme."""
    return [score_item(item, theme_id, hits) for item, hits in classified]
