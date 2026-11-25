"""Tests for trade_safety.wakeups — event-driven wakeup triggers."""

from __future__ import annotations

import pytest

from trade_safety.wakeups import (
    CrossDirection,
    OrderEventTrigger,
    PriceLevelTrigger,
    SafetyClockTrigger,
    WakeupEngine,
    WakeupKind,
)


def test_price_cross_above_fires_once():
    eng = WakeupEngine()
    eng.add_price_trigger(PriceLevelTrigger("t1", "SPY", 500.0, CrossDirection.ABOVE))
    assert eng.on_price("SPY", 499.0, now=1.0) == []  # baseline only
    events = eng.on_price("SPY", 501.0, now=2.0)
    assert len(events) == 1
    assert events[0].kind is WakeupKind.PRICE_LEVEL
    assert events[0].detail == {"level": 500.0, "price": 501.0, "previous_price": 499.0}
    # one-shot: disarmed after firing
    assert eng.on_price("SPY", 499.0, now=3.0) == []
    assert eng.on_price("SPY", 502.0, now=4.0) == []
    assert "t1" not in eng.armed_ids()


def test_price_no_cross_no_fire():
    eng = WakeupEngine()
    eng.add_price_trigger(PriceLevelTrigger("t1", "SPY", 500.0, CrossDirection.ABOVE))
    eng.on_price("SPY", 490.0, now=1.0)
    assert eng.on_price("SPY", 495.0, now=2.0) == []
    assert eng.on_price("SPY", 500.0, now=3.0) == []  # touching is not crossing
    assert "t1" in eng.armed_ids()


def test_price_cross_below_and_wrong_symbol_ignored():
    eng = WakeupEngine()
    eng.add_price_trigger(PriceLevelTrigger("stop", "SPY", 500.0, CrossDirection.BELOW))
    eng.on_price("QQQ", 100.0, now=1.0)  # different symbol: no baseline for SPY
    assert eng.on_price("SPY", 505.0, now=2.0) == []  # SPY baseline
    events = eng.on_price("SPY", 498.0, now=3.0)
    assert len(events) == 1 and events[0].trigger_id == "stop"


def test_price_repeat_trigger_refires_on_each_cross():
    eng = WakeupEngine()
    eng.add_price_trigger(
        PriceLevelTrigger("t1", "SPY", 500.0, CrossDirection.EITHER, repeat=True)
    )
    eng.on_price("SPY", 499.0, now=1.0)
    assert len(eng.on_price("SPY", 501.0, now=2.0)) == 1
    assert len(eng.on_price("SPY", 499.0, now=3.0)) == 1
    assert "t1" in eng.armed_ids()


def test_price_fire_if_beyond_fires_on_first_observation():
    eng = WakeupEngine()
    eng.add_price_trigger(
        PriceLevelTrigger("stop", "SPY", 500.0, CrossDirection.BELOW, fire_if_beyond=True)
    )
    events = eng.on_price("SPY", 480.0, now=1.0)  # already through the stop at arm time
    assert len(events) == 1


def test_price_baseline_never_fires_without_fire_if_beyond():
    eng = WakeupEngine()
    eng.add_price_trigger(PriceLevelTrigger("stop", "SPY", 500.0, CrossDirection.BELOW))
    assert eng.on_price("SPY", 480.0, now=1.0) == []


def test_order_event_fires_on_transition_into_watched_status():
    eng = WakeupEngine()
    eng.add_order_trigger(OrderEventTrigger("w1", "ord-1", frozenset({"FILLED_ALL", "FAILED"})))
    assert eng.on_order_status("ord-1", "SUBMITTED", now=1.0) == []
    events = eng.on_order_status("ord-1", "FILLED_ALL", now=2.0)
    assert len(events) == 1
    assert events[0].kind is WakeupKind.ORDER_EVENT
    assert events[0].detail["previous_status"] == "SUBMITTED"
    assert "w1" not in eng.armed_ids()


def test_order_event_first_observation_in_set_fires():
    eng = WakeupEngine()
    eng.add_order_trigger(OrderEventTrigger("w1", "ord-1", frozenset({"FILLED"})))
    events = eng.on_order_status("ord-1", "filled", now=1.0)  # case-insensitive
    assert len(events) == 1


def test_order_event_repeat_refires_only_on_new_watched_status():
    eng = WakeupEngine()
    eng.add_order_trigger(
        OrderEventTrigger("w1", "ord-1", frozenset({"FILLED_PART", "FILLED_ALL"}), repeat=True)
    )
    assert len(eng.on_order_status("ord-1", "FILLED_PART", now=1.0)) == 1
    assert eng.on_order_status("ord-1", "FILLED_PART", now=2.0) == []  # no transition
    assert len(eng.on_order_status("ord-1", "FILLED_ALL", now=3.0)) == 1


def test_order_event_trigger_requires_a_status():
    with pytest.raises(ValueError):
        OrderEventTrigger("w1", "ord-1", frozenset())


def test_safety_clock_fires_after_max_sleep():
    eng = WakeupEngine()
    eng.add_clock_trigger(SafetyClockTrigger("c1", 60.0), now=1000.0)
    assert eng.tick(now=1059.0) == []
    events = eng.tick(now=1060.0)
    assert len(events) == 1
    assert events[0].kind is WakeupKind.SAFETY_CLOCK
    assert events[0].detail["slept_s"] == 60.0
    assert eng.tick(now=1200.0) == []  # one-shot, disarmed


def test_safety_clock_repeat_rearms():
    eng = WakeupEngine()
    eng.add_clock_trigger(SafetyClockTrigger("c1", 60.0, repeat=True), now=0.0)
    assert len(eng.tick(now=60.0)) == 1
    assert eng.tick(now=119.0) == []
    assert len(eng.tick(now=120.0)) == 1


def test_safety_clock_requires_positive_sleep():
    with pytest.raises(ValueError):
        SafetyClockTrigger("c1", 0.0)


def test_callback_receives_events_and_remove_disarms():
    seen = []
    eng = WakeupEngine(on_wakeup=seen.append)
    eng.add_price_trigger(PriceLevelTrigger("t1", "SPY", 10.0, CrossDirection.ABOVE))
    eng.on_price("SPY", 9.0, now=1.0)
    eng.on_price("SPY", 11.0, now=2.0)
    assert [e.trigger_id for e in seen] == ["t1"]

    eng.add_clock_trigger(SafetyClockTrigger("c1", 30.0), now=0.0)
    assert eng.remove("c1") is True
    assert eng.tick(now=100.0) == []
    assert eng.remove("nope") is False
