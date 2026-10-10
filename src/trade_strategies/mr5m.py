"""MR-5M: pre-registered 5-minute mean-reversion crypto scalper.

Trial 2 of 2, pre-registered 2026-09-26 (see
docs/validation/mr-5m/PRE-REGISTRATION.md — frozen spec; this module
implements it exactly, no tuning).

Long/flat 5-minute mean reversion on BTC/USD and ETH/USD spot: buy a fresh
cross below -2.0 z (close vs trailing-8h mean in trailing-8h std units) with
10% of equity; exit when z crosses back to >= 0, on a stop at z <= -4.0, or
after 48 bars (4 hours). Signals are computed at bar t's close; the backtest
engine fills at bar t+1's open (no lookahead).

Architecture: pure ``zscore`` (no state; unit-testable) + a stateful
:class:`MR5MScalper` owning the flat/long machine per symbol, the entry bar
counter for the time stop, and an exit-reason log for evidence.

Validation outcome: pending (trial 2). This module is NOT registered for
agent use — registration happens only on a PASS verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite, sqrt

from .base import Signal, SignalAction, SingleAssetStrategy, closes


# ---------------------------------------------------------------------------
# config (pre-registered values — changing these is a new trial)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MR5MConfig:
    """Frozen parameters for trial 2. Defaults are the pre-registered spec."""

    lookback: int = 96          # z-score window, bars (96 x 5m = 8h)
    entry_z: float = 2.0        # enter long on fresh cross below -entry_z
    exit_z: float = 0.0         # exit when z >= exit_z (reversion complete)
    stop_z: float = 4.0         # stop when z <= -stop_z (adverse extension)
    max_hold_bars: int = 48     # time stop, bars (48 x 5m = 4h)
    equity_fraction: float = 0.10  # notional per position, fraction of equity

    def as_dict(self) -> dict:
        return {
            "lookback": self.lookback,
            "entry_z": self.entry_z,
            "exit_z": self.exit_z,
            "stop_z": self.stop_z,
            "max_hold_bars": self.max_hold_bars,
            "equity_fraction": self.equity_fraction,
        }


# ---------------------------------------------------------------------------
# pure indicator (no state; unit-testable)
# ---------------------------------------------------------------------------

def zscore(closes_list: list[float], lookback: int) -> float | None:
    """Z of the last close vs the prior ``lookback`` closes (population std).

    Returns None when there are fewer than ``lookback + 1`` closes, when the
    window has zero variance (flat/maintenance bars), or when the result is
    non-finite. Never raises on bad input — returns None instead.
    """
    if lookback < 1 or len(closes_list) < lookback + 1:
        return None
    window = closes_list[-lookback - 1:-1]
    last = closes_list[-1]
    try:
        mean = sum(window) / lookback
        var = sum((c - mean) ** 2 for c in window) / lookback
    except (TypeError, ValueError):
        return None
    if var <= 0:
        return None
    z = (last - mean) / sqrt(var)
    return z if isfinite(z) else None


# ---------------------------------------------------------------------------
# stateful strategy
# ---------------------------------------------------------------------------

class MR5MScalper(SingleAssetStrategy):
    """Frozen MR-5M implementation. See module docstring + PRE-REGISTRATION.md."""

    name = "mr_5m"
    family = "mean_reversion"
    description = (
        "5-minute crypto mean reversion, long/flat: buy fresh -2σ dips vs the "
        "trailing 8h mean, exit at z>=0, stop at z<=-4, 48-bar time stop."
    )
    DEFAULT_PARAMS = {
        "lookback": 96,
        "entry_z": 2.0,
        "exit_z": 0.0,
        "stop_z": 4.0,
        "max_hold_bars": 48,
        "equity_fraction": 0.10,
    }

    def __init__(self, symbols: list[str], **params) -> None:
        super().__init__(symbols, **params)
        self._bar_no: dict[str, int] = {s: 0 for s in self.symbols}
        self._entry_no: dict[str, int] = {}
        self.exit_log: list[tuple[datetime, str, str]] = []
        """(timestamp, symbol, reason) for every EXIT — evidence, not trading."""

    @property
    def warmup_bars(self) -> int:
        # lookback window + current bar + one prior z for the fresh-cross check
        return self.params["lookback"] + 2

    def on_symbol(self, timestamp: datetime, symbol: str, history: list) -> Signal | None:
        p = self.params
        c = closes(history)
        z = zscore(c, p["lookback"])
        z_prev = zscore(c[:-1], p["lookback"])
        self._bar_no[symbol] += 1
        if z is None or z_prev is None:
            return None
        holding = self._regime.get(symbol, 0) == 1
        target: int | None = None
        reason: str | None = None
        if not holding:
            if z_prev >= -p["entry_z"] and z < -p["entry_z"]:
                target = 1
        else:
            held = self._bar_no[symbol] - self._entry_no[symbol]
            if z >= p["exit_z"]:
                target, reason = 0, "reversion"
            elif z <= -p["stop_z"]:
                target, reason = 0, "stop"
            elif held >= p["max_hold_bars"]:
                target, reason = 0, "time"
        regime = self._transition(symbol, target)
        if regime is None:
            return None
        if regime == 1:
            self._entry_no[symbol] = self._bar_no[symbol]
            return Signal(symbol, timestamp, SignalAction.LONG,
                          strength=p["equity_fraction"])
        self.exit_log.append((timestamp, symbol, reason or "unknown"))
        return Signal(symbol, timestamp, SignalAction.EXIT)
