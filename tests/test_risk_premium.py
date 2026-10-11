"""Tests for the short-premium risk primitives (trade_risk.premium)."""

import dataclasses
import math

import pytest

from trade_risk.premium import (
    PremiumRiskProfile,
    credit_stop,
    defined_risk_max_loss,
    premium_profile,
    premium_size,
)


def test_credit_stop_returns_credit():
    # Hand-computed: the stop IS the credit. No arithmetic, no tuning.
    assert credit_stop(20.0) == 20.0
    assert credit_stop(0.40) == 0.40
    assert credit_stop(13.85) == 13.85


@pytest.mark.parametrize("bad", [0.0, -5.0, -0.01, math.nan, math.inf, -math.inf])
def test_credit_stop_rejects_non_positive_or_non_finite(bad):
    with pytest.raises(ValueError):
        credit_stop(bad)


def test_credit_stop_rejects_non_numbers():
    with pytest.raises(ValueError):
        credit_stop("20.0")
    with pytest.raises(ValueError):
        credit_stop(None)


def test_defined_risk_max_loss_hand_computed():
    # Worked example from the module docstring: $20 credit on 50-wide
    # wings -> structural max loss $30/contract.
    assert defined_risk_max_loss(50.0, 20.0) == 30.0
    assert defined_risk_max_loss(20.0, 3.5) == 16.5
    assert defined_risk_max_loss(25.0, 7.0) == 18.0


@pytest.mark.parametrize(
    "wing, credit",
    [
        (20.0, 20.0),   # wings don't cover the credit: degenerate
        (15.0, 20.0),   # wings narrower than credit: not a spread
        (0.0, 20.0),    # non-positive wing
        (-50.0, 20.0),  # negative wing
        (50.0, 0.0),    # non-positive credit
        (50.0, -20.0),  # negative credit
        (math.nan, 20.0),
        (50.0, math.inf),
    ],
)
def test_defined_risk_max_loss_rejects_degenerate(wing, credit):
    with pytest.raises(ValueError):
        defined_risk_max_loss(wing, credit)


def test_premium_size_hand_computed():
    # $100k account, 1% risk, $20 credit -> risk budget $1000 -> 50 contracts.
    assert premium_size(100_000.0, 0.01, 20.0) == 50
    # $10k account, 50% risk, $20 credit -> $5000 / $20 = 250.
    assert premium_size(10_000.0, 0.5, 20.0) == 250
    # Full-account risk is allowed (caller's responsibility), still floored.
    assert premium_size(10_000.0, 1.0, 20.0) == 500


def test_premium_size_never_rounds_up():
    # $5000 risk budget / $30 credit = 166.67 -> 166, never 167.
    assert premium_size(10_000.0, 0.5, 30.0) == 166
    # $1000 / $300 = 3.33 -> 3.
    assert premium_size(100_000.0, 0.01, 300.0) == 3


def test_premium_size_zero_when_unaffordable():
    # $50 risk budget can't buy one $200-credit contract -> 0, not an error.
    assert premium_size(100.0, 0.5, 200.0) == 0
    # Zero risk fraction -> zero contracts, valid input.
    assert premium_size(100_000.0, 0.0, 20.0) == 0


@pytest.mark.parametrize(
    "account, risk_pct, credit",
    [
        (0.0, 0.01, 20.0),      # non-positive account
        (-100.0, 0.01, 20.0),
        (100_000.0, 1.5, 20.0),  # risk fraction > 1
        (100_000.0, -0.1, 20.0),  # negative risk fraction
        (100_000.0, math.nan, 20.0),
        (100_000.0, 0.01, 0.0),   # non-positive credit
        (100_000.0, 0.01, -20.0),
        (100_000.0, 0.01, math.inf),
        (math.inf, 0.01, 20.0),
    ],
)
def test_premium_size_rejects_bad_inputs(account, risk_pct, credit):
    with pytest.raises(ValueError):
        premium_size(account, risk_pct, credit)


def test_premium_size_returns_int():
    n = premium_size(100_000.0, 0.01, 20.0)
    assert isinstance(n, int)


def test_profile_bundles_validated_answers():
    p = premium_profile(20.0, 50.0, 10_000.0, 0.5)
    assert isinstance(p, PremiumRiskProfile)
    assert p.credit == 20.0
    assert p.stop_distance == 20.0      # stop IS the credit
    assert p.max_loss == 30.0           # 50 - 20 structural cap
    assert p.contracts == 250           # floor(5000 / 20)
    assert "$20.00" in p.reason
    assert "250" in p.reason


def test_profile_is_frozen():
    p = premium_profile(20.0, 50.0, 10_000.0, 0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.contracts = 999


def test_profile_to_dict_contract():
    p = premium_profile(20.0, 50.0, 10_000.0, 0.5)
    d = p.to_dict()
    assert d == {
        "credit": 20.0,
        "stop_distance": 20.0,
        "max_loss": 30.0,
        "contracts": 250,
        "reason": p.reason,
    }


def test_profile_propagates_validation():
    with pytest.raises(ValueError):
        premium_profile(0.0, 50.0, 10_000.0, 0.5)     # bad credit
    with pytest.raises(ValueError):
        premium_profile(20.0, 20.0, 10_000.0, 0.5)    # degenerate wings
    with pytest.raises(ValueError):
        premium_profile(20.0, 50.0, -1.0, 0.5)        # bad account
    with pytest.raises(ValueError):
        premium_profile(20.0, 50.0, 10_000.0, 2.0)    # bad risk fraction
