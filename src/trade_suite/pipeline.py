"""End-to-end research workflows over the suite engines.

Each workflow orchestrates already-installed sibling modules through the
shared dashboard-engine services, so a scripted run and a dashboard run of
the same job produce identical results.  All sibling imports are lazy: a
workflow raises a clear error naming the missing package instead of failing
at ``import trade_suite`` time.
"""

from __future__ import annotations

from . import data as _data


def _services():
    """Dashboard engine services: web first, desktop fallback."""
    for package in ("trade_dashboard_web", "trade_dashboard_desktop"):
        try:
            return __import__(f"{package}.engine", fromlist=["run_backtest_job"])
        except ImportError:
            continue
    raise RuntimeError(
        "workflows need a dashboard package installed "
        "(trade-dashboard-web or trade-dashboard-desktop)"
    )


def run_backtest(
    strategy_name: str,
    symbols: list[str],
    params: dict | None = None,
    source: str = "demo",
    days: int = 250,
    initial_cash: float = 100_000.0,
) -> dict:
    """Backtest ``strategy_name``; returns metrics, equity curve, trades."""
    services = _services()
    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        raise ValueError("at least one symbol is required")
    bars = _data.get_bars(symbols[0], source=source, days=days)
    return services.run_backtest_job(strategy_name, symbols, params or {},
                                     bars, initial_cash=initial_cash)


def run_desk(
    symbols: list[str],
    source: str = "demo",
    days: int = 250,
    equity: float = 100_000.0,
) -> dict:
    """Run the agentic research desk; returns the plain-data desk report."""
    services = _services()
    bars = _data.get_bars_many(symbols, source=source, days=days)
    return services.run_desk_job(sorted(bars), bars, equity=equity)


def evaluate_orders(
    orders: list[dict],
    limits: list[list] | None = None,
    equity: float = 100_000.0,
) -> dict:
    """Evaluate ``orders`` against a ``[[name, params], ...]`` limit stack."""
    services = _services()
    return services.evaluate_orders_job(orders, limits, equity)


def research_pipeline(
    symbols: list[str],
    source: str = "demo",
    days: int = 250,
    equity: float = 100_000.0,
    backtest_strategy: str | None = None,
    backtest_params: dict | None = None,
) -> dict:
    """Desk research → optional strategy backtest → risk review of orders.

    Returns ``{"desk": ..., "backtest": ...|None, "risk": ...}`` as plain data.
    """
    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        raise ValueError("at least one symbol is required")

    desk = run_desk(symbols, source=source, days=days, equity=equity)

    backtest = None
    if backtest_strategy:
        backtest = run_backtest(backtest_strategy, symbols,
                                backtest_params, source, days, equity)

    risk = evaluate_orders(desk.get("approved_orders", []), None, equity)
    return {"desk": desk, "backtest": backtest, "risk": risk}


def paper_overview(config_path: str = "paper-config.json") -> dict:
    """One-screen paper-trading state from the ``trade-paper`` engine.

    Unlike the research workflows above this talks to ``trade-paper``
    directly — the engine of record for execution — rather than the
    dashboard services.  Returns account, positions, and the approval
    queue as plain data.  Paper only: ``trade-paper`` refuses live
    brokers in code, so this can never report or touch live state.
    """
    try:
        from trade_paper.brokers import make_broker
        from trade_paper.config import PaperConfig
        from trade_paper.ledger import Ledger
    except ImportError as exc:
        raise RuntimeError(
            "paper workflows need the trade-paper package installed "
            "(pip install git+https://github.com/crieck2010/trade-paper.git)"
        ) from exc

    cfg = PaperConfig.load(config_path)
    broker, ledger = make_broker(cfg), Ledger(cfg.db_path)
    try:
        acct = broker.get_account()
        positions = broker.get_positions()
        pending = ledger.list_approvals(status="pending")
        return {
            "broker": broker.name, "paper_only": True,
            "equity": round(acct.equity, 2), "cash": round(acct.cash, 2),
            "buying_power": round(acct.buying_power, 2),
            "market_open": broker.is_market_open(),
            "positions": [{"symbol": p.symbol, "qty": p.quantity,
                           "unrealized": round(p.unrealized_pnl, 2)}
                          for p in positions],
            "pending_approvals": [
                {"id": r["id"], "strategy": r["strategy"],
                 "symbols": r["symbols"],
                 "score": r["metrics"].get("score")}
                for r in pending],
            "active_strategies": len(ledger.active_strategies()),
        }
    finally:
        ledger.close()


def sentiment_scan(
    symbols: list[str],
    window_hours: int = 24,
    min_mentions: int = 5,
    min_conviction: float = 5.0,
) -> dict:
    """Scan ``symbols`` for social/news sentiment pops (trade-sentiment).

    Unlike the research workflows above this talks to ``trade-sentiment``
    directly — the engine of record for chatter — rather than the
    dashboard services.  Returns the scan window, one verdict string per
    pop, and the pops themselves as plain data (dual 0-10 scores:
    ``bullishness_10`` = pure tone, ``conviction_10`` = tone x volume).
    The same engine feeds the trade-agents ``sentiment_scout`` researcher.
    """
    try:
        from trade_sentiment import scan as engine_scan
    except ImportError as exc:
        raise RuntimeError(
            "sentiment scans need the trade-sentiment package installed "
            "(pip install git+https://github.com/crieck2010/trade-sentiment.git)"
        ) from exc

    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        raise ValueError("at least one symbol is required")
    pops = engine_scan(symbols, window_hours=window_hours,
                       min_mentions=min_mentions)
    pops = [p for p in pops if p.conviction >= min_conviction]
    return {
        "window_hours": window_hours,
        "symbols": symbols,
        "verdicts": [p.verdict for p in pops],
        "pops": [
            {"symbol": p.symbol,
             "bullishness_10": p.bullishness,
             "conviction_10": p.conviction,
             "n_mentions": p.n_mentions,
             "volume_zscore": round(p.volume_zscore, 2),
             "tone_shift": round(p.tone_shift, 3),
             "drivers": p.drivers,
             "verdict": p.verdict}
            for p in pops
        ],
    }


def summarize_sentiment(scan_result: dict) -> str:
    """One-screen text summary of a sentiment scan."""
    lines = [f"Sentiment scan ({scan_result['window_hours']}h): "
             f"{len(scan_result['pops'])} pops "
             f"across {len(scan_result['symbols'])} symbols"]
    lines.extend(f"  {v}" for v in scan_result["verdicts"][:10])
    return "\n".join(lines)


def summarize_desk(report: dict) -> str:
    """One-screen text summary of a desk report."""
    n_ideas = sum(len(b["ideas"]) for b in report["briefs"])
    lines = [
        f"Desk report {report['as_of'][:16]}Z: {len(report['briefs'])} briefs, "
        f"{n_ideas} ideas, {len(report['allocations'])} allocations, "
        f"{len(report['approved_orders'])} approved, {len(report['vetoes'])} vetoed",
    ]
    ideas = sorted(
        (i for b in report["briefs"] for i in b["ideas"]),
        key=lambda i: i.get("conviction", 0), reverse=True,
    )
    for idea in ideas[:8]:
        m = idea.get("metrics", {})
        lines.append(
            f"  {idea.get('direction', '').upper():5s} {idea.get('symbol'):6s} "
            f"conviction={idea.get('conviction', 0):.2f} "
            f"sharpe={m.get('sharpe_ratio', 0):.2f} "
            f"max_dd={m.get('max_drawdown', 0):.1%} via {idea.get('strategy')}"
        )
    return "\n".join(lines)


def summarize_backtest(result: dict) -> str:
    """One-screen text summary of a backtest result."""
    m = result["metrics"]
    return (
        f"{result['strategy']} on {', '.join(result['symbols'])}: "
        f"final ${result['final_equity']:,.2f} "
        f"({m.get('total_return', 0):+.1%} total, "
        f"Sharpe {m.get('sharpe_ratio', 0):.2f}, "
        f"max DD {m.get('max_drawdown', 0):.1%}, "
        f"{len(result['trades'])} trades)"
    )
