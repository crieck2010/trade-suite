"""Backtest runner: trade-backtest first, internal fallback second.

PRIMARY PATH — ``trade-backtest`` (when installed). The sibling owns
fills, cash accounting and the equity curve. The call mapping:

- plain bars -> ``trade_backtest.models.Bar`` (UTC datetimes)
- ``generate_signals()`` intent stream -> ``_IntentStrategy`` replays one
  intent per (symbol, timestamp) as ``Signal(LONG|EXIT)``. Trigger logic
  lives ONLY in ``strategy.py`` — it cannot drift between engines.
- ``sizing.atr_position_size`` -> ``_ATRSizer`` (a
  ``trade_backtest.portfolio.PositionSizer``); sized on
  ``portfolio.equity`` at signal time, exactly like the fallback loop.
- ``SimulatedExecutionHandler`` with zero commission/slippage: fills at
  the next bar's open (the sibling's no-look-ahead convention).
- costs are applied POST-HOC by ``costs.apply_costs`` (see below), so the
  cost model is identical whichever engine ran.

FALLBACK PATH — ``_run_internal``. A minimal event loop used ONLY when
``trade-backtest`` is absent. It mirrors the sibling's conventions
(signals at bar close, fills at next bar's open, mark-to-market at
close). The result flags ``engine: "internal-fallback"`` so results are
never misread as sibling-engine output.

COSTS — applied uniformly after the run: each closed trade's round-trip
cost is subtracted from the equity curve at its exit date, and all
headline metrics are computed on the cost-adjusted curve. A backtest
that hides costs is a fantasy; this one can't.
"""

from __future__ import annotations

import importlib

from . import metrics as _metrics
from .costs import CostModel, apply_costs
from .sizing import atr_position_size
from .strategy import SwingConfig, generate_signals


# ---------------------------------------------------------------------------
# sibling import (lazy)
# ---------------------------------------------------------------------------

def _try_import_trade_backtest():
    try:
        models = importlib.import_module("trade_backtest.models")
        data = importlib.import_module("trade_backtest.data")
        strategy_mod = importlib.import_module("trade_backtest.strategy")
        portfolio = importlib.import_module("trade_backtest.portfolio")
        execution = importlib.import_module("trade_backtest.execution")
        engine = importlib.import_module("trade_backtest.engine")
    except ImportError:
        return None
    return {"models": models, "data": data, "strategy": strategy_mod,
            "portfolio": portfolio, "execution": execution, "engine": engine}


# ---------------------------------------------------------------------------
# primary path: delegate to trade-backtest
# ---------------------------------------------------------------------------

def _run_with_trade_backtest(tb, bars_by_symbol, config, convictions,
                             initial_cash):
    from datetime import datetime, timezone

    intents: dict[str, dict[str, dict]] = {}
    for symbol, bars in bars_by_symbol.items():
        rows = generate_signals(bars, config, convictions)
        intents[symbol] = {r["date"]: r for r in rows}

    models, data_mod = tb["models"], tb["data"]

    tb_bars = []
    for symbol, bars in bars_by_symbol.items():
        for b in bars:
            dt = datetime.fromisoformat(b["date"]).replace(tzinfo=timezone.utc)
            tb_bars.append(models.Bar(
                symbol=symbol, timestamp=dt, open=b["open"], high=b["high"],
                low=b["low"], close=b["close"], volume=b.get("volume", 0.0)))

    class _IntentStrategy(tb["strategy"].Strategy):
        def __init__(self, symbols, intents):
            super().__init__(symbols)
            self._intents = intents

        def on_bar(self, timestamp, bars):
            out = []
            date = timestamp.date().isoformat()
            for symbol in bars:
                row = self._intents.get(symbol, {}).get(date)
                if row is None:
                    continue
                if row["signal"] == "enter_long":
                    out.append(models.Signal(
                        symbol=symbol, timestamp=timestamp,
                        action=models.SignalAction.LONG))
                elif row["signal"] == "exit_long":
                    out.append(models.Signal(
                        symbol=symbol, timestamp=timestamp,
                        action=models.SignalAction.EXIT))
            return out

    class _ATRSizer(tb["portfolio"].PositionSizer):
        def __init__(self, intents, config):
            self._intents = intents
            self._config = config

        def size(self, signal, price, portfolio):
            if signal.action == models.SignalAction.EXIT:
                return 0.0
            row = self._intents.get(signal.symbol, {}).get(
                signal.timestamp.date().isoformat())
            atr = row["atr"] if row and row["atr"] else 0.0
            cfg = self._config
            return float(atr_position_size(
                portfolio.equity, atr, cfg.stop_multiple,
                cfg.risk_per_trade, price, cfg.max_position_pct))

    data = data_mod.ListDataHandler(tb_bars)
    strategy = _IntentStrategy(list(bars_by_symbol), intents)
    portfolio = tb["portfolio"].Portfolio(
        initial_cash, _ATRSizer(intents, config))
    execution = tb["execution"].SimulatedExecutionHandler(
        slippage_bps=0.0, commission=tb["execution"].NoCommission())
    result = tb["engine"].BacktestEngine(
        data, strategy, portfolio, execution).run()

    equity_curve = [{"date": p.timestamp.date().isoformat(), "equity": p.equity}
                    for p in result.equity_curve]
    trades = [{
        "symbol": t.symbol,
        "entry_date": t.entry_time.date().isoformat(),
        "exit_date": t.exit_time.date().isoformat(),
        "quantity": t.quantity,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "pnl_gross": t.pnl,
    } for t in result.trades]
    return equity_curve, trades


# ---------------------------------------------------------------------------
# fallback path: minimal internal event loop
# ---------------------------------------------------------------------------

def _run_internal(bars_by_symbol, config, convictions, initial_cash):
    intents: dict[str, dict[str, dict]] = {}
    for symbol, bars in bars_by_symbol.items():
        rows = generate_signals(bars, config, convictions)
        intents[symbol] = {r["date"]: r for r in rows}

    dates = sorted({b["date"] for bars in bars_by_symbol.values() for b in bars})
    bars_by_date: dict[str, dict[str, dict]] = {}
    for symbol, bars in bars_by_symbol.items():
        for b in bars:
            bars_by_date.setdefault(b["date"], {})[symbol] = b

    cash = float(initial_cash)
    positions: dict[str, dict] = {}   # symbol -> {qty, entry_price, entry_date}
    last_close: dict[str, float] = {}
    pending: list[tuple[str, str, int]] = []  # (symbol, side, qty)
    trades: list[dict] = []
    equity_curve: list[dict] = []

    for d in dates:
        day = bars_by_date.get(d, {})
        # 1. fill orders signaled on the previous bar, at this bar's open
        for symbol, side, qty in pending:
            bar = day.get(symbol)
            if bar is None:
                continue  # no bar -> order lapses (matches trade-backtest)
            price = bar["open"]
            if side == "buy":
                cash -= qty * price
                positions[symbol] = {"qty": qty, "entry_price": price,
                                     "entry_date": d}
            else:
                pos = positions.pop(symbol)
                cash += qty * price
                trades.append({
                    "symbol": symbol,
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "quantity": qty,
                    "entry_price": pos["entry_price"],
                    "exit_price": price,
                    "pnl_gross": (price - pos["entry_price"]) * qty,
                })
        pending = []
        # 2. mark to market at close
        for symbol, bar in day.items():
            last_close[symbol] = bar["close"]
        equity = cash + sum(p["qty"] * last_close[s] for s, p in positions.items())
        # 3. today's intents become tomorrow's fills
        for symbol, imap in intents.items():
            row = imap.get(d)
            if row is None or symbol not in day:
                continue
            if row["signal"] == "enter_long" and symbol not in positions:
                shares = atr_position_size(
                    equity, row["atr"] or 0.0, config.stop_multiple,
                    config.risk_per_trade, day[symbol]["close"],
                    config.max_position_pct)
                if shares > 0:
                    pending.append((symbol, "buy", shares))
            elif row["signal"] == "exit_long" and symbol in positions:
                pending.append((symbol, "sell", positions[symbol]["qty"]))
        # 4. record
        equity_curve.append({"date": d, "equity": equity})

    open_positions = [
        {"symbol": s, "qty": p["qty"], "entry_price": p["entry_price"],
         "entry_date": p["entry_date"], "last_close": last_close[s]}
        for s, p in positions.items()
    ]
    return equity_curve, trades, open_positions


# ---------------------------------------------------------------------------
# costs -> metrics -> plain-data result
# ---------------------------------------------------------------------------

def _apply_costs_to_curve(equity_curve: list[dict],
                          trades: list[dict]) -> list[dict]:
    cost_by_date: dict[str, float] = {}
    for t in trades:
        cost_by_date[t["exit_date"]] = cost_by_date.get(t["exit_date"], 0.0) + t["cost"]
    cum = 0.0
    out = []
    for pt in equity_curve:
        cum += cost_by_date.get(pt["date"], 0.0)
        out.append({"date": pt["date"], "equity": pt["equity"] - cum})
    return out


def run_backtest(bars_by_symbol: dict[str, list[dict]],
                 config: SwingConfig | None = None,
                 cost_model: CostModel | None = None,
                 initial_cash: float = 100_000.0,
                 convictions: dict[str, float] | None = None,
                 provenance: dict | None = None,
                 force_engine: str | None = None) -> dict:
    """Run the swing backtest. Returns a plain-data, JSON-serializable dict.

    ``force_engine``: ``"trade-backtest"`` | ``"internal"`` | None (auto).
    The result's ``"engine"`` field always says which one ran.
    """
    config = config or SwingConfig()
    cost_model = cost_model or CostModel()
    if initial_cash <= 0:
        raise ValueError("initial_cash must be > 0")
    if not bars_by_symbol:
        raise ValueError("bars_by_symbol is empty")

    tb = None if force_engine == "internal" else _try_import_trade_backtest()
    if force_engine == "trade-backtest" and tb is None:
        raise RuntimeError("force_engine='trade-backtest' but trade-backtest "
                           "is not installed")

    open_positions: list[dict] = []
    if tb is not None:
        engine_name = "trade-backtest"
        equity_curve, trades = _run_with_trade_backtest(
            tb, bars_by_symbol, config, convictions, initial_cash)
    else:
        engine_name = "internal-fallback"
        equity_curve, trades, open_positions = _run_internal(
            bars_by_symbol, config, convictions, initial_cash)

    trades, cost_summary = apply_costs(trades, cost_model)
    adj_curve = _apply_costs_to_curve(equity_curve, trades)
    curve_values = [p["equity"] for p in adj_curve]
    stats = _metrics.summarize(curve_values, trades)

    return {
        "engine": engine_name,
        "config": config.as_dict(),
        "initial_cash": initial_cash,
        "final_equity": curve_values[-1] if curve_values else initial_cash,
        "equity_curve": adj_curve,
        "trades": trades,
        "open_positions": open_positions,
        "metrics": stats,
        "costs": cost_summary,
        "provenance": provenance or {"source": "unspecified"},
        "notes": [] if tb is not None else [
            "trade-backtest is not installed; the minimal internal event "
            "loop ran instead. Trigger logic is identical (strategy.py is "
            "the single source of truth); cash accounting is simplified."
        ],
    }
