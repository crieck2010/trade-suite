"""Seeded demo scenarios. Deterministic: same seed in -> same numbers out.

1. ``demo_drift_breach`` — a 5-stock portfolio that starts delta-neutral and
   drifts into a delta breach plus a gross-cap breach; shows exposures
   before/after and the proposals the loop emits.
2. ``demo_vol_regime_shift`` — calm returns turn turbulent; the vol-regime
   rule proposes a scale-down.
3. ``demo_stale_data`` — market prices 3 hours old: the kill-switch fires
   and the cycle emits zero proposals.
"""

from __future__ import annotations

import datetime as _dt
import random

from .presets import DEFAULT_CONFIG


def _mk(seed: int):
    return random.Random(seed)


def demo_drift_breach(seed: int = 7) -> tuple[dict, dict, dict]:
    rng = _mk(seed)
    symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"]
    # Start: long tech, short SPY as a rough hedge — near delta-neutral.
    start_prices = {"AAPL": 230.0, "MSFT": 420.0, "NVDA": 130.0,
                    "TSLA": 250.0, "SPY": 590.0}
    positions = [
        {"symbol": "AAPL", "qty": 200.0},
        {"symbol": "MSFT", "qty": 100.0},
        {"symbol": "NVDA", "qty": 300.0},
        {"symbol": "TSLA", "qty": 150.0},
        {"symbol": "SPY", "qty": -230.0},
    ]
    # Tech rallies (drifts long), SPY lags: the hedge stops covering.
    end_prices = {
        "AAPL": start_prices["AAPL"] * (1 + 0.10 + rng.uniform(-0.01, 0.01)),
        "MSFT": start_prices["MSFT"] * (1 + 0.08 + rng.uniform(-0.01, 0.01)),
        "NVDA": start_prices["NVDA"] * (1 + 0.25 + rng.uniform(-0.02, 0.02)),
        "TSLA": start_prices["TSLA"] * (1 + 0.05 + rng.uniform(-0.01, 0.01)),
        "SPY": start_prices["SPY"] * (1 + 0.02),
    }
    config = dict(DEFAULT_CONFIG)
    config["equity"] = 100_000.0
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    portfolio_state = {"positions": positions, "equity": 100_000.0,
                       "peak_equity": 102_000.0}
    market_state = {"prices": end_prices, "as_of": now.isoformat(),
                    "start_prices": start_prices}
    return portfolio_state, market_state, config


def demo_vol_regime_shift(seed: int = 7, n: int = 126) -> tuple[dict, dict, dict]:
    rng = _mk(seed + 1)
    # First half calm (1% daily vol), second half turbulent (3.5%).
    returns = ([rng.gauss(0.0004, 0.01) for _ in range(n // 2)]
               + [rng.gauss(-0.0005, 0.035) for _ in range(n - n // 2)])
    positions = [{"symbol": "SPY", "qty": 300.0}]
    config = dict(DEFAULT_CONFIG)
    config["equity"] = 100_000.0
    config["hysteresis_band"] = 2.00  # don't trip the delta rule; isolate vol
    portfolio_state = {"positions": positions, "equity": 100_000.0,
                       "peak_equity": 105_000.0}
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    market_state = {"prices": {"SPY": 590.0}, "as_of": now.isoformat(),
                    "portfolio_returns": returns}
    return portfolio_state, market_state, config


def demo_stale_data(seed: int = 7) -> tuple[dict, dict, dict]:
    portfolio_state, market_state, config = demo_drift_breach(seed)
    stale = (_dt.datetime.now(tz=_dt.timezone.utc)
             - _dt.timedelta(hours=3))
    market_state = dict(market_state, as_of=stale.isoformat())
    return portfolio_state, market_state, config
