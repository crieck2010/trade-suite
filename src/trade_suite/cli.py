"""Unified CLI: ``trade-suite status|doctor|demo|backtest|paper|sentiment|launch``
plus the research-lab commands: ``factors|optimize|montecarlo|pairs|
orderbook|sentiment-price|volsurface``, the 0.4.0 market-context commands:
``breadth|macro|stream|reconcile``, and the 0.5.0 terminal wave:
``trades|performance|agents|network|risk``."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def _parse_symbols(text: str) -> list[str]:
    return [s.strip().upper() for s in text.replace(";", ",").split(",")
            if s.strip()]


def cmd_status(_args) -> int:
    from . import env

    print(env.status_table())
    return 0


def cmd_doctor(_args) -> int:
    from . import env

    ok = True

    def check(label: str, passed: bool, hint: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}"
              + (f" — {hint}" if hint and not passed else ""))

    print("trade-suite doctor")
    check("Python >= 3.10", sys.version_info >= (3, 10),
          f"found {sys.version.split()[0]}")
    try:
        import tkinter  # noqa: F401
        check("tkinter (desktop dashboard)", True)
    except ImportError:
        check("tkinter (desktop dashboard)", False,
              "install python3-tk (Linux) to run the desktop dashboard")
    try:
        import yfinance  # noqa: F401
        print("  [PASS] yfinance (delayed data)")
    except ImportError:
        print("  [SKIP] yfinance not installed — demo data works without it")
    for row in env.module_status():
        check(f"module {row['dist']} {row['version']}",
              row["installed"], f"pip install git+{row['repo']}.git")

    print("\n" + ("All checks passed." if ok else
                  "Some checks failed — see hints above."))
    return 0 if ok else 1


def cmd_demo(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    print(f"Running agent desk on demo data: {', '.join(symbols)} …")
    report = pipeline.run_desk(symbols, source="demo", days=args.days,
                               equity=args.equity)
    print(pipeline.summarize_desk(report))
    return 0


def cmd_backtest(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    params = {}
    for chunk in (args.params or "").split(","):
        if "=" in chunk:
            key, _, value = chunk.partition("=")
            key, value = key.strip(), value.strip()
            try:
                params[key] = int(value)
            except ValueError:
                try:
                    params[key] = float(value)
                except ValueError:
                    params[key] = value
    print(f"Backtesting {args.strategy} on {', '.join(symbols)} …")
    result = pipeline.run_backtest(args.strategy, symbols, params,
                                   source=args.source, days=args.days,
                                   initial_cash=args.equity)
    print(pipeline.summarize_backtest(result))
    return 0


def cmd_launch(args) -> int:
    target = {"web": "trade-dashboard-web",
              "desktop": "trade-dashboard-desktop"}[args.which]
    exe = shutil.which(target)
    if exe is None:
        print(f"{target} is not on PATH. Install it with:\n"
              f"  pip install git+https://github.com/crieck2010/{target}.git")
        return 1
    print(f"Launching {target} …")
    return subprocess.call([exe, *args.extra])


def cmd_sentiment(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    print(f"Scanning sentiment ({args.window_hours}h window): "
          f"{', '.join(symbols)} …")
    scan = pipeline.sentiment_scan(
        symbols, window_hours=args.window_hours,
        min_mentions=args.min_mentions, min_conviction=args.min_conviction)
    print(pipeline.summarize_sentiment(scan))
    return 0


def cmd_paper(args) -> int:
    from . import pipeline
    view = pipeline.paper_overview(args.config)
    print(f"paper account ({view['broker']}): equity ${view['equity']:,.2f} · "
          f"cash ${view['cash']:,.2f} · buying power ${view['buying_power']:,.2f} · "
          f"{'market OPEN' if view['market_open'] else 'market closed'}")
    print(f"positions: {len(view['positions'])} · "
          f"active strategies: {view['active_strategies']} · "
          f"approvals pending: {len(view['pending_approvals'])}")
    for a in view["pending_approvals"]:
        score = a["score"]
        print(f"  #{a['id']} {a['strategy']} [{a['symbols']}]"
              + (f" score={score:.2f}" if score is not None else ""))
    return 0


def cmd_pairs(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    print(f"Screening pairs across {', '.join(symbols)} …")
    result = pipeline.run_pairs_screen(
        symbols, source=args.source, days=args.days,
        lookback=args.lookback, max_pairs=args.max_pairs)
    print(pipeline.summarize_pairs(result))
    return 0


def cmd_orderbook(args) -> int:
    from . import pipeline

    print(f"Simulating {args.side} {args.quantity:g} {args.symbol} "
          f"({args.order_type}) …")
    result = pipeline.run_orderbook_sim(
        symbol=args.symbol, side=args.side, quantity=args.quantity,
        order_type=args.order_type, n_levels=args.levels)
    print(pipeline.summarize_orderbook(result))
    return 0


def cmd_optimize(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    print(f"Optimizing ({args.method}) over {', '.join(symbols)} …")
    result = pipeline.run_optimize(
        symbols, source=args.source, days=args.days,
        method=args.method, max_weight=args.max_weight)
    print(pipeline.summarize_optimize(result))
    return 0


def cmd_montecarlo(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    weights = None
    if args.weights:
        weights = [float(x) for x in args.weights.split(",")]
    print(f"Running Monte Carlo on {', '.join(symbols)} …")
    result = pipeline.run_montecarlo(
        symbols, weights=weights, source=args.source, days=args.days,
        equity=args.equity, n_paths=args.paths, n_steps=args.steps,
        seed=args.seed)
    print(pipeline.summarize_montecarlo(result))
    return 0


def cmd_factors(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    print(f"Running {args.model} factor regressions on "
          f"{', '.join(symbols)} …")
    result = pipeline.run_factor_analysis(
        symbols, source=args.source, days=args.days,
        model=args.model, n_months=args.months)
    print(pipeline.summarize_factors(result))
    return 0


def cmd_sentiment_price(args) -> int:
    from . import pipeline

    print(f"Analyzing sentiment vs price for {args.symbol} …")
    result = pipeline.run_sentiment_price(
        args.symbol, source=args.source, days=args.days)
    print(pipeline.summarize_sentiment_price(result))
    return 0


def cmd_correlation(args) -> int:
    from . import pipeline

    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]
    print(f"Running correlation/EDA over {', '.join(syms)} …")
    result = pipeline.run_correlation(
        syms, source=args.source, days=args.days, method=args.method,
        shrinkage=args.shrinkage, lookback=args.lookback)
    print(pipeline.summarize_correlation(result))
    return 0


def cmd_breadth(args) -> int:
    from . import pipeline

    print(f"Running market-breadth snapshot (preset={args.preset}) …")
    result = pipeline.run_breadth(preset=args.preset, seed=args.seed,
                                  n_days=args.days)
    print(pipeline.summarize_breadth(result))
    return 0


def cmd_macro(args) -> int:
    from . import pipeline

    print(f"Running macro regime snapshot (preset={args.preset}) …")
    result = pipeline.run_macro(preset=args.preset, seed=args.seed,
                                days=args.days)
    print(pipeline.summarize_macro(result))
    return 0


def cmd_stream(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    print(f"Running demo tick stream: {', '.join(symbols)} "
          f"({args.ticks} ticks) …")
    result = pipeline.run_stream_demo(symbols=tuple(symbols), seed=args.seed,
                                      n_ticks=args.ticks)
    print(pipeline.summarize_stream_demo(result))
    return 0


def cmd_reconcile(args) -> int:
    from . import pipeline

    print("DEMO — read-only reconcile against a mock broker")
    result = pipeline.run_reconcile_demo()
    print(pipeline.summarize_reconcile(result))
    return 0


def cmd_volsurface(args) -> int:
    from . import pipeline

    print(f"Fitting SVI vol surface for {args.symbol} …")
    result = pipeline.run_vol_surface(
        symbol=args.symbol, spot=args.spot, risk_free=args.risk_free)
    print(pipeline.summarize_volsurface(result))
    return 0


# -- terminal wave (0.5.0): dashboard monitoring views ------------------------

def _trade_filter_kwargs(args) -> dict:
    return {"ledger_path": args.ledger, "date_from": args.from_date,
            "date_to": args.to, "symbol": args.symbol, "side": args.side,
            "strategy": args.strategy, "agent": args.agent,
            "outcome": args.outcome, "limit": args.limit}


def cmd_trades(args) -> int:
    from . import pipeline

    if getattr(args, "trades_action", None) == "export":
        result = pipeline.run_trades(**_trade_filter_kwargs(args))
        csv_text = pipeline.trades_to_csv(result)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(csv_text)
            print(f"Wrote {len(result.get('trades', []))} rows to {args.out}")
        else:
            print(csv_text, end="")
        return 0

    print("Fetching trade blotter …")
    result = pipeline.run_trades(**_trade_filter_kwargs(args))
    print(pipeline.summarize_trades(result))
    return 0


def cmd_performance(args) -> int:
    from . import pipeline

    if args.source == "backtest" and not args.backtest_path:
        raise RuntimeError(
            "performance --source backtest needs --backtest-path "
            "(a trade-backtest result JSON)")
    print(f"Computing performance analytics ({args.source}) …")
    result = pipeline.run_performance(source=args.source,
                                      backtest_path=args.backtest_path)
    print(pipeline.summarize_performance(result))
    return 0


def cmd_agents(args) -> int:
    from . import pipeline

    print("Fetching agent activity …")
    result = pipeline.run_agent_activity(limit=args.limit)
    print(pipeline.summarize_agent_activity(result))
    return 0


def cmd_network(args) -> int:
    from . import pipeline

    symbols = _parse_symbols(args.symbols)
    print(f"Building correlation network "
          f"({', '.join(symbols) or 'demo universe'}) …")
    result = pipeline.run_network(
        symbols=symbols or None, source=args.source, days=args.days,
        method=args.method, seed=args.seed)
    print(pipeline.summarize_network(result))
    return 0


def cmd_risk(args) -> int:
    from . import pipeline

    print("Fetching risk monitor …")
    result = pipeline.run_risk_monitor(vol_days=args.vol_days)
    print(pipeline.summarize_risk_monitor(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade-suite",
        description="Meta-package CLI for the trade-suite trading system")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show installed suite modules and versions")

    sub.add_parser("doctor", help="diagnose the environment")

    demo = sub.add_parser("demo", help="run the agent desk on demo data")
    demo.add_argument("--symbols", default="SPY,AAPL")
    demo.add_argument("--days", type=int, default=250)
    demo.add_argument("--equity", type=float, default=100_000.0)

    bt = sub.add_parser("backtest", help="backtest a strategy")
    bt.add_argument("--strategy", default="donchian_breakout")
    bt.add_argument("--symbols", default="SPY")
    bt.add_argument("--params", default="entry=20,exit=10",
                    help="comma-separated key=value pairs")
    bt.add_argument("--source", default="demo", choices=["demo", "equities"])
    bt.add_argument("--days", type=int, default=250)
    bt.add_argument("--equity", type=float, default=100_000.0)

    launch = sub.add_parser("launch", help="launch a dashboard")
    launch.add_argument("which", choices=["web", "desktop"])
    launch.add_argument("extra", nargs=argparse.REMAINDER,
                        help="extra args passed to the dashboard")

    paper = sub.add_parser("paper", help="paper-trading overview (paper only)")
    paper.add_argument("--config", default="paper-config.json",
                       help="path to the trade-paper config")

    sent = sub.add_parser("sentiment", help="scan social/news sentiment pops")
    sent.add_argument("--symbols", default="SPY,AAPL,MSFT,NVDA,TSLA",
                      help="comma-separated symbols")
    sent.add_argument("--window-hours", type=int, default=24,
                      help="chatter window in hours")
    sent.add_argument("--min-mentions", type=int, default=5,
                      help="minimum mentions to count as a pop")
    sent.add_argument("--min-conviction", type=float, default=5.0,
                      help="0-10 conviction bar for keeping a pop")

    pairs = sub.add_parser("pairs", help="screen a universe for cointegrated pairs")
    pairs.add_argument("--symbols", default="SPY,QQQ,AAPL,MSFT,NVDA",
                       help="comma-separated symbols")
    pairs.add_argument("--source", default="demo", choices=["demo", "equities"])
    pairs.add_argument("--days", type=int, default=300)
    pairs.add_argument("--lookback", type=int, default=252)
    pairs.add_argument("--max-pairs", type=int, default=10)

    ob = sub.add_parser("orderbook", help="simulate an order against a seeded book")
    ob.add_argument("--symbol", default="DEMO")
    ob.add_argument("--side", default="buy", choices=["buy", "sell"])
    ob.add_argument("--quantity", type=float, default=100.0)
    ob.add_argument("--order-type", default="market", choices=["market", "limit"])
    ob.add_argument("--levels", type=int, default=5,
                    help="seeded book depth per side")

    opt = sub.add_parser("optimize", help="optimize a long-only portfolio")
    opt.add_argument("--symbols", default="SPY,AAPL,MSFT")
    opt.add_argument("--source", default="demo", choices=["demo", "equities"])
    opt.add_argument("--days", type=int, default=250)
    opt.add_argument("--method", default="max_sharpe",
                     choices=["max_sharpe", "min_variance", "risk_parity",
                              "equal_weight"])
    opt.add_argument("--max-weight", type=float, default=1.0)

    mc = sub.add_parser("montecarlo", help="simulated portfolio VaR/CVaR")
    mc.add_argument("--symbols", default="SPY,AAPL")
    mc.add_argument("--weights", default="",
                    help="comma-separated weights (default: equal)")
    mc.add_argument("--source", default="demo", choices=["demo", "equities"])
    mc.add_argument("--days", type=int, default=250)
    mc.add_argument("--equity", type=float, default=100_000.0)
    mc.add_argument("--paths", type=int, default=5_000)
    mc.add_argument("--steps", type=int, default=252)
    mc.add_argument("--seed", type=int, default=7)

    fac = sub.add_parser("factors", help="Fama-French factor regressions + GRS")
    fac.add_argument("--symbols", default="SPY,AAPL")
    fac.add_argument("--source", default="demo", choices=["demo", "equities"])
    fac.add_argument("--days", type=int, default=1500)
    fac.add_argument("--model", default="ff5",
                     choices=["ff3", "ff5", "carhart"])
    fac.add_argument("--months", type=int, default=60)

    sp = sub.add_parser("sentiment-price",
                        help="sentiment-vs-price verdict bundle")
    sp.add_argument("--symbol", default="DEMO")
    sp.add_argument("--source", default="demo", choices=["demo", "equities"])
    sp.add_argument("--days", type=int, default=180)

    vs = sub.add_parser("volsurface", help="fit an SVI vol surface (demo quotes)")
    vs.add_argument("--symbol", default="SPY")
    vs.add_argument("--spot", type=float, default=None)
    vs.add_argument("--risk-free", type=float, default=0.03)

    co = sub.add_parser("correlate", help="correlation/EDA report (trade-eda)")
    co.add_argument("--symbols", default="SPY,QQQ,IWM,DIA")
    co.add_argument("--source", default="demo", choices=["demo", "equities"])
    co.add_argument("--days", type=int, default=365)
    co.add_argument("--method", default="pearson",
                    choices=["pearson", "spearman"])
    co.add_argument("--shrinkage", default="ledoit_wolf",
                    choices=["ledoit_wolf", "sample"])
    co.add_argument("--lookback", type=int, default=252)

    br = sub.add_parser("breadth",
                        help="market-breadth regime snapshot (trade-breadth)")
    br.add_argument("--preset", default="standard")
    br.add_argument("--seed", type=int, default=7)
    br.add_argument("--days", type=int, default=600)

    ma = sub.add_parser("macro", help="macro regime snapshot (trade-macro)")
    ma.add_argument("--preset", default="standard")
    ma.add_argument("--seed", type=int, default=42)
    ma.add_argument("--days", type=int, default=600)

    st = sub.add_parser("stream", help="demo tick stream (trade-stream)")
    st.add_argument("--symbols", default="AAA,BBB,CCC",
                    help="comma-separated symbols")
    st.add_argument("--seed", type=int, default=7)
    st.add_argument("--ticks", type=int, default=600)

    sub.add_parser("reconcile",
                   help="DEMO: reconcile the paper ledger against a mock "
                        "broker (trade-paper v0.2.0 machinery, read-only)")

    # -- terminal wave (0.5.0) --
    def _trade_filters(p: argparse.ArgumentParser) -> None:
        p.add_argument("--from", dest="from_date", default=None,
                       help="filter: created on/after YYYY-MM-DD")
        p.add_argument("--to", default=None,
                       help="filter: created on/before YYYY-MM-DD")
        p.add_argument("--symbol", default=None)
        p.add_argument("--side", default=None, choices=["buy", "sell"])
        p.add_argument("--strategy", default=None)
        p.add_argument("--agent", default=None,
                       help="substring match over strategy + order id")
        p.add_argument("--outcome", default=None,
                       choices=["win", "loss", "open", "unknown"])
        p.add_argument("--limit", type=int, default=500)
        p.add_argument("--ledger", default=None,
                       help="paper-ledger path (default: resolve standard "
                            "locations)")

    tr = sub.add_parser("trades",
                        help="paper-ledger trade blotter (read-only)")
    _trade_filters(tr)
    tr_sub = tr.add_subparsers(dest="trades_action")
    tr_exp = tr_sub.add_parser("export", help="export the blotter as CSV")
    _trade_filters(tr_exp)
    tr_exp.add_argument("--format", default="csv", choices=["csv"],
                        help="export format (csv only for now)")
    tr_exp.add_argument("--out", default=None,
                        help="write to FILE instead of stdout")

    pf = sub.add_parser("performance",
                        help="equity/drawdown/monthly/rolling analytics")
    pf.add_argument("--source", default="paper", choices=["paper", "backtest"])
    pf.add_argument("--backtest-path", default=None,
                    help="JSON path to a trade-backtest result "
                         "(with --source backtest)")

    ag = sub.add_parser("agents",
                        help="agent track-record leaderboards, Elo, debates")
    ag.add_argument("--limit", type=int, default=50)

    nw = sub.add_parser("network",
                        help="correlation MST network (trade-eda maths)")
    nw.add_argument("--symbols", default="",
                    help="comma-separated symbols; empty = seeded demo "
                         "universe (no network)")
    nw.add_argument("--source", default="yfinance",
                    choices=["yfinance", "demo"])
    nw.add_argument("--days", type=int, default=252)
    nw.add_argument("--method", default="pearson",
                    choices=["pearson", "spearman"])
    nw.add_argument("--seed", type=int, default=7)

    rk = sub.add_parser("risk",
                        help="exposures, vol regime, kill-switch, "
                             "regime-conviction gauge")
    rk.add_argument("--vol-days", type=int, default=63,
                    help="vol-regime timeline length in days")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {
        "status": cmd_status,
        "doctor": cmd_doctor,
        "demo": cmd_demo,
        "backtest": cmd_backtest,
        "paper": cmd_paper,
        "sentiment": cmd_sentiment,
        "pairs": cmd_pairs,
        "orderbook": cmd_orderbook,
        "optimize": cmd_optimize,
        "montecarlo": cmd_montecarlo,
        "factors": cmd_factors,
        "sentiment-price": cmd_sentiment_price,
        "volsurface": cmd_volsurface,
        "correlate": cmd_correlation,
        "breadth": cmd_breadth,
        "macro": cmd_macro,
        "stream": cmd_stream,
        "reconcile": cmd_reconcile,
        "trades": cmd_trades,
        "performance": cmd_performance,
        "agents": cmd_agents,
        "network": cmd_network,
        "risk": cmd_risk,
        "launch": cmd_launch,
    }
    try:
        return commands[args.command](args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
