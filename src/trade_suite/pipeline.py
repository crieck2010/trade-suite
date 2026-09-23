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
