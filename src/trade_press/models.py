"""Plain-data models.  No I/O, no network, no UI imports."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # runtime import lives in scoring.py (lazy, per spec §4.4)
    from trade_sentiment.models import SentimentLabel


class MomentumState(str, Enum):
    """Per-theme daily narrative verdict (spec §8 conventions)."""

    RISING = "RISING"
    STEADY = "STEADY"
    FADING = "FADING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def make_item_id(url: str, title: str) -> str:
    """Stable content id: sha256 of URL + normalized title.

    Deterministic across runs and processes (unlike ``hash()``), so the
    archive primary key collapses wire syndication of the same story no
    matter which query or scan surfaced it.
    """
    norm_title = re.sub(r"\s+", " ", title.strip().lower())
    digest = hashlib.sha256(f"{url.strip()}\n{norm_title}".encode("utf-8"))
    return f"press:{digest.hexdigest()[:24]}"


@dataclass(frozen=True)
class PressItem:
    """One press/news item as fetched, before classification and scoring.

    The three timestamps are the point-in-time contract (spec §3.4):

    - ``published_at`` — when the publisher says the story ran
      (``None`` when the feed omits it).
    - ``observed_at`` — when the story entered our world: the
      publication time when known, else the fetch time.
    - ``recorded_at`` — when the item entered the archive (the fetch
      time).  Always >= ``observed_at``; the archive enforces it.
    """

    id: str
    source: str  # "google_news" in Phase 1
    title: str
    summary: str  # RSS snippet only — never full article text (spec §9)
    url: str
    publisher: str
    published_at: datetime | None
    observed_at: datetime
    recorded_at: datetime

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source,
            "title": self.title, "summary": self.summary,
            "url": self.url, "publisher": self.publisher,
            "published_at": (self.published_at.isoformat()
                             if self.published_at is not None else None),
            "observed_at": self.observed_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True)
class ScoredPressItem:
    """A press item with its theme classification and tone attached.

    Its ``to_dict()`` is the frozen ``press.observation.v1`` payload
    (spec §5): the ``PressItem`` fields plus score fields, ISO-8601
    timestamps, and the keyword ``hits`` that explain both the theme
    match and the tone.
    """

    item: PressItem
    theme_id: str
    polarity: float  # -1.0 (very bearish) .. +1.0 (very bullish)
    magnitude: float  # 0..1, how much sentiment-bearing language was found
    label: "SentimentLabel"  # trade_sentiment.models.SentimentLabel
    hits: tuple[str, ...] = ()  # classifier + lexicon terms that fired

    def to_dict(self) -> dict:
        return {
            "schema": "press.observation.v1",
            **self.item.to_dict(),
            "theme_id": self.theme_id,
            "polarity": round(self.polarity, 3),
            "magnitude": round(self.magnitude, 3),
            "label": self.label.value,
            "hits": list(self.hits),
        }


@dataclass(frozen=True)
class ThemeDefinition:
    """A narrative theme pack: data, not code (spec §6).

    Adding a theme is a data change here plus tests — the engine never
    changes.  ``version`` is bumped whenever a pack's queries or terms
    change, so archived reads stay attributable to the pack that
    produced them.
    """

    theme_id: str
    title: str
    queries: tuple[str, ...]  # RSS search strings
    include_terms: tuple[str, ...]
    exclude_terms: tuple[str, ...] = ()
    min_hits: int = 2
    related_symbols: tuple[str, ...] = ()  # cross-reference only
    version: str = "1.0.0"

    def to_dict(self) -> dict:
        return {
            "theme_id": self.theme_id, "title": self.title,
            "queries": list(self.queries),
            "include_terms": list(self.include_terms),
            "exclude_terms": list(self.exclude_terms),
            "min_hits": self.min_hits,
            "related_symbols": list(self.related_symbols),
            "version": self.version,
        }


@dataclass(frozen=True)
class ThemeDayStats:
    """One theme, one day: the numbers behind the momentum verdict.

    ``baseline_*`` describe the trailing 30-day window of daily counts
    (recorded days only).  ``freq_z``/``polarity_slope_7d`` are ``None``
    when the underlying windows hold too little to compute honestly.
    """

    theme_id: str
    date: str  # ISO date the stats describe (UTC, by recorded day)
    n_items: int
    mean_polarity: float
    baseline_mean: float | None
    baseline_std: float | None
    freq_z: float | None  # today's count vs the baseline distribution
    polarity_slope_7d: float | None  # 7d mean polarity − prior-7d mean
    n_publishers: int  # distinct publishers among today's items
    baseline_days: int  # recorded days inside the 30-day baseline window

    def to_dict(self) -> dict:
        return {
            "theme_id": self.theme_id, "date": self.date,
            "n_items": self.n_items,
            "mean_polarity": round(self.mean_polarity, 3),
            "baseline_mean": (round(self.baseline_mean, 3)
                              if self.baseline_mean is not None else None),
            "baseline_std": (round(self.baseline_std, 3)
                             if self.baseline_std is not None else None),
            "freq_z": (round(self.freq_z, 2)
                       if self.freq_z is not None else None),
            "polarity_slope_7d": (round(self.polarity_slope_7d, 3)
                                  if self.polarity_slope_7d is not None
                                  else None),
            "n_publishers": self.n_publishers,
            "baseline_days": self.baseline_days,
        }


@dataclass(frozen=True)
class NarrativeState:
    """The per-theme daily verdict, with the stats that produced it.

    Its ``to_dict()`` is the frozen ``press.narrative_state.v1`` payload
    (spec §5) consumed by the agents' ``market_context``.  This is
    context, never a signal (spec §3.7).
    """

    theme_id: str
    as_of: str  # ISO date
    state: MomentumState
    stats: ThemeDayStats
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        s = self.stats
        return {
            "schema": "press.narrative_state.v1",
            "theme_id": self.theme_id,
            "as_of": self.as_of,
            "state": self.state.value,
            "n_items": s.n_items,
            "freq_z": (round(s.freq_z, 2) if s.freq_z is not None else None),
            "mean_polarity": round(s.mean_polarity, 3),
            "polarity_slope_7d": (round(s.polarity_slope_7d, 3)
                                  if s.polarity_slope_7d is not None
                                  else None),
            "n_publishers": s.n_publishers,
            "baseline_days": s.baseline_days,
            "notes": list(self.notes),
        }
