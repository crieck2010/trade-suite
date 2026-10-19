"""Tests for trade_press.archive — point-in-time discipline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from trade_sentiment.models import SentimentLabel

from trade_press.archive import PressArchive
from trade_press.models import PressItem, ScoredPressItem, make_item_id

T0 = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
THEME = "ai_infrastructure_capex"


def scored(title: str, *, published: datetime, recorded: datetime,
           polarity: float = 0.1) -> ScoredPressItem:
    item = PressItem(
        id=make_item_id(f"https://example.com/{title}", title),
        source="google_news", title=title, summary="data center capex",
        url=f"https://example.com/{title}", publisher="Reuters",
        published_at=published, observed_at=published,
        recorded_at=recorded,
    )
    return ScoredPressItem(
        item=item, theme_id=THEME, polarity=polarity, magnitude=0.5,
        label=SentimentLabel.BULLISH, hits=("data center", "capex"),
    )


@pytest.fixture()
def arc(tmp_path):
    a = PressArchive(tmp_path / "press.db")
    yield a
    a.close()


def test_record_and_query_round_trip(arc):
    s = scored("Story A", published=T0, recorded=T0)
    assert arc.record(s) is True
    out = arc.query(THEME, as_of=T0 + timedelta(hours=1))
    assert len(out) == 1
    assert out[0].item.title == "Story A"
    assert out[0].polarity == 0.1
    assert out[0].hits == ("data center", "capex")
    assert out[0].to_dict()["schema"] == "press.observation.v1"


def test_point_in_time_no_lookahead(arc):
    """An item recorded later must not exist for an earlier decision time."""
    late = scored("Late Story", published=T0,
                  recorded=T0 + timedelta(days=2))
    arc.record(late)
    assert arc.query(THEME, as_of=T0 + timedelta(days=1)) == []
    assert len(arc.query(THEME, as_of=T0 + timedelta(days=2))) == 1


def test_observed_after_recorded_is_rejected(arc):
    bad = scored("Time Travel", published=T0 + timedelta(days=1),
                 recorded=T0)
    with pytest.raises(ValueError, match="after recorded_at"):
        arc.record(bad)


def test_syndicated_duplicate_collapses(arc):
    s = scored("Wire Story", published=T0, recorded=T0)
    assert arc.record(s) is True
    assert arc.record(s) is False  # same content hash: no second row
    assert arc.record_many([s, s]) == 0
    assert len(arc.query(THEME, as_of=T0)) == 1


def test_themes_are_isolated(arc):
    arc.record(scored("Story A", published=T0, recorded=T0))
    assert arc.query("some_other_theme", as_of=T0) == []


def test_coverage_honesty(arc):
    assert arc.coverage() is None  # empty archive says so plainly
    assert arc.coverage(THEME) is None
    arc.record(scored("Story A", published=T0, recorded=T0))
    cov = arc.coverage(THEME)
    assert cov["n_items"] == 1
    assert cov["theme_id"] == THEME
    assert cov["first_recorded"].startswith("2026-10-19")
    assert arc.coverage()["n_themes"] == 1


def test_rollup_round_trip(arc):
    payload = {
        "schema": "press.narrative_state.v1", "theme_id": THEME,
        "as_of": "2026-10-19", "state": "INSUFFICIENT_DATA",
        "n_items": 3, "freq_z": None, "mean_polarity": 0.1,
        "polarity_slope_7d": None, "n_publishers": 2,
        "baseline_days": 0, "notes": [],
    }
    arc.save_rollup(payload, {})
    assert arc.get_rollup(THEME, "2026-10-19") == payload
    assert arc.get_rollup(THEME, "2026-10-18") is None
    # upsert: recomputing the same day replaces, never duplicates
    payload2 = {**payload, "n_items": 5}
    arc.save_rollup(payload2, {})
    assert arc.get_rollup(THEME, "2026-10-19")["n_items"] == 5
