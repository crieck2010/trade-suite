"""Narrative momentum engine (the press listener) for the trade-suite.

Listens to the financial press by **narrative theme** rather than by
ticker, archives what it hears point-in-time, and reduces each theme to
one daily question: is this narrative gaining momentum, holding steady,
or fading?  It is the sibling of ``trade_sentiment`` — that engine asks
"what are people saying about NVDA?"; this one asks "is the AI-capex
story losing momentum?"

The core is stdlib-only, keyless, and deterministic: Google News RSS by
theme query, a keyword classifier whose hits are stored for audit, the
shared ``trade_sentiment`` lexicon for tone (imported lazily), and a
SQLite archive with the suite's dual-timestamp discipline —
``observed_at`` (publication) vs ``recorded_at`` (fetch) — so every
read is point-in-time safe and no history is ever fabricated.

Outputs are **context, never signals**: the frozen
``press.narrative_state.v1`` payload feeds the agents'
``market_context`` the way ``trade_macro.weather``'s barometer feeds
sizing context.  Nothing may trade on narrative state until a
narrative→return relationship passes Tier-1 validation (spec §14).
"""

from __future__ import annotations

__version__ = "0.1.0"

from .archive import DEFAULT_ARCHIVE_PATH, PressArchive
from .classify import classify_hits, classify_item, classify_items
from .context import narrative_input
from .models import (
    MomentumState,
    NarrativeState,
    PressItem,
    ScoredPressItem,
    ThemeDayStats,
    ThemeDefinition,
)
from .pipeline import rollup, scan
from .themes import THEME_PACKS, get_theme

__all__ = [
    "DEFAULT_ARCHIVE_PATH",
    "MomentumState",
    "NarrativeState",
    "PressArchive",
    "PressItem",
    "ScoredPressItem",
    "THEME_PACKS",
    "ThemeDayStats",
    "ThemeDefinition",
    "classify_hits",
    "classify_item",
    "classify_items",
    "get_theme",
    "narrative_input",
    "rollup",
    "scan",
    "__version__",
]
