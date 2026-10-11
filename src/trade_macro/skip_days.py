"""Skip-day conditioning: tail-risk days for short-premium *research*.

Thesis: some calendar days concentrate the tail risk that kills short-
premium strategies — FOMC announcement days (intraday gaps on the rate
decision), monthly options-expiration days (pinning/gamma unwind), and the
last trading day of the month (rebalance flows).  For a 0DTE iron-fly
style harvester, these are conditioning variables: the research question
is "how does the strategy behave with vs. without these days?", not "trade
every day and hope".

Usage contract (read this before calling):

- This module is a **research filter** for conditioning backtests
  ("skip-day-conditioned returns").  It is NOT auto-wired into any live
  runner, paper config, or strategy — a day being "skipped" here changes
  nothing by itself.  Promoting any skip rule to live trading requires
  Charlie's explicit approval after validation.
- The three skip-day types are **hypotheses**, not facts.  The source
  video claimed skipping them "doubles performance" — a huge effect from
  ~5% of trading days that smells of a few specific events driving the
  result.  Treat as conditioning to test, never as a rule to adopt.

Wednesday/Friday discrepancy note: the source video said to skip "the
third Wednesday of the month".  Standard monthly SPX options expiration
is the **third Friday** — the day with the documented pinning/gamma
effects.  This module defaults to ``opex_rule="third_friday"`` and records
the discrepancy here.  ``"third_wednesday"`` remains a supported,
configurable value so the video's claim can be tested as stated; if
research ever vindicates Wednesday, the rule changes by configuration,
not by code edit.

FOMC dates: the shipped list covers 2025, 2026, and the announced 2027
schedule — the **announcement (decision) day**, i.e. the second day of
each FOMC meeting, which is when the statement drops at 14:00 ET and the
tail risk lands.  Source: the Federal Reserve's meeting calendars
(federalreserve.gov/monetarypolicy/fomccalendars.htm).  Refresh cadence:
**quarterly** — the Fed publishes the next year's schedule each June, and
unscheduled meetings happen.  ``SkipCalendar.fomc_dates`` is the adapter
slot: a future Fed-calendar feed replaces the static list with zero
changes to this module's logic.

No-look-ahead note: this is a pure calendar read — ``is_skip_day`` needs
nothing but the date (plus an optional session calendar), so there is no
future data to leak by construction.

Stdlib only.  Plain data in/out.  Research/backtesting only.
"""

from __future__ import annotations

import calendar as _calendar
from dataclasses import dataclass, field
from datetime import date
from datetime import timedelta


# ---------------------------------------------------------------------------
# Shipped FOMC announcement (decision-day) list
# ---------------------------------------------------------------------------

# Second day of each scheduled FOMC meeting — the statement release day.
# Source: federalreserve.gov/monetarypolicy/fomccalendars.htm
# (verified 2026-10-11).  Refresh QUARTERLY; see module docstring.
# Adapter slot: pass your own frozenset to SkipCalendar to override.
_SHIPPED_FOMC_DATES = frozenset({
    # 2025
    date(2025, 1, 29), date(2025, 3, 19), date(2025, 5, 7),
    date(2025, 6, 18), date(2025, 7, 30), date(2025, 9, 17),
    date(2025, 10, 29), date(2025, 12, 10),
    # 2026
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
    date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
    date(2026, 10, 28), date(2026, 12, 9),
    # 2027 (announced schedule)
    date(2027, 1, 27), date(2027, 3, 17), date(2027, 4, 28),
    date(2027, 6, 9), date(2027, 7, 28), date(2027, 9, 15),
    date(2027, 10, 27),
})

# Supported monthly-expiration rules.  "third_friday" is the standard
# monthly SPX OpEx; "third_wednesday" is the source video's claim, kept
# configurable so it can be tested as stated.
OPEX_RULES = ("third_friday", "third_wednesday")

_SKIP_REASONS = ("fomc", "opex", "month_end")


def _as_date(value: date | str, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{name}: expected date or ISO 'YYYY-MM-DD', "
                         f"got {value!r}") from None


def _third_weekday(year: int, month: int, weekday: int) -> date:
    """The third ``weekday`` (Mon=0..Sun=6) of a calendar month."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def _opex_date(year: int, month: int, rule: str) -> date:
    if rule == "third_friday":
        return _third_weekday(year, month, 4)   # Friday
    if rule == "third_wednesday":
        return _third_weekday(year, month, 2)   # Wednesday
    raise ValueError(f"opex_rule: expected one of {OPEX_RULES}, "
                     f"got {rule!r}")


@dataclass(frozen=True)
class SkipCalendar:
    """Which calendar days count as tail-risk skip days.

    ``fomc_dates`` is the adapter slot: pass the shipped list via
    :func:`default_skip_calendar`, or your own frozenset (e.g. from a
    future Fed-calendar feed) to override with zero logic changes.
    """

    fomc_dates: frozenset = field(default_factory=frozenset)
    opex_rule: str = "third_friday"   # one of OPEX_RULES; see discrepancy note
    month_end: bool = True            # flag the last trading day of the month

    def __post_init__(self) -> None:
        if self.opex_rule not in OPEX_RULES:
            raise ValueError(f"opex_rule: expected one of {OPEX_RULES}, "
                             f"got {self.opex_rule!r}")
        for d in self.fomc_dates:
            if not isinstance(d, date):
                raise ValueError(f"fomc_dates: expected date objects, "
                                 f"got {d!r}")


def default_skip_calendar() -> SkipCalendar:
    """The shipped calendar: static FOMC list, third-Friday OpEx, month-end on."""
    return SkipCalendar(fomc_dates=_SHIPPED_FOMC_DATES)


@dataclass(frozen=True)
class SkipDay:
    """The skip-day read for one date."""

    date: str               # ISO date the read applies to
    skipped: bool           # True when at least one reason fires
    reasons: list           # subset of ("fomc", "opex", "month_end"), in that order
    reason: str             # human-readable

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "skipped": self.skipped,
            "reasons": list(self.reasons),
            "reason": self.reason,
        }


def is_skip_day(
    d: date | str,
    calendar: SkipCalendar,
    trading_days: set[date] | None = None,
) -> SkipDay:
    """Is ``d`` a tail-risk skip day under ``calendar``?

    - ``fomc``: ``d`` is in ``calendar.fomc_dates`` (announcement days).
    - ``opex``: ``d`` is the month's expiration day per
      ``calendar.opex_rule`` ("third_friday" default; "third_wednesday"
      supported — see the discrepancy note in the module docstring).
    - ``month_end``: with ``trading_days`` supplied, ``d`` is the last
      *session* of its calendar month; without it, ``d`` is the calendar
      month's last day — a documented approximation (flags weekends and
      holidays as month-end, since no session calendar is available).

    Pure calendar read: no data, no look-ahead, no fitted parameters.
    """
    day = _as_date(d, "d")
    iso = day.isoformat()
    reasons: list[str] = []

    if day in calendar.fomc_dates:
        reasons.append("fomc")

    if _opex_date(day.year, day.month, calendar.opex_rule) == day:
        reasons.append("opex")

    if calendar.month_end:
        if trading_days is not None:
            sessions = sorted(s for s in trading_days
                              if s.year == day.year and s.month == day.month)
            if sessions and day == sessions[-1]:
                reasons.append("month_end")
        else:
            last_day = _calendar.monthrange(day.year, day.month)[1]
            if day.day == last_day:
                reasons.append("month_end")

    skipped = bool(reasons)
    if not skipped:
        checked = ", ".join(r for r in _SKIP_REASONS
                            if r != "month_end" or calendar.month_end)
        reason = (f"not a skip day: {iso} has no tail-risk calendar event "
                  f"(checked: {checked}).")
    else:
        labels = {"fomc": "an FOMC announcement date",
                  "opex": f"monthly options expiration "
                          f"({calendar.opex_rule.replace('_', ' ')})",
                  "month_end": "the last trading day of the month"
                  if trading_days is not None else
                  "the calendar month-end (no session calendar supplied — "
                  "approximation, may be a weekend/holiday)"}
        reason = (f"skip day ({', '.join(reasons)}): {iso} is "
                  + "; ".join(labels[r] for r in reasons)
                  + " — short-premium tail-risk day, condition research "
                    "on it; not a live-trading rule.")

    return SkipDay(date=iso, skipped=skipped, reasons=reasons, reason=reason)
