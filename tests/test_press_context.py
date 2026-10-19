"""Tests for trade_press.context — strict as-of narrative reads."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest
from trade_sentiment.models import SentimentLabel

from trade_press.aggregate import rollup_day
from trade_press.archive import PressArchive
from trade_press.context import narrative_input
from trade_press.models import PressItem, ScoredPressItem, make_item_id

THEME = "ai_infrastructure_capex"
DAY = date(2026, 10, 19)

FROZEN_KEYS = {
    "schema", "theme_id", "as_of", "state", "n_items", "freq_z",
    "mean_polarity", "polarity_slope_7d", "n_publishers",
    "baseline_days", "notes",
}


@pytest.fixture()
def arc():
    a = PressArchive(":memory:")
    ts = datetime.combine(DAY, time(12, 0), tzinfo=timezone.utc)
    item = PressItem(
        id=make_item_id("https://example.com/a", "Story A"),
        source="google_news", title="Story A", summary="data center capex",
        url="https://example.com/a", publisher="Reuters",
        published_at=ts, observed_at=ts, recorded_at=ts)
    a.record(ScoredPressItem(
        item=item, theme_id=THEME, polarity=0.2, magnitude=0.5,
        label=SentimentLabel.BULLISH, hits=("data center",)))
    rollup_day(a, THEME, DAY)
    yield a
    a.close()


def test_payload_matches_frozen_schema(arc):
    payload = narrative_input("2026-10-19", arc)
    assert set(payload) == FROZEN_KEYS
    assert payload["schema"] == "press.narrative_state.v1"
    assert payload["theme_id"] == THEME
    assert payload["as_of"] == "2026-10-19"
    assert payload["state"] == "INSUFFICIENT_DATA"  # day one, honestly
    assert payload["n_items"] == 1


def test_date_object_accepted(arc):
    assert narrative_input(DAY, arc)["as_of"] == "2026-10-19"


def test_missing_rollup_raises_never_stale(arc):
    with pytest.raises(ValueError, match="no narrative rollup"):
        narrative_input("2026-10-18", arc)


def test_unknown_theme_raises_with_hint(arc):
    with pytest.raises(KeyError, match="unknown press theme"):
        narrative_input("2026-10-19", arc, theme_id="nope")


def test_bad_date_raises(arc):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        narrative_input("19/10/2026", arc)
