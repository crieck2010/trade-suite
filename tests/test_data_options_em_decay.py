"""Tests for the EM-decay entry trigger (trade_data_options.em_decay)."""

from datetime import date, datetime, timezone

import pytest

from trade_data_options.em_decay import (
    HYPOTHESIS_THRESHOLD,
    DecayTrigger,
    decay_trigger,
    em_decay,
    em_decay_from_expected_move,
)
from trade_data_options.expected_move import ExpectedMove

NOW = datetime(2026, 10, 11, 14, 30, tzinfo=timezone.utc)


def _opening(em_points: float = 12.0) -> ExpectedMove:
    return ExpectedMove(
        underlying="SPX",
        expiry=date(2026, 10, 11),
        atm_strike=7700.0,
        call_price=6.2,
        put_price=5.8,
        em_points=em_points,
        em_pct=em_points / 7700.0,
        band_1_low=7700.0 - em_points,
        band_1_high=7700.0 + em_points,
        band_2_low=7700.0 - 2 * em_points,
        band_2_high=7700.0 + 2 * em_points,
        as_of=NOW,
        price_source="mid",
        data_delayed=False,
    )


# --- hand-computed decay fractions -----------------------------------------

def test_exact_83_percent_triggers():
    # 52.0 + 31.0 = 83.0; 83.0 / 100.0 == 0.83 exactly -> triggered
    assert em_decay(100.0, 52.0, 31.0) == pytest.approx(0.83)
    trig = decay_trigger(100.0, 52.0, 31.0, as_of=NOW)
    assert trig.decay_pct <= 0.83
    assert trig.triggered is True
    assert trig.threshold == HYPOTHESIS_THRESHOLD == 0.83


def test_no_decay_is_full_premium():
    assert em_decay(20.0, 11.0, 9.0) == pytest.approx(1.0)
    trig = decay_trigger(20.0, 11.0, 9.0, as_of=NOW)
    assert trig.triggered is False


def test_full_decay_is_zero():
    assert em_decay(20.0, 0.0, 0.0) == pytest.approx(0.0)
    assert decay_trigger(20.0, 0.0, 0.0, as_of=NOW).triggered is True


def test_threshold_boundary():
    # 8301/10000 = 0.8301 > 0.83 -> no trigger; 8299/10000 = 0.8299 -> trigger
    assert decay_trigger(10000.0, 5000.0, 3301.0, as_of=NOW).triggered is False
    assert decay_trigger(10000.0, 5000.0, 3299.0, as_of=NOW).triggered is True


def test_custom_threshold_override():
    trig = decay_trigger(100.0, 52.0, 31.0, threshold=0.80, as_of=NOW)
    assert trig.threshold == 0.80
    assert trig.triggered is False  # 0.83 > 0.80


# --- ExpectedMove integration ----------------------------------------------

def test_from_expected_move():
    opening = _opening(em_points=12.0)
    # current straddle 9.96 -> 9.96/12.0 = 0.83
    assert em_decay_from_expected_move(opening, 5.10, 4.86) == pytest.approx(0.83)


def test_from_expected_move_rejects_wrong_type():
    with pytest.raises(ValueError):
        em_decay_from_expected_move({"em_points": 12.0}, 5.0, 5.0)


# --- DecayTrigger validation ------------------------------------------------

def test_trigger_normalizes_naive_as_of_to_utc():
    naive = datetime(2026, 10, 11, 14, 30)
    trig = DecayTrigger(decay_pct=0.5, as_of=naive)
    assert trig.as_of.tzinfo == timezone.utc


def test_trigger_rejects_bad_threshold():
    for bad in (0.0, -0.1, 1.5, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            DecayTrigger(decay_pct=0.5, as_of=NOW, threshold=bad)


def test_trigger_rejects_bad_decay_pct():
    for bad in (-0.1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            DecayTrigger(decay_pct=bad, as_of=NOW)


def test_trigger_rejects_non_datetime_as_of():
    with pytest.raises(TypeError):
        DecayTrigger(decay_pct=0.5, as_of="2026-10-11")


# --- input validation ---------------------------------------------------------

@pytest.mark.parametrize("bad", [0.0, -10.0, float("nan"), float("inf"), "12"])
def test_em_decay_rejects_bad_opening_em(bad):
    with pytest.raises(ValueError):
        em_decay(bad, 5.0, 5.0)


@pytest.mark.parametrize("bad", [-0.01, float("nan"), float("inf")])
def test_em_decay_rejects_bad_quotes(bad):
    with pytest.raises(ValueError):
        em_decay(10.0, bad, 5.0)
    with pytest.raises(ValueError):
        em_decay(10.0, 5.0, bad)


def test_decay_trigger_validates_before_trigger():
    with pytest.raises(ValueError):
        decay_trigger(0.0, 5.0, 5.0, as_of=NOW)
