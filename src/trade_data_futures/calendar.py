"""Expiry calendars: generate listed contract months for a root.

A calendar walks a root's cycle (quarterly, monthly, grains, ...) and
produces :class:`FuturesContract`s with approximate last-trading dates.
Expiry *dates* are conventional approximations (documented per rule) --
good enough for roll scheduling in research, not for settlement
accounting. Pass explicit dates when exactness matters.
"""

from __future__ import annotations

import calendar as _calendar
from datetime import date

from .exceptions import UnknownRootError
from .models import ContractSpec, FuturesContract
from .specs import get_spec


def _third_friday(year: int, month: int) -> date:
    month_cal = _calendar.monthcalendar(year, month)
    fridays = [week[_calendar.FRIDAY] for week in month_cal if week[_calendar.FRIDAY]]
    return date(year, month, fridays[2])


def approximate_expiry(root: str, year: int, month: int) -> date:
    """Conventional last-trading-day approximation for a contract month.

    * Equity index / FX / rates (CME, CBOT): third Friday of the contract month.
    * Energy / metals / grains: a few business days before month start is the
      exchange norm; we use the last business day of the *prior* month as a
      simple, documented stand-in.
    """
    spec = get_spec(root)
    if spec.exchange in ("CME", "CBOT"):
        return _third_friday(year, month)
    # Prior-month last business day.
    first = date(year, month, 1)
    day = first - _one_day()
    while day.weekday() >= 5:
        day -= _one_day()
    return day


def _one_day():
    from datetime import timedelta

    return timedelta(days=1)


class ContractCalendar:
    """Generate contract months for a root from its reference spec."""

    def __init__(self, spec: ContractSpec | None = None, root: str | None = None) -> None:
        if spec is None:
            if root is None:
                raise ValueError("pass spec= or root=")
            spec = get_spec(root)
        self.spec = spec

    @property
    def root(self) -> str:
        return self.spec.root

    def contract_months(self, year: int) -> list[tuple[int, int]]:
        """``(year, month)`` pairs listed in ``year``, ascending."""
        return [(year, m) for m in self.spec.cycle_months]

    def upcoming(self, n: int = 12, from_date: date | None = None) -> list[FuturesContract]:
        """Next ``n`` contracts at or after ``from_date`` (default today).

        Contracts whose approximate expiry already passed are skipped.
        """
        from_date = from_date or date.today()
        out: list[FuturesContract] = []
        year, month = from_date.year, from_date.month
        while len(out) < n:
            for m in self.spec.cycle_months:
                if (year, m) < (from_date.year, from_date.month):
                    continue
                try:
                    expiry = approximate_expiry(self.root, year, m)
                except UnknownRootError:
                    expiry = None
                if expiry is not None and expiry < from_date:
                    continue
                out.append(
                    FuturesContract(root=self.root, year=year, month=m, expiry=expiry, spec=self.spec)
                )
                if len(out) == n:
                    break
            year += 1
        return out

    def front_month(self, from_date: date | None = None) -> FuturesContract:
        """Nearest listed contract."""
        return self.upcoming(1, from_date)[0]
