"""Daily aggregation and the narrative momentum state machine.

For each theme and day, everything is computed **only** from items with
``recorded_at`` on or before that day, bucketed by their recorded (UTC)
day — the day the item entered the archive is the day it became
knowable, which is what makes every read here point-in-time safe
(spec §4.6).

Two momentum numbers per day:

- **Frequency z-score** — today's item count vs the trailing 30-day
  distribution of daily counts (population std, the same convention as
  ``trade_sentiment.aggregation``'s volume z-score).
- **Polarity slope** — the last 7 days' mean polarity minus the prior
  7 days' mean polarity.  A shift, not a regression fit: simple,
  robust, explainable.

The state rules are the frozen conventions of spec §8 — documented,
round, symmetric, and **not fitted to returns**.  Changing any
threshold below requires a spec version bump and a changelog entry; it
is a pre-registered decision, never silent tuning.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, time, timedelta, timezone

from .archive import PressArchive
from .models import (
    MomentumState,
    NarrativeState,
    ScoredPressItem,
    ThemeDayStats,
)

BASELINE_DAYS = 30
FREQ_Z_THRESHOLD = 0.5
SLOPE_THRESHOLD = 0.05

MOMENTUM_RULES = (
    "INSUFFICIENT_DATA when fewer than 30 baseline days are recorded",
    f"FADING when freq_z <= -{FREQ_Z_THRESHOLD} and "
    f"polarity_slope_7d <= -{SLOPE_THRESHOLD} "
    "(told less often AND less warmly)",
    f"RISING when freq_z >= +{FREQ_Z_THRESHOLD} and "
    f"polarity_slope_7d >= +{SLOPE_THRESHOLD} "
    "(told more often AND more warmly)",
    "STEADY otherwise (a full baseline, no joint move)",
)


def _recorded_day(item: ScoredPressItem) -> date:
    rec = item.item.recorded_at
    if rec.tzinfo is None:
        rec = rec.replace(tzinfo=timezone.utc)
    return rec.astimezone(timezone.utc).date()


def compute_day_stats(theme_id: str, day: date,
                      items: list[ScoredPressItem]) -> ThemeDayStats:
    """Stats for ``day`` from items recorded through that day.

    ``items`` must already be point-in-time filtered (``recorded_at``
    at or before end of ``day``) — ``PressArchive.query`` does that;
    this function trusts its input so it stays pure and testable.
    """
    by_day: dict[date, list[ScoredPressItem]] = {}
    for s in items:
        by_day.setdefault(_recorded_day(s), []).append(s)

    today = by_day.get(day, [])
    n = len(today)
    mean_p = statistics.fmean([s.polarity for s in today]) if n else 0.0
    n_publishers = len({s.item.publisher for s in today if s.item.publisher})

    # Baseline: the BASELINE_DAYS calendar days before ``day``, counting
    # only days the listener was actually running (on/after the first
    # recorded day in the archive).  Days before deployment are unknown,
    # not zero — that distinction is the honesty rule of spec §7.
    window = [day - timedelta(days=k) for k in range(BASELINE_DAYS, 0, -1)]
    first_day = min(by_day) if by_day else None
    covered = [d for d in window if first_day is not None and d >= first_day]
    baseline_days = len(covered)
    counts = [len(by_day.get(d, [])) for d in covered]
    baseline_mean: float | None = None
    baseline_std: float | None = None
    freq_z: float | None = None
    if counts:
        baseline_mean = statistics.fmean(counts)
        baseline_std = statistics.pstdev(counts)
        if len(counts) >= 3:
            freq_z = (n - baseline_mean) / (baseline_std or 1.0)

    def _window_mean(lo: date, hi: date) -> float | None:
        pols = [s.polarity for d, day_items in by_day.items()
                if lo <= d <= hi for s in day_items]
        return statistics.fmean(pols) if pols else None

    recent = _window_mean(day - timedelta(days=6), day)
    prior = _window_mean(day - timedelta(days=13), day - timedelta(days=7))
    slope = (recent - prior) if recent is not None and prior is not None \
        else None

    return ThemeDayStats(
        theme_id=theme_id, date=day.isoformat(), n_items=n,
        mean_polarity=round(mean_p, 4),
        baseline_mean=(round(baseline_mean, 4)
                       if baseline_mean is not None else None),
        baseline_std=(round(baseline_std, 4)
                      if baseline_std is not None else None),
        freq_z=round(freq_z, 4) if freq_z is not None else None,
        polarity_slope_7d=round(slope, 4) if slope is not None else None,
        n_publishers=n_publishers, baseline_days=baseline_days,
    )


def momentum_state(stats: ThemeDayStats) -> MomentumState:
    """The frozen spec §8 state rules, applied to one day's stats."""
    if stats.baseline_days < BASELINE_DAYS:
        return MomentumState.INSUFFICIENT_DATA
    z, slope = stats.freq_z, stats.polarity_slope_7d
    if z is not None and slope is not None:
        if z <= -FREQ_Z_THRESHOLD and slope <= -SLOPE_THRESHOLD:
            return MomentumState.FADING
        if z >= FREQ_Z_THRESHOLD and slope >= SLOPE_THRESHOLD:
            return MomentumState.RISING
    return MomentumState.STEADY


def rollup_day(archive: PressArchive, theme_id: str,
               day: date) -> NarrativeState:
    """Compute, store, and return the narrative state for one day.

    Reads only items recorded through end of ``day`` (UTC), so a rollup
    recomputed later for a past date can never see items that arrived
    after that date.
    """
    end = datetime.combine(day, time.max, tzinfo=timezone.utc)
    items = archive.query(theme_id, as_of=end)
    stats = compute_day_stats(theme_id, day, items)
    state = momentum_state(stats)

    notes: list[str] = []
    if stats.baseline_days < BASELINE_DAYS:
        notes.append(
            f"baseline window incomplete: {stats.baseline_days} of "
            f"{BASELINE_DAYS} baseline days recorded")
    if stats.n_items == 0:
        notes.append("no items recorded on this date")

    result = NarrativeState(
        theme_id=theme_id, as_of=day.isoformat(), state=state,
        stats=stats, notes=tuple(notes),
    )
    archive.save_rollup(result.to_dict(), stats.to_dict())
    return result
