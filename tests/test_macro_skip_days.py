"""Tests for trade_macro.skip_days — hand-computed calendar cases."""

from __future__ import annotations


from datetime import date

import pytest

from trade_macro.skip_days import (
    SkipCalendar,
    default_skip_calendar,
    is_skip_day,
)


def cal(**kw):
    kw.setdefault("fomc_dates", frozenset())
    return SkipCalendar(**kw)


def test_default_calendar_ships_23_fomc_dates():
    c = default_skip_calendar()
    assert len(c.fomc_dates) == 23
    assert date(2026, 10, 28) in c.fomc_dates   # next upcoming FOMC
    assert date(2025, 12, 10) in c.fomc_dates
    assert c.opex_rule == "third_friday"
    assert c.month_end is True


def test_known_fomc_date_skipped():
    # 2026-10-28: FOMC announcement day. Oct 2026 third Friday is the 16th,
    # calendar month-end is the 31st — so "fomc" is the only reason.
    r = is_skip_day(date(2026, 10, 28), default_skip_calendar())
    assert r.skipped is True
    assert r.reasons == ["fomc"]
    assert "FOMC" in r.reason


def test_day_before_fomc_not_skipped():
    # 2026-10-27: no fomc, not third Friday (16th), not month-end.
    r = is_skip_day("2026-10-27", default_skip_calendar())
    assert r.skipped is False
    assert r.reasons == []
    assert r.date == "2026-10-27"


def test_opex_third_friday():
    # June 2026: 1st is a Monday -> Fridays 5/12/19. Third = 19th.
    r = is_skip_day(date(2026, 6, 19), cal())
    assert r.skipped is True
    assert r.reasons == ["opex"]
    # The Friday before is not OpEx.
    assert is_skip_day(date(2026, 6, 12), cal()).skipped is False


def test_opex_year_boundary():
    # Dec 2026: 1st is a Tuesday -> Fridays 4/11/18. Third = 18th.
    assert is_skip_day(date(2026, 12, 18), cal()).reasons == ["opex"]
    # Jan 2027: 1st is a Friday -> Fridays 1/8/15. Third = 15th.
    assert is_skip_day(date(2027, 1, 15), cal()).reasons == ["opex"]
    # Dec 31 / Jan 1 are not OpEx under the Friday rule.
    assert is_skip_day(date(2026, 12, 31), cal(month_end=False)).skipped is False


def test_month_end_with_trading_days():
    # Oct 2026 sessions ending Friday the 30th (31st is a Saturday).
    sessions = {date(2026, 10, d) for d in (28, 29, 30)}
    r = is_skip_day(date(2026, 10, 30), cal(), trading_days=sessions)
    assert r.skipped is True
    assert r.reasons == ["month_end"]
    assert is_skip_day(date(2026, 10, 29), cal(),
                       trading_days=sessions).skipped is False


def test_month_end_without_trading_days_is_calendar_approximation():
    # No session calendar: flags the calendar month-end (Sat 2026-10-31),
    # documented approximation — and does NOT flag Friday the 30th.
    assert is_skip_day(date(2026, 10, 31), cal()).reasons == ["month_end"]
    assert is_skip_day(date(2026, 10, 30), cal()).skipped is False


def test_month_end_can_be_disabled():
    r = is_skip_day(date(2026, 10, 31), cal(month_end=False))
    assert r.skipped is False


def test_wednesday_friday_discrepancy():
    # Oct 2026: third Wednesday = 21st, third Friday = 16th.
    # Default (third_friday): Wednesday is NOT a skip day...
    assert is_skip_day(date(2026, 10, 21), cal()).skipped is False
    # ...but the video's claim is testable as stated via configuration.
    wed = cal(opex_rule="third_wednesday")
    r = is_skip_day(date(2026, 10, 21), wed)
    assert r.skipped is True
    assert r.reasons == ["opex"]
    assert "third wednesday" in r.reason
    # Under the Wednesday rule, the third Friday is not OpEx.
    assert is_skip_day(date(2026, 10, 16), wed).skipped is False


def test_multiple_reasons_in_fixed_order():
    # Synthetic: FOMC list containing a third-Friday OpEx day.
    c = SkipCalendar(fomc_dates=frozenset({date(2026, 6, 19)}))
    r = is_skip_day(date(2026, 6, 19), c)
    assert r.skipped is True
    assert r.reasons == ["fomc", "opex"]


def test_invalid_opex_rule_raises():
    with pytest.raises(ValueError, match="opex_rule"):
        SkipCalendar(fomc_dates=frozenset(), opex_rule="second_monday")


def test_iso_string_input():
    r = is_skip_day("2026-03-18", default_skip_calendar())
    assert r.skipped is True and r.reasons == ["fomc"]


def test_bad_date_raises():
    with pytest.raises(ValueError, match="expected date or ISO"):
        is_skip_day("not-a-date", cal())


def test_to_dict_round_trip():
    r = is_skip_day(date(2026, 10, 28), default_skip_calendar())
    d = r.to_dict()
    assert d == {"date": "2026-10-28", "skipped": True,
                 "reasons": ["fomc"], "reason": r.reason}
