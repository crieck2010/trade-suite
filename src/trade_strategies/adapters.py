"""Lazy bridge to ``trade-backtest``.

This module is the *only* place that touches ``trade-backtest``, and it
imports it lazily so ``trade-strategies`` stays installable and usable
without the backtester (e.g. for pure research or agent-side analysis).
"""

from __future__ import annotations

from .base import Strategy


def _tb():
    try:
        import trade_backtest as tb
    except ImportError as exc:
        raise ImportError(
            "trade-backtest is required for this function; "
            "install it with `pip install trade-backtest`") from exc
    return tb


def to_backtest_strategy(strategy: Strategy):
    """Adapt a strategy to ``trade_backtest.Strategy`` (fresh instance)."""
    tb = _tb()

    class _Adapted(tb.Strategy):
        def __init__(self) -> None:
            super().__init__(strategy.symbols)
            self.inner = strategy

        def on_bar(self, timestamp, bars):
            return [
                tb.Signal(s.symbol, s.timestamp, tb.SignalAction[s.action.name],
                          s.strength, s.limit_price)
                for s in self.inner.on_bar(timestamp, bars)
            ]

    adapted = _Adapted()
    adapted.__class__.__name__ = f"Backtest{type(strategy).__name__}"
    return adapted


def run_backtest(
    strategy: Strategy,
    bars: list,
    initial_cash: float = 100_000.0,
    sizer=None,
    execution=None,
    periods_per_year: float = 252,
    risk_free: float = 0.0,
):
    """One-call backtest: normalize ``bars``, adapt ``strategy``, run, return result.

    ``bars`` may be dicts or any bar-like objects; symbols are taken as-is.
    """
    tb = _tb()
    normalized = [tb.normalize_bar(b) for b in bars]
    engine = tb.BacktestEngine(
        data=tb.ListDataHandler(normalized),
        strategy=to_backtest_strategy(strategy),
        portfolio=tb.Portfolio(initial_cash,
                               sizer or tb.FixedQuantitySizer(100)),
        execution=execution or tb.SimulatedExecutionHandler(),
        periods_per_year=periods_per_year,
        risk_free=risk_free,
        # trade-backtest v0.2.0 requires a declared basis. Bars here come
        # from arbitrary providers, so we assume the common vendor
        # convention -- verify for your feed.
        adjustment_basis="pre_adjusted",
        adjustment_note="provider bars assumed split/dividend-adjusted -- "
                        "verify for your feed",
    )
    return engine.run()
