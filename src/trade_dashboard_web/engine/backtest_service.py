"""Run backtests and return JSON-safe results (via siblings, lazy)."""


def run_backtest_job(
    strategy_name: str,
    symbols: list[str],
    params: dict | None,
    bars: list,
    initial_cash: float = 100_000.0,
) -> dict:
    """Backtest ``strategy_name`` over ``bars``; return metrics, equity
    curve, and trades as plain data."""
    try:
        from trade_strategies import get_strategy
        from trade_strategies.adapters import run_backtest
    except ImportError as exc:
        raise RuntimeError(
            "backtests need the trade-strategies and trade-backtest "
            "packages installed"
        ) from exc

    if not symbols:
        raise ValueError("at least one symbol is required")
    strategy = get_strategy(strategy_name)(list(symbols), **(params or {}))
    result = run_backtest(strategy, bars, initial_cash=initial_cash)

    curve = [
        {"timestamp": _iso(p.timestamp), "equity": p.equity, "cash": p.cash}
        for p in result.equity_curve
    ]
    trades = [
        {
            "symbol": t.symbol,
            "entry_time": _iso(t.entry_time),
            "exit_time": _iso(t.exit_time),
            "quantity": t.quantity,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "return_pct": t.return_pct,
        }
        for t in result.trades
    ]
    return {
        "strategy": strategy_name,
        "symbols": list(symbols),
        "params": params or {},
        "initial_cash": initial_cash,
        "final_equity": result.final_equity,
        "metrics": {k: float(v) for k, v in result.metrics.items()},
        "equity_curve": curve,
        "trades": trades,
    }


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
