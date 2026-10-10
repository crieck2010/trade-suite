"""Health state machine for live strategies: healthy -> watchlist -> demoted.

A strategy is **healthy** while live performance tracks its
validation-time expectation, moves to **watchlist** when it
deteriorates, and is **demoted** when the deterioration is severe or
confirmed.  Demotion emits a *recommendation to retire* -- the engine
never touches the broker, closes positions, or edits an allocator; a
human (or a consuming system) acts on the recommendation.

Signal levels (worst signal wins):
  * Sharpe ratio ``trailing / expected`` below ``sharpe_warn_ratio``,
    z-score below ``z_warn``, or realized max-drawdown beyond
    ``dd_warn_ratio`` x validation maxDD  ->  warn (level 1)
  * the same metrics past the ``*_demote_*`` thresholds  ->  demote (level 2)

Transitions:
  healthy   --(warn)-->   watchlist
  healthy   --(demote)--> demoted      (a demote-level breach is a cliff,
                                       not a slope; it does not queue
                                       behind the watchlist)
  watchlist --(demote)--> demoted
  watchlist --(recovered)--> healthy   (hysteresis: recovery needs
                                       ``recover_ratio`` of expectation,
                                       so a strategy does not flicker)
  watchlist --(warn persists)--> watchlist
  demoted   --(anything)--> demoted    (sticky; only an explicit operator
                                       ``promote`` moves it, and that is
                                       recorded as an event)

Evaluations with too little history (fewer than ``min_daily_points``
daily marks) leave the state untouched and report
``insufficient-data`` -- a young strategy is unjudged, not healthy.

Stdlib only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Health states, in escalation order.
HEALTHY = "healthy"
WATCHLIST = "watchlist"
DEMOTED = "demoted"

STATES = (HEALTHY, WATCHLIST, DEMOTED)

#: Sentinel state reported (never stored) when history is too thin.
INSUFFICIENT_DATA = "insufficient-data"


@dataclass
class Thresholds:
    """Tunable escalation thresholds (see docs/METHODOLOGY.md)."""
    sharpe_warn_ratio: float = 0.5    # trailing < 50% of expected -> warn
    sharpe_demote_ratio: float = 0.25  # trailing < 25% of expected -> demote
    z_warn: float = -1.0
    z_demote: float = -2.0
    dd_warn_ratio: float = 1.0        # realized DD > 1x validation maxDD
    dd_demote_ratio: float = 1.5      # realized DD > 1.5x validation maxDD
    recover_ratio: float = 0.75       # trailing >= 75% of expected to recover
    min_daily_points: int = 20
    trailing_window_days: int = 60

    @classmethod
    def from_dict(cls, data: dict | None) -> "Thresholds":
        base = cls()
        if not data:
            return base
        for name in base.__dataclass_fields__:
            if name in data:
                setattr(base, name, data[name])
        return base

    def to_dict(self) -> dict:
        return {name: getattr(self, name)
                for name in self.__dataclass_fields__}


def signal_level(*, sharpe_ratio: float | None, z_score: float | None,
                 dd_ratio: float | None, t: Thresholds) -> tuple[int, list]:
    """Worst signal level across the three decay metrics.

    Returns ``(level, fired)`` where level is 0 (ok), 1 (warn) or 2
    (demote) and ``fired`` names the breached thresholds, e.g.
    ``["sharpe<warn(0.5)", "dd>demote(1.5)"]``.
    """
    level = 0
    fired: list[str] = []

    def _bump(candidate: int, label: str):
        nonlocal level
        if candidate > level:
            level = candidate
        fired.append(label)

    if sharpe_ratio is not None and math.isfinite(sharpe_ratio):
        if sharpe_ratio < t.sharpe_demote_ratio:
            _bump(2, f"sharpe<demote({t.sharpe_demote_ratio})")
        elif sharpe_ratio < t.sharpe_warn_ratio:
            _bump(1, f"sharpe<warn({t.sharpe_warn_ratio})")
    if z_score is not None and math.isfinite(z_score):
        if z_score < t.z_demote:
            _bump(2, f"z<demote({t.z_demote})")
        elif z_score < t.z_warn:
            _bump(1, f"z<warn({t.z_warn})")
    if dd_ratio is not None and math.isfinite(dd_ratio):
        if dd_ratio > t.dd_demote_ratio:
            _bump(2, f"dd>demote({t.dd_demote_ratio})")
        elif dd_ratio > t.dd_warn_ratio:
            _bump(1, f"dd>warn({t.dd_warn_ratio})")
    return level, fired


def recovered(*, sharpe_ratio: float | None, dd_ratio: float | None,
              t: Thresholds) -> bool:
    """Hysteresis gate for watchlist -> healthy.

    Recovery demands the Sharpe ratio back above ``recover_ratio`` of
    expectation *and* no ongoing drawdown breach -- one good week does
    not erase a broken edge.
    """
    if sharpe_ratio is None or not math.isfinite(sharpe_ratio):
        return False
    if sharpe_ratio < t.recover_ratio:
        return False
    if dd_ratio is not None and math.isfinite(dd_ratio) \
            and dd_ratio > t.dd_warn_ratio:
        return False
    return True


def evaluate(*, current_state: str, n_daily_points: int,
             sharpe_ratio: float | None, z_score: float | None,
             dd_ratio: float | None,
             thresholds: Thresholds | None = None) -> dict:
    """One state-machine step.  Pure function -- no I/O.

    Returns ``{"state", "previous_state", "level", "fired",
    "recommendation"}``.  ``state`` is ``insufficient-data`` (and
    ``previous_state`` unchanged) when history is too thin.
    """
    t = thresholds or Thresholds()
    if current_state not in STATES:
        raise ValueError(f"unknown state {current_state!r}")

    if n_daily_points < t.min_daily_points:
        return {"state": INSUFFICIENT_DATA, "previous_state": current_state,
                "level": 0, "fired": [],
                "recommendation": (
                    f"only {n_daily_points} daily marks "
                    f"(need {t.min_daily_points}); no judgment yet")}

    level, fired = signal_level(sharpe_ratio=sharpe_ratio, z_score=z_score,
                                dd_ratio=dd_ratio, t=t)

    new_state = current_state
    if current_state == HEALTHY:
        if level == 2:
            new_state = DEMOTED
        elif level == 1:
            new_state = WATCHLIST
    elif current_state == WATCHLIST:
        if level == 2:
            new_state = DEMOTED
        elif level == 0 and recovered(sharpe_ratio=sharpe_ratio,
                                     dd_ratio=dd_ratio, t=t):
            new_state = HEALTHY
    # DEMOTED is sticky: no automatic transition out.

    return {"state": new_state, "previous_state": current_state,
            "level": level, "fired": fired,
            "recommendation": _recommendation(new_state, current_state,
                                             fired, level)}


def _recommendation(new_state: str, old_state: str, fired: list,
                    level: int) -> str:
    if new_state == DEMOTED and old_state != DEMOTED:
        return ("recommend retirement: " + "; ".join(fired)
                if fired else "recommend retirement")
    if new_state == DEMOTED:
        return "demoted: retirement recommended; operator promote to revisit"
    if new_state == WATCHLIST:
        detail = "; ".join(fired) if fired else "deterioration"
        return f"watch: {detail} (escalates to demoted on further decay)"
    if new_state == HEALTHY and old_state == WATCHLIST:
        return "recovered: trailing performance back within tolerance"
    if level == 0:
        return "no action"
    return "no action"
