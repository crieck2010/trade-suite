"""Unified CLI: ``trade-suite status|doctor|demo|backtest|paper|sentiment|launch``."""

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
