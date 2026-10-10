"""DON-20/10-ATR: pre-registered Donchian breakout swing system.

Trial 1 of 1, pre-registered 2026-09-26 (see
docs/validation/donchian-20-10/PRE-REGISTRATION.md — frozen spec; this module
implements it exactly, no tuning).

Long/flat Donchian trend system on liquid large-caps: buy 20-day closing highs,
exit on 10-day closing lows or a 2.5xATR(20) trailing stop, risking 1% of
equity per trade (position value capped at 10% of equity, at most 20 concurrent
positions). Signals are computed on the daily close; the backtest engine fills
at the next bar's open (no lookahead).

Architecture: pure per-bar *features* (no state) + a stateful strategy that
owns the flat/holding state machine per symbol. The strategy tracks its own
intended positions so the 20-position cap and momentum ranking are enforced at
signal time; exits for non-held symbols are harmless no-ops at the engine
(``target 0 - position 0 = no order``).

Validation outcome (2026-09-26): **KILLED** — one pre-registered trial
through the walk-forward overfit gates failed 2 of 5 (median OOS Sharpe 0.87
< 1.0; OOS max drawdown −40.2% > 15% limit). Not viable; not registered for
agent use. See docs/validation/donchian-20-10/.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Signal, SignalAction, Strategy


# ---------------------------------------------------------------------------
# config (pre-registered values — changing these is a new trial)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DonchianSwingConfig:
    """Frozen parameters for trial 1. Defaults are the pre-registered spec."""

    entry_window: int = 20        # Donchian entry channel (prior bars)
    exit_window: int = 10         # Donchian exit channel (prior bars)
    atr_period: int = 20          # Wilder ATR period
    stop_multiple: float = 2.5    # trailing stop = stop_multiple * ATR
    risk_per_trade: float = 0.01  # fraction of equity risked per position
    max_position_pct: float = 0.10  # cap: position value <= 10% of equity
    max_positions: int = 20       # cap: concurrent positions
    warmup_bars: int = 21         # no signals before this bar index

    def as_dict(self) -> dict:
        return {
            "entry_window": self.entry_window,
            "exit_window": self.exit_window,
            "atr_period": self.atr_period,
            "stop_multiple": self.stop_multiple,
            "risk_per_trade": self.risk_per_trade,
            "max_position_pct": self.max_position_pct,
            "max_positions": self.max_positions,
            "warmup_bars": self.warmup_bars,
        }


# ---------------------------------------------------------------------------
# pure indicators (no state; unit-testable)
# ---------------------------------------------------------------------------

def true_range(high: float, low: float, prev_close: float | None) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def wilder_atr(bars: list[dict], n: int) -> list[float | None]:
    """Wilder's ATR: seed with mean of first ``n`` true ranges, then smooth.

    ``None`` before index ``n - 1``. Bar dicts need high/low/close.
    """
    out: list[float | None] = [None] * len(bars)
    if len(bars) < n or n < 1:
        return out
    trs = []
    prev_close = None
    for b in bars:
        trs.append(true_range(b["high"], b["low"], prev_close))
        prev_close = b["close"]
    atr = sum(trs[:n]) / n
    out[n - 1] = atr
    for i in range(n, len(bars)):
        atr = (atr * (n - 1) + trs[i]) / n
        out[i] = atr
    return out


def donchian_high(highs: list[float], i: int, n: int) -> float | None:
    """Highest high of the ``n`` bars strictly before bar ``i``."""
    if i < n:
        return None
    return max(highs[i - n:i])


def donchian_low(lows: list[float], i: int, n: int) -> float | None:
    """Lowest low of the ``n`` bars strictly before bar ``i``."""
    if i < n:
        return None
    return min(lows[i - n:i])


def target_equity_fraction(atr: float, close: float,
                           config: DonchianSwingConfig) -> float:
    """Equity fraction for a new position: risk ``risk_per_trade`` of equity
    against a ``stop_multiple * ATR`` adverse move, capped at
    ``max_position_pct``. Returns 0.0 when inputs are unusable."""
    if atr is None or atr <= 0 or close is None or close <= 0:
        return 0.0
    stop_distance_pct = config.stop_multiple * atr / close
    if stop_distance_pct <= 0:
        return 0.0
    return min(config.max_position_pct, config.risk_per_trade / stop_distance_pct)


def compute_features(bars: list[dict],
                     config: DonchianSwingConfig) -> list[dict]:
    """Per-bar features for one symbol's bar list (chronological dicts with
    date/open/high/low/close). Pure function of past-and-present bars only."""
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    closes = [b["close"] for b in bars]
    atr = wilder_atr(bars, config.atr_period)
    out = []
    for i, b in enumerate(bars):
        mom20 = (closes[i] / closes[i - 20] - 1.0) if i >= 20 and closes[i - 20] > 0 else None
        out.append({
            "date": b["date"],
            "close": closes[i],
            "dh_entry": donchian_high(highs, i, config.entry_window),
            "dl_exit": donchian_low(lows, i, config.exit_window),
            "atr": atr[i],
            "momentum20": mom20,
        })
    return out


# ---------------------------------------------------------------------------
# strategy (stateful; owns the flat/holding machine per symbol)
# ---------------------------------------------------------------------------

class DonchianSwingStrategy(Strategy):
    """Pre-registered DON-20/10-ATR implementation.

    ``features`` maps symbol -> per-bar feature dicts from
    :func:`compute_features` (aligned to that symbol's own bar list).
    """

    name = "donchian_swing"
    family = "trend"
    description = (
        "Pre-registered Donchian-20/10 breakout, long/flat: buy 20-day closing "
        "highs, exit on 10-day closing lows or a 2.5xATR(20) trailing stop; "
        "1% equity risk per trade, 10% position cap, 20 positions max. "
        "Trial 1 of 1 (2026-09-26)."
    )
    DEFAULT_PARAMS: dict = {
        "entry_window": 20,
        "exit_window": 10,
        "atr_period": 20,
        "stop_multiple": 2.5,
        "risk_per_trade": 0.01,
        "max_position_pct": 0.10,
        "max_positions": 20,
        "warmup_bars": 21,
    }

    def __init__(self, symbols: list[str], features: dict[str, list[dict]] | None = None,
                 **params) -> None:
        super().__init__(symbols, **params)
        self.config = DonchianSwingConfig(
            entry_window=self.params["entry_window"],
            exit_window=self.params["exit_window"],
            atr_period=self.params["atr_period"],
            stop_multiple=self.params["stop_multiple"],
            risk_per_trade=self.params["risk_per_trade"],
            max_position_pct=self.params["max_position_pct"],
            max_positions=self.params["max_positions"],
            warmup_bars=self.params["warmup_bars"],
        )
        self.features = features or {}
        # per-symbol state: {"holding": bool, "stop": float|None, "idx": int}
        # idx tracks consumption of the feature stream per symbol.
        self._state: dict[str, dict] = {
            s: {"holding": False, "stop": None, "idx": 0} for s in self.symbols
        }

    @property
    def warmup_bars(self) -> int:  # noqa: D102
        return int(self.params["warmup_bars"])

    def _row(self, symbol: str, date: str) -> dict | None:
        feats = self.features.get(symbol)
        st = self._state[symbol]
        # advance the per-symbol cursor to this date (bars may be sparse)
        while st["idx"] < len(feats) and feats[st["idx"]]["date"] < date:
            st["idx"] += 1
        if st["idx"] < len(feats) and feats[st["idx"]]["date"] == date:
            return feats[st["idx"]]
        return None

    def on_bar(self, timestamp, bars: dict) -> list[Signal]:
        cfg = self.config
        date = timestamp.date().isoformat()
        signals: list[Signal] = []

        # pass 1: exits (always honored, no cap applies)
        for symbol in bars:
            if symbol not in self._state:
                continue
            st = self._state[symbol]
            if not st["holding"]:
                continue
            row = self._row(symbol, date)
            if row is None:
                continue
            i = self._state[symbol]["idx"]
            if i < cfg.warmup_bars:
                continue
            close = row["close"]
            # trail the stop up only, never down
            if row["atr"] is not None and row["atr"] > 0:
                st["stop"] = max(st["stop"], close - cfg.stop_multiple * row["atr"])
            if (row["dl_exit"] is not None and close < row["dl_exit"]) or \
               (st["stop"] is not None and close < st["stop"]):
                signals.append(Signal(symbol, timestamp, SignalAction.EXIT))
                st["holding"] = False
                st["stop"] = None

        # pass 2: entries, ranked, capped
        holding = {s for s, st in self._state.items() if st["holding"]}
        free_slots = cfg.max_positions - len(holding)
        candidates = []
        if free_slots > 0:
            for symbol in bars:
                if symbol not in self._state or symbol in holding:
                    continue
                row = self._row(symbol, date)
                if row is None:
                    continue
                i = self._state[symbol]["idx"]
                if i < cfg.warmup_bars:
                    continue
                if row["dh_entry"] is None or row["atr"] is None or row["atr"] <= 0:
                    continue
                if row["close"] > row["dh_entry"]:
                    mom = row["momentum20"] if row["momentum20"] is not None else -1.0
                    candidates.append((mom, symbol, row))
        # rank by 20-day momentum desc, ties alphabetical (deterministic)
        candidates.sort(key=lambda c: (-c[0], c[1]))
        for mom, symbol, row in candidates[:free_slots]:
            frac = target_equity_fraction(row["atr"], row["close"], cfg)
            if frac <= 0:
                continue
            signals.append(Signal(symbol, timestamp, SignalAction.LONG, strength=frac))
            st = self._state[symbol]
            st["holding"] = True
            st["stop"] = row["close"] - cfg.stop_multiple * row["atr"]
        return signals
