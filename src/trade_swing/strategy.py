"""Swing trend-following strategy: fast/slow MA cross + ATR trailing stop.

Long/flat only. Entry on fast-MA crossing above slow-MA; exit on cross-under
OR on a close below the ATR trailing stop. Every signal is computed from
data available at that bar's close — no look-ahead, ever.

Bar contract (plain dicts)::
    {"date": "YYYY-MM-DD", "open": ..., "high": ..., "low": ...,
     "close": ..., "volume": ...}

Signal contract (one dict per bar, from the first bar where every
indicator is defined)::
    {"date": ..., "signal": "enter_long" | "exit_long" | "flat",
     "fast_ma": ..., "slow_ma": ..., "atr": ...,
     "stop": ... | None, "in_position": bool,
     "conviction_gated": bool}
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# indicators (pure)
# ---------------------------------------------------------------------------

def simple_ma(values: list[float], n: int) -> list[float | None]:
    """Simple moving average; ``None`` for the ``n - 1`` warm-up bars."""
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    out: list[float | None] = [None] * len(values)
    window = 0.0
    for i, v in enumerate(values):
        window += v
        if i >= n:
            window -= values[i - n]
        if i >= n - 1:
            out[i] = window / n
    return out


def true_range(bars: list[dict]) -> list[float]:
    """Wilder's true range per bar. ``tr[0] = high - low`` (no prior close)."""
    out: list[float] = []
    prev_close: float | None = None
    for b in bars:
        high, low, close = b["high"], b["low"], b["close"]
        if prev_close is None:
            out.append(high - low)
        else:
            out.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        prev_close = close
    return out


def wilder_atr(bars: list[dict], n: int) -> list[float | None]:
    """Wilder's ATR: seed with the mean of the first ``n`` true ranges, then
    ``atr = (atr_prev * (n - 1) + tr) / n``. ``None`` before index ``n - 1``."""
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    tr = true_range(bars)
    out: list[float | None] = [None] * len(bars)
    if len(bars) < n:
        return out
    atr = sum(tr[:n]) / n
    out[n - 1] = atr
    for i in range(n, len(bars)):
        atr = (atr * (n - 1) + tr[i]) / n
        out[i] = atr
    return out


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SwingConfig:
    """Strategy parameters. Defaults are conventions, NOT optimized values.

    Optimizing these on the demo data would BE overfitting — the demo
    exists to prove the gates can pass a trend and fail chop, not to
    discover parameters.
    """
    fast: int = 20
    slow: int = 50
    atr_period: int = 14
    stop_multiple: float = 3.0      # trailing stop = stop_multiple * ATR
    risk_per_trade: float = 0.01    # fraction of equity risked per trade
    max_position_pct: float = 0.25  # cap: position value <= 25% of equity
    regime_min_conviction: float = 30.0  # min trade-regime conviction (0-100)
                                         # to open NEW positions; exits always
                                         # honored. None disables gating.

    def __post_init__(self) -> None:
        if not 0 < self.fast < self.slow:
            raise ValueError(f"need 0 < fast < slow, got {self.fast}, {self.slow}")
        if self.atr_period < 1:
            raise ValueError("atr_period must be >= 1")
        if self.stop_multiple <= 0:
            raise ValueError("stop_multiple must be > 0")
        if not 0 < self.risk_per_trade <= 1:
            raise ValueError("risk_per_trade must be in (0, 1]")
        if not 0 < self.max_position_pct <= 1:
            raise ValueError("max_position_pct must be in (0, 1]")

    def as_dict(self) -> dict:
        return {
            "fast": self.fast, "slow": self.slow, "atr_period": self.atr_period,
            "stop_multiple": self.stop_multiple,
            "risk_per_trade": self.risk_per_trade,
            "max_position_pct": self.max_position_pct,
            "regime_min_conviction": self.regime_min_conviction,
        }


# ---------------------------------------------------------------------------
# signal walk (the single source of truth)
# ---------------------------------------------------------------------------

class _SignalWalk:
    """Stateful signal generator; one instance per symbol.

    The walk is the single source of truth for entries/exits. Both the
    internal backtest loop and the trade-backtest adapter consume the
    intent stream it produces, so trigger logic can never drift between
    engines. Fills are assumed at the *next* bar's open by the engines;
    stop *triggers* are evaluated at bar close — a documented one-bar
    simplification, identical in both paths.

    Re-entry rule: a stop-out while the trend is intact (fast still above
    slow) does NOT require a fresh MA cross to get back in — price
    recovering above the stop level re-enters. Otherwise a single
    noise shake-out would sideline the system for the rest of a trend.
    A cross-down exit clears the re-entry reference (trend broken; wait
    for a genuinely new cross).
    """

    def __init__(self, config: SwingConfig) -> None:
        self.config = config
        self.in_position = False
        # While in position: the trailing stop. After a stop-out: the
        # frozen re-entry reference. None when flat with no reference.
        self.stop: float | None = None

    def step(self, i: int, bar: dict, fast_ma: float | None,
             slow_ma: float | None, atr: float | None,
             prev_fast: float | None, prev_slow: float | None,
             conviction: float | None) -> dict:
        cfg = self.config
        date = bar["date"]
        close = bar["close"]
        signal = "flat"
        gated = False

        cross_up = (fast_ma is not None and slow_ma is not None
                    and prev_fast is not None and prev_slow is not None
                    and fast_ma > slow_ma and prev_fast <= prev_slow)
        cross_down = (fast_ma is not None and slow_ma is not None
                      and prev_fast is not None and prev_slow is not None
                      and fast_ma < slow_ma and prev_fast >= prev_slow)
        trend_intact = (fast_ma is not None and slow_ma is not None
                        and fast_ma > slow_ma)

        if not self.in_position:
            if cross_down:
                self.stop = None  # trend broke; forget any re-entry level
            reenter = (self.stop is not None and trend_intact
                       and close > self.stop)
            if (cross_up or reenter) and atr is not None and atr > 0:
                if (cfg.regime_min_conviction is not None and conviction is not None
                        and conviction < cfg.regime_min_conviction):
                    gated = True  # regime says stand down: no NEW entries
                else:
                    self.in_position = True
                    self.stop = close - cfg.stop_multiple * atr
                    signal = "enter_long"
        else:
            # trail the stop up only, never down
            if atr is not None and atr > 0:
                self.stop = max(self.stop, close - cfg.stop_multiple * atr)
            stop_hit = self.stop is not None and close < self.stop
            if cross_down or stop_hit:
                self.in_position = False
                signal = "exit_long"
                if cross_down:
                    self.stop = None  # trend broke; wait for a fresh cross
                # on a stop-out the stop level is KEPT as the re-entry
                # reference (see class docstring)

        return {
            "date": date,
            "signal": signal,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "atr": atr,
            "stop": self.stop,
            "in_position": self.in_position,
            "conviction_gated": gated,
        }


def generate_signals(bars: list[dict], config: SwingConfig | None = None,
                     convictions: dict[str, float] | None = None) -> list[dict]:
    """Full signal stream for one symbol's bar list.

    ``convictions`` maps date -> trade-regime conviction (0-100); dates
    below ``config.regime_min_conviction`` suppress new entries. The walk
    uses only data available at each bar's close.
    """
    config = config or SwingConfig()
    if len(bars) < config.slow:
        return []
    closes = [b["close"] for b in bars]
    fast = simple_ma(closes, config.fast)
    slow = simple_ma(closes, config.slow)
    atr = wilder_atr(bars, config.atr_period)

    walk = _SignalWalk(config)
    out: list[dict] = []
    start = max(config.slow, config.atr_period)  # need prev MAs for crosses
    for i in range(start, len(bars)):
        conviction = convictions.get(bars[i]["date"]) if convictions else None
        out.append(walk.step(i, bars[i], fast[i], slow[i], atr[i],
                             fast[i - 1], slow[i - 1], conviction))
    return out


class SwingTrendStrategy:
    """Thin wrapper: config + ``signals()``. Keeps the functional core
    importable without instantiating anything."""

    def __init__(self, config: SwingConfig | None = None) -> None:
        self.config = config or SwingConfig()

    def signals(self, bars: list[dict],
                convictions: dict[str, float] | None = None) -> list[dict]:
        return generate_signals(bars, self.config, convictions)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        c = self.config
        return (f"SwingTrendStrategy(fast={c.fast}, slow={c.slow}, "
                f"atr={c.atr_period}, stop_x={c.stop_multiple})")
