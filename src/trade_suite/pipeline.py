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
    sentiment_price: bool = False,
    factor_model: str | None = None,
) -> dict:
    """Desk research → optional strategy backtest → risk review of orders.

    Optional enrichments (off by default, keeping the classic call fast):
    ``sentiment_price=True`` attaches a per-symbol sentiment-vs-price
    verdict; ``factor_model="ff5"`` attaches a Fama-French factor report.

    Returns ``{"desk": ..., "backtest": ...|None, "risk": ...}`` plus any
    requested enrichment keys, all as plain data.
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
    out: dict = {"desk": desk, "backtest": backtest, "risk": risk}
    if sentiment_price:
        out["sentiment_price"] = {
            s: run_sentiment_price(s, source=source, days=min(days, 365))
            for s in symbols
        }
    if factor_model:
        out["factors"] = run_factor_analysis(
            symbols, source=source, days=max(days, 750), model=factor_model)
    return out


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


# ---------------------------------------------------------------------------
# Research-lab workflows (trade-suite 0.2.0): one thin workflow per new engine.
#
# Like run_backtest/run_desk/evaluate_orders above, these delegate to the
# shared dashboard-engine services — the single implementation both
# dashboards' Research Lab tabs use — so a scripted run and a dashboard run
# of the same job produce identical results.  All sibling imports stay lazy:
# a missing engine raises a RuntimeError naming the pip install fix.
# ---------------------------------------------------------------------------

def _clean_symbols(symbols: list[str]) -> list[str]:
    out = [s.strip().upper() for s in symbols if s and s.strip()]
    if not out:
        raise ValueError("at least one symbol is required")
    return out


def run_pairs_screen(
    symbols: list[str],
    source: str = "demo",
    days: int = 300,
    lookback: int = 252,
    max_pairs: int = 10,
) -> dict:
    """Screen a symbol universe for cointegrated pairs (trade-pairs).

    Returns the ranked candidates with hedge ratios, half-lives, and the
    Engle-Granger verdicts as plain data.
    """
    syms = _clean_symbols(symbols)
    services = _services()
    bars = _data.get_bars_many(syms, source=source, days=days)
    return services.run_pairs_job(syms, bars, lookback=lookback,
                                  max_pairs=max_pairs)


def run_orderbook_sim(
    symbol: str = "DEMO",
    side: str = "buy",
    quantity: float = 100.0,
    order_type: str = "market",
    n_levels: int = 5,
    level_qty: float = 50.0,
) -> dict:
    """Simulate executing an order against a seeded book (trade-orderbook).

    Seeds a symmetric ``n_levels``-deep book around 100.00, fires one probe
    order, and reports fill quality: average fill price and slippage in bps
    versus mid, plus microstructure features for agents.
    """
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if order_type not in ("market", "limit"):
        raise ValueError("order_type must be 'market' or 'limit'")
    services = _services()
    return services.run_orderbook_job(
        symbol=symbol, side=side, quantity=quantity, order_type=order_type,
        n_levels=n_levels, level_qty=level_qty)


def run_optimize(
    symbols: list[str],
    source: str = "demo",
    days: int = 250,
    method: str = "max_sharpe",
    max_weight: float = 1.0,
) -> dict:
    """Optimize a long-only portfolio over ``symbols`` (trade-optimize).

    ``method``: max_sharpe | min_variance | risk_parity | equal_weight.
    Returns weights, portfolio stats, and a 20-point efficient frontier —
    the same numbers the dashboard Portfolio panel renders.
    """
    syms = _clean_symbols(symbols)
    services = _services()
    bars = _data.get_bars_many(syms, source=source, days=days)
    return services.run_optimize_job(syms, bars, method=method,
                                     max_weight=max_weight)


def run_montecarlo(
    symbols: list[str],
    weights: list[float] | None = None,
    source: str = "demo",
    days: int = 250,
    equity: float = 100_000.0,
    n_paths: int = 5_000,
    n_steps: int = 252,
    seed: int = 7,
    alpha: float = 0.95,
) -> dict:
    """Simulated portfolio VaR/CVaR over correlated GBM paths (trade-montecarlo).

    Complements trade-optimize's analytic vol with a full P&L distribution.
    """
    syms = _clean_symbols(symbols)
    services = _services()
    bars = _data.get_bars_many(syms, source=source, days=days)
    return services.run_montecarlo_job(
        syms, bars, weights=weights, equity=equity, n_paths=n_paths,
        n_steps=n_steps, seed=seed, alpha=alpha)


def run_vol_surface(
    symbol: str = "SPY",
    spot: float | None = None,
    risk_free: float = 0.03,
) -> dict:
    """Fit an SVI volatility surface (trade-volsurface).

    Demo mode uses the engine's synthetic quote set; real option chains plug
    into the same ``from_option_chain`` adapter the engine exposes.
    """
    services = _services()
    return services.run_vol_surface_job(symbol=symbol, spot=spot,
                                        risk_free=risk_free)


def run_factor_analysis(
    symbols: list[str],
    source: str = "demo",
    days: int = 1500,
    model: str = "ff5",
    n_months: int = 60,
) -> dict:
    """Fama-French time-series regressions + GRS test (trade-factors).

    Demo mode regresses monthly asset returns on the engine's synthetic
    monthly factor set (date labels are synthetic in demo mode; alignment
    is what matters).  Demo bars cap at 750 days, so demo runs use about
    two years of monthly history.  Real Ken French CSVs plug in via the
    engine's ``load_french_csv``.
    """
    syms = _clean_symbols(symbols)
    services = _services()
    bars = _data.get_bars_many(syms, source=source, days=days)
    return services.run_factor_analysis_job(syms, bars, model=model,
                                            n_months=n_months)


def run_sentiment_price(
    symbol: str,
    source: str = "demo",
    days: int = 180,
    sentiment_rows: list[dict] | None = None,
) -> dict:
    """Sentiment-vs-price verdict bundle (trade-sentiment-vs-price).

    Demo mode uses synthetic data with a planted 1-day sentiment lead.
    For real data pass ``sentiment_rows`` (trade-sentiment JSON rows —
    the engine is snapshot-based, so history comes from your archive) and
    set ``source`` to a real bar source.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("a symbol is required")
    services = _services()
    if sentiment_rows is not None:
        bars = _data.get_bars(symbol, source=source, days=days)
    elif source != "demo":
        raise ValueError(
            "run_sentiment_price needs sentiment_rows for non-demo sources "
            "(trade-sentiment is snapshot-based); use source='demo' or pass rows")
    else:
        bars = None
    return services.run_sentiment_price_job(
        symbol, bars=bars, sentiment_rows=sentiment_rows, days=days)


def run_correlation(
    symbols: list[str],
    source: str = "demo",
    days: int = 365,
    method: str = "pearson",
    shrinkage: str = "ledoit_wolf",
    lookback: int = 252,
) -> dict:
    """Correlation/EDA report over a symbol universe (trade-eda).

    Returns the Pearson/Spearman matrix, Ledoit-Wolf shrunk covariance,
    per-asset summary stats, data-quality flags, and diversification
    stats (mean/max pairwise correlation, effective number of bets) as
    plain data — the same job the Research Lab's Correlations panel runs.
    """
    if method not in ("pearson", "spearman"):
        raise ValueError("method must be 'pearson' or 'spearman'")
    syms = _clean_symbols(symbols)
    services = _services()
    bars = _data.get_bars_many(syms, source=source, days=days)
    return services.run_correlation_job(
        syms, bars, method=method, shrinkage=shrinkage, lookback=lookback)


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


def summarize_pairs(result: dict) -> str:
    """One-screen text summary of a pairs screen."""
    lines = [f"Pairs screen ({result['lookback']}d lookback): "
             f"{len(result['pairs'])} candidates, "
             f"{result['n_cointegrated']} cointegrated"]
    for p in result["pairs"][:8]:
        mark = "COINT" if p["cointegrated"] else "     "
        lines.append(f"  {mark} {p['symbol_a']}/{p['symbol_b']} "
                     f"hedge={p['hedge_ratio']:.3f} "
                     f"half-life={p['half_life_bars']:.1f}d "
                     f"corr={p['correlation']:.2f}")
    return "\n".join(lines)


def summarize_orderbook(result: dict) -> str:
    """One-screen text summary of an order-book simulation."""
    return (
        f"Order book {result['symbol']} {result['side']} "
        f"{result['quantity']:g} ({result['order_type']}): "
        f"filled {result['filled_qty']:g} @ avg {result['avg_fill_price']:.2f} "
        f"vs mid {result['midprice']:.2f} → "
        f"slippage {result['slippage_bps']:+.1f} bps "
        f"({result['n_fills']} fills)"
    )


def summarize_optimize(result: dict) -> str:
    """One-screen text summary of a portfolio optimization."""
    lines = [f"Optimize ({result['method']}) on {', '.join(result['symbols'])}: "
             f"E[r]={result['expected_return']:.4f} "
             f"vol={result['volatility']:.4f} "
             f"Sharpe={result['sharpe']:.2f}"]
    top = sorted(result["weights"].items(), key=lambda kv: -kv[1])[:6]
    lines.append("  weights: " + ", ".join(f"{s}={w:.2%}" for s, w in top))
    return "\n".join(lines)


def summarize_montecarlo(result: dict) -> str:
    """One-screen text summary of a Monte Carlo VaR run."""
    return (
        f"Monte Carlo ({result['n_paths']:,} paths × {result['n_steps']} steps) "
        f"on {', '.join(result['symbols'])}: "
        f"VaR({result['alpha']:.0%})=${result['var']:,.0f} "
        f"({result['var_pct_of_capital']:.1%} of capital) · "
        f"CVaR=${result['cvar']:,.0f} · "
        f"P(profit)={result['prob_profit']:.1%}"
    )


def summarize_volsurface(result: dict) -> str:
    """One-screen text summary of a vol-surface fit."""
    return (
        f"Vol surface {result['symbol']} @ {result['spot']:.2f}: "
        f"{result['n_quotes']} quotes across {len(result['expiries'])} expiries, "
        f"SVI fits: {', '.join(result['svi_fits'])}"
    )


def summarize_factors(result: dict) -> str:
    """One-screen text summary of a factor analysis."""
    lines = [f"Factor analysis ({result['model']}, {result['n_months']} months):"]
    for a, r in result["assets"].items():
        lines.append(f"  {a}: alpha={r['alpha']:+.4f} "
                     f"(t={r['alpha_t']:+.2f}, p={r['alpha_p']:.3f}) "
                     f"R²={r['rsquared']:.3f}")
    grs = result.get("grs") or {}
    if grs:
        lines.append(f"  GRS joint-alpha: F={grs.get('F', 0):.2f}, "
                     f"p={grs.get('pvalue', 1):.4f}")
    return "\n".join(lines)


def summarize_sentiment_price(result: dict) -> str:
    """One-screen text summary of a sentiment-vs-price report."""
    ll, ic = result["lead_lag"], result["ic"]
    es = result["event_study"]
    return (
        f"Sentiment vs price {result['symbol']} ({result['n_days']}d): "
        f"{ll['verdict']} (lag {ll['best_lag']}, r={ll['best_r']:+.3f}, "
        f"p={ll['best_pvalue']:.3f}) · "
        f"IC={ic['ic']:+.3f} (p={ic['pvalue']:.3f}) · "
        f"event CAR={es['mean_car']:+.4f} over {es['n_events']} bursts "
        f"(p={es['pvalue']:.3f})"
    )


# ---------------------------------------------------------------------------
# Market-context, streaming, and reconcile workflows (trade-suite 0.4.0):
# the same delegation pattern as the research-lab workflows above — each
# calls _services() (web engine first, desktop fallback) and invokes the
# canonical run_*_job the dashboards' new panels run, so scripted, CLI,
# and dashboard runs of the same job agree exactly.  All sibling imports
# stay lazy: a missing dashboard raises the standard RuntimeError.
# ---------------------------------------------------------------------------

def run_breadth(
    preset: str = "standard",
    seed: int = 7,
    n_days: int = 600,
) -> dict:
    """Market-breadth regime snapshot (trade-breadth).

    Delegates to the dashboards' canonical ``run_breadth_job``.  Returns
    the source, seed, n_days, n_symbols, and the engine's ``snapshot`` dict
    (regime, fragility, indicators, thrusts_recent) as plain data.
    """
    services = _services()
    return services.run_breadth_job(preset=preset, seed=seed, n_days=n_days)


def run_macro(
    preset: str = "standard",
    seed: int = 42,
    days: int = 600,
) -> dict:
    """Macro regime snapshot (trade-macro).

    Copper:gold ratio as the market's growth-expectations proxy, with
    transition alerts on fast z-score moves.  Delegates to the dashboards'
    canonical ``run_macro_job``; returns source, seed, days, and the
    engine's ``snapshot`` dict (regime, z_score, ratio, transition_alert).
    """
    services = _services()
    return services.run_macro_job(preset=preset, seed=seed, days=days)


def run_stream_demo(
    symbols: tuple[str, ...] = ("AAA", "BBB", "CCC"),
    seed: int = 7,
    n_ticks: int = 600,
) -> dict:
    """Demo tick-stream run (trade-stream): feed -> bus -> alerts + bars.

    Delegates to the dashboards' canonical ``run_stream_demo_job``; the
    result is JSON-serializable demo output (ticks, spike alerts, resampled
    bars, latest-price cache) with no network and no credentials.
    """
    services = _services()
    return services.run_stream_demo_job(symbols=list(symbols), seed=seed,
                                        n_ticks=n_ticks)


def run_reconcile_demo() -> dict:
    """DEMO — read-only reconcile of the paper ledger against a mock broker.

    Exercises trade-paper v0.2.0's reconcile machinery (the same read-only
    diff the Robinhood MCP adapter uses) against an in-memory mock broker,
    so this can never touch live state.  Returns ``{"demo": True,
    "paper_positions": {...}, "broker_positions": {...}, "reconcile":
    {matched, missing_from_broker, missing_from_ledger, quantity_mismatches,
    clean}}`` as plain data.
    """
    services = _services()
    return services.run_reconcile_demo_job()


def summarize_breadth(result: dict) -> str:
    """One-screen text summary of a market-breadth snapshot."""
    snap = result["snapshot"]
    lines = [
        f"Market breadth ({result['n_symbols']} symbols x {result['n_days']}d, "
        f"seed {result['seed']}): regime {snap['regime']} "
        f"(score {snap.get('regime_score', 0.0):.2f}), "
        f"fragility {snap['fragility']:.2f}",
    ]
    thrusts = snap.get("thrusts_recent") or []
    if thrusts:
        lines.append("  recent thrusts: " + ", ".join(
            f"{t.get('date', '?')} {t.get('kind', t.get('type', 'thrust'))}"
            for t in thrusts[-3:]))
    warnings = snap.get("warnings") or []
    if warnings:
        lines.append(f"  narrowing warnings active: {len(warnings)}")
    return "\n".join(lines)


def summarize_macro(result: dict) -> str:
    """One-screen text summary of a macro regime snapshot."""
    snap = result["snapshot"]
    ratio, z = snap.get("ratio"), snap.get("z_score")
    alert = " - TRANSITION ALERT" if snap.get("transition_alert") else ""
    return (
        f"Macro regime ({result['days']}d, seed {result['seed']}): "
        f"{snap['regime']}"
        + (f" - copper:gold {ratio:.4f}" if ratio is not None else "")
        + (f" (z {z:+.2f})" if z is not None else "")
        + alert
    )


def summarize_stream_demo(result: dict) -> str:
    """One-screen text summary of a demo tick-stream run."""
    lines = [
        f"Demo tick stream ({', '.join(result.get('symbols', []))}): "
        f"{result.get('n_ticks', 0)} ticks -> "
        f"{result.get('n_alerts', 0)} spike alerts, "
        f"{result.get('n_bars', 0)} bars",
    ]
    for a in (result.get("alerts") or [])[:5]:
        lines.append(f"  {a.get('symbol')} spike {a.get('move_pct', 0):+.1%} "
                     f"@ {a.get('price')}")
    return "\n".join(lines)


def summarize_reconcile(result: dict) -> str:
    """One-screen text summary of a demo reconcile."""
    rec = result["reconcile"]
    if rec["clean"]:
        lines = ["DEMO reconcile (paper ledger vs mock broker): "
                 "CLEAN - no drift"]
    else:
        lines = [f"DEMO reconcile (paper ledger vs mock broker): DRIFT - "
                 f"{len(rec['missing_from_broker'])} missing from broker, "
                 f"{len(rec['missing_from_ledger'])} missing from ledger, "
                 f"{len(rec['quantity_mismatches'])} quantity mismatches"]
    for m in rec.get("quantity_mismatches", [])[:5]:
        lines.append(f"  {m['symbol']}: paper {m['paper']:g} vs "
                     f"broker {m['broker']:g} (diff {m['diff']:+g})")
    for m in rec.get("missing_from_broker", [])[:5]:
        lines.append(f"  {m['symbol']}: in paper ({m['paper']:g}), "
                     "absent at broker")
    for m in rec.get("missing_from_ledger", [])[:5]:
        lines.append(f"  {m['symbol']}: at broker ({m['broker']:g}), "
                     "unknown to paper")
    return "\n".join(lines)


def summarize_correlation(result: dict) -> str:
    """One-screen text summary of a correlation/EDA report."""
    div = result["diversification"]
    hi = div["max_pairwise_corr"]
    dirty = [s for s, q in result["quality"].items() if not q["clean"]]
    lines = [
        f"Correlation ({result['correlation']['method']}) "
        f"{len(result['symbols'])} symbols, {result['n_obs']} obs: "
        f"mean pairwise r={div['mean_pairwise_corr']:+.3f}, "
        f"max {hi['a']}/{hi['b']}={hi['value']:+.3f}, "
        f"effective N={div['effective_n_equal_weight']:.1f}, "
        f"LW delta={result['covariance']['shrinkage_delta']:.3f}",
    ]
    if dirty:
        lines.append(f"  data-quality flags: {', '.join(dirty)}")
    return "\n".join(lines)
