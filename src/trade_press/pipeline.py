"""End-to-end pipeline: fetch → classify → score → archive; rollup.

``scan()`` is the one call the CLI and the accumulation cron share.
Fetching is the only network step; classification, scoring, and
archiving are deterministic transforms of what was fetched.  Items
that do not match the theme are dropped, never archived — the archive
holds the narrative's evidence, not the whole firehose.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from . import aggregate as agg
from .archive import PressArchive
from .classify import classify_items
from .models import NarrativeState, ScoredPressItem
from .scoring import score_items
from .sources import PressSource, get_source
from .themes import ThemeDefinition, get_theme


def scan(
    theme: ThemeDefinition | str,
    source: PressSource | str | None = None,
    archive: PressArchive | None = None,
    limit_per_query: int = 50,
) -> list[ScoredPressItem]:
    """Fetch, classify, and score one theme's current press coverage.

    ``theme`` is a ``ThemeDefinition`` or a registered theme id.
    ``source`` is a ``PressSource`` instance, a registered source name,
    or None (the default ``google_news`` source).  When ``archive`` is
    given, every scored item is recorded (record-on-fetch) with the
    timestamps the source stamped — ``observed_at`` from publication,
    ``recorded_at`` from the fetch — so the archive stays point-in-time
    safe.  A failing record never kills the scan (mirrors
    ``trade_sentiment.pipeline``); the primary key dedupes repeats.

    Returns the scored items for the theme (archived or not).
    """
    theme_def = theme if isinstance(theme, ThemeDefinition) \
        else get_theme(theme)
    if source is None:
        src: PressSource = get_source("google_news")
    elif isinstance(source, str):
        src = get_source(source)
    else:
        src = source

    fetched = src.fetch(theme_def, limit=limit_per_query)
    classified = classify_items(fetched, theme_def)
    scored = score_items(classified, theme_def.theme_id)

    if archive is not None:
        for s in scored:
            try:
                archive.record(s)
            except Exception:
                pass  # archiving must never kill the scan
    return scored


def rollup(
    archive: PressArchive,
    theme: ThemeDefinition | str,
    day: date | None = None,
) -> NarrativeState:
    """Compute and store the narrative state for one day (default: today UTC).

    Only items recorded through that day are read, so re-running a past
    date's rollup is reproducible and look-ahead-free.
    """
    theme_def = theme if isinstance(theme, ThemeDefinition) \
        else get_theme(theme)
    day = day or datetime.now(timezone.utc).date()
    return agg.rollup_day(archive, theme_def.theme_id, day)
