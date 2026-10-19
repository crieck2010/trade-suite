"""Tests for trade_press.aggregate — frozen momentum conventions (spec §8)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from trade_sentiment.models import SentimentLabel

from trade_press.aggregate import (
    BASELINE_DAYS,
    compute_day_stats,
    momentum_state,
    rollup_day,
)
from trade_press.archive import PressArchive
from trade_press.models import (
    MomentumState,
    PressItem,
    ScoredPressItem,
    ThemeDayStats,
    make_item_id,
)

THEME = "ai_infrastructure_capex"
DAY = date(2026, 10, 19)


def scored_on(day: date, idx: int, polarity: float,
              publisher: str = "Reuters") -> ScoredPressItem:
    ts = datetime.combine(day, time(12, 0), tzinfo=timezone.utc)
    title = f"Story {day.isoformat()} #{idx}"
    item = PressItem(
        id=make_item_id(f"https://example.com/{title}", title),
        source="google_news", title=title, summary="data center capex",
        url=f"https://example.com/{title}", publisher=publisher,
        published_at=ts, observed_at=ts, recorded_at=ts,
    )
    return ScoredPressItem(
        item=item, theme_id=THEME, polarity=polarity, magnitude=0.5,
        label=SentimentLabel.NEUTRAL, hits=("data center",),
    )


def stats(**kw) -> ThemeDayStats:
    base = dict(
        theme_id=THEME, date=DAY.isoformat(), n_items=10,
        mean_polarity=0.0, baseline_mean=10.0, baseline_std=2.0,
        freq_z=0.0, polarity_slope_7d=0.0, n_publishers=3,
        baseline_days=BASELINE_DAYS,
    )
    base.update(kw)
    return ThemeDayStats(**base)


# -- the state machine, at its boundaries ------------------------------------

def test_fading_exactly_at_thresholds():
    s = stats(freq_z=-0.5, polarity_slope_7d=-0.05)
    assert momentum_state(s) is MomentumState.FADING


def test_rising_exactly_at_thresholds():
    s = stats(freq_z=0.5, polarity_slope_7d=0.05)
    assert momentum_state(s) is MomentumState.RISING


def test_one_condition_alone_is_steady():
    assert momentum_state(stats(freq_z=-2.0, polarity_slope_7d=0.0)) \
        is MomentumState.STEADY
    assert momentum_state(stats(freq_z=0.0, polarity_slope_7d=-0.4)) \
        is MomentumState.STEADY


def test_missing_numbers_are_steady_with_full_baseline():
    s = stats(freq_z=None, polarity_slope_7d=None)
    assert momentum_state(s) is MomentumState.STEADY


def test_insufficient_data_beats_extreme_numbers():
    s = stats(freq_z=-9.0, polarity_slope_7d=-0.9,
              baseline_days=BASELINE_DAYS - 1)
    assert momentum_state(s) is MomentumState.INSUFFICIENT_DATA


# -- the stats math on synthetic series ---------------------------------------

def _series(day_polarity_count):
    """{(days_before_DAY): (n_items, polarity)} → scored items list."""
    out = []
    for back, (n, pol) in day_polarity_count.items():
        d = DAY - timedelta(days=back)
        out.extend(scored_on(d, i, pol) for i in range(n))
    return out


def test_flat_series_is_steady_with_zero_z():
    items = _series({back: (4, 0.0) for back in range(0, 31)})
    s = compute_day_stats(THEME, DAY, items)
    assert s.baseline_days == 30
    assert s.freq_z == 0.0  # (4 - 4) / fallback sd
    assert s.polarity_slope_7d == 0.0
    assert momentum_state(s) is MomentumState.STEADY


def test_fading_series():
    plan = {back: (4, 0.2) for back in range(7, 31)}     # warm baseline
    plan.update({back: (4, -0.3) for back in range(1, 7)})  # cold week
    plan[0] = (1, -0.3)                                     # thin today
    s = compute_day_stats(THEME, DAY, _series(plan))
    assert s.freq_z == -3.0  # counts were a constant 4 → (1-4)/1.0
    assert s.polarity_slope_7d == -0.5
    assert momentum_state(s) is MomentumState.FADING


def test_baseline_days_count_only_recorded_days():
    items = _series({back: (2, 0.0) for back in range(0, 10)})
    s = compute_day_stats(THEME, DAY, items)
    assert s.baseline_days == 9  # only 9 of the 30 window days have coverage
    assert momentum_state(s) is MomentumState.INSUFFICIENT_DATA


def test_n_publishers_counts_distinct_publishers():
    items = [scored_on(DAY, 0, 0.1, "Reuters"),
             scored_on(DAY, 1, 0.1, "Reuters"),
             scored_on(DAY, 2, 0.1, "Bloomberg")]
    s = compute_day_stats(THEME, DAY, items)
    assert s.n_items == 3
    assert s.n_publishers == 2


# -- rollup through the archive ------------------------------------------------

def test_rollup_day_one_is_insufficient_data():
    arc = PressArchive(":memory:")
    for s in _series({0: (3, 0.2)}):
        arc.record(s)
    state = rollup_day(arc, THEME, DAY)
    assert state.state is MomentumState.INSUFFICIENT_DATA
    assert state.stats.baseline_days == 0
    assert any("baseline window incomplete" in n for n in state.notes)
    assert arc.get_rollup(THEME, DAY.isoformat()) is not None
    arc.close()


def test_rollup_never_sees_items_recorded_after_the_day():
    arc = PressArchive(":memory:")
    for s in _series({0: (3, 0.2)}):
        arc.record(s)
    first = rollup_day(arc, THEME, DAY)
    # an item published yesterday but only *recorded* tomorrow must not
    # change yesterday's rollup when it is recomputed
    pub = datetime.combine(DAY, time(9, 0), tzinfo=timezone.utc)
    rec = datetime.combine(DAY + timedelta(days=1), time(9, 0),
                           tzinfo=timezone.utc)
    late_item = PressItem(
        id=make_item_id("https://example.com/late", "Late Story"),
        source="google_news", title="Late Story",
        summary="data center capex", url="https://example.com/late",
        publisher="Reuters", published_at=pub, observed_at=pub,
        recorded_at=rec)
    arc.record(ScoredPressItem(
        item=late_item, theme_id=THEME, polarity=-0.9, magnitude=0.5,
        label=SentimentLabel.VERY_BEARISH, hits=("data center",)))
    second = rollup_day(arc, THEME, DAY)
    assert second.stats.n_items == first.stats.n_items == 3
    assert second.to_dict() == first.to_dict()
    arc.close()
