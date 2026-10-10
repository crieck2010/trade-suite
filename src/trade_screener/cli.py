"""Command-line interface for trade-screener."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from . import __version__
from .adapters import bars_from_trade_data, tickers_from_universe
from .demo import demo_fundamentals, demo_universe
from .fundamentals import load_fundamentals_csv
from .licensing import check_license, check_update
from .models import Criterion, ScoreSpec
from .screen import (
    PRESETS,
    SCORE_PRESETS,
    compute_metrics,
    preset_criteria,
    preset_score_spec,
    score,
    screen,
)


def _parse_criterion(text: str) -> Criterion:
    """Parse ``metric:op:value`` or ``metric:between:lo,hi``."""
    parts = text.split(":")
    if len(parts) < 3:
        raise ValueError(f"bad criterion {text!r}; expected metric:op:value")
    metric, op = parts[0].strip(), parts[1].strip()
    rest = ":".join(parts[2:])
    if op in ("between", "outside"):
        lo_s, hi_s = rest.split(",")
        value = (float(lo_s), float(hi_s))
    else:
        value = float(rest)
    return Criterion(metric=metric, op=op, value=value)


def _load_universe(args) -> tuple[str, dict[str, list[dict]]]:
    if args.demo:
        data = demo_universe(n=args.demo_n, days=args.days, seed=args.seed)
        return f"demo(n={args.demo_n})", data
    if args.universe:
        name, tickers = tickers_from_universe(args.universe)
    elif args.tickers:
        name = "cli"
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        raise SystemExit("need one of --demo, --universe FILE, or --tickers A,B,C")
    data = bars_from_trade_data(tickers, source=args.source, days=args.days)
    return name, data


def _load_fundamentals(args, tickers: list[str]) -> dict[str, dict]:
    if args.fundamentals:
        return load_fundamentals_csv(args.fundamentals)
    if args.demo:
        return demo_fundamentals(tickers, seed=args.seed)
    return {}


def _fmt_number(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.4f}"
    return str(v)


def cmd_scan(args) -> int:
    name, data = _load_universe(args)
    fundamentals = _load_fundamentals(args, list(data))
    criteria = list(preset_criteria(args.preset)) if args.preset else []
    for text in args.criterion or []:
        criteria.append(_parse_criterion(text))
    if not criteria:
        print("no criteria given: use --preset NAME and/or --criterion metric:op:value", file=sys.stderr)
        return 2
    report = screen(data, criteria, fundamentals, universe=name)
    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, default=str))
    elif args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["ticker", "passed"] + [c.describe() for c in criteria])
        for row in report.rows:
            writer.writerow([row.ticker, int(row.passed)] + [int(c["passed"]) for c in row.checks])
    else:
        print(f"universe: {name}  scanned: {len(report.rows)}  passed: {len(report.passed_tickers)}")
        for c in criteria:
            print(f"  filter: {c.describe()}")
        print(f"  passed: {', '.join(report.passed_tickers) or '(none)'}")
    return 0


def cmd_score(args) -> int:
    name, data = _load_universe(args)
    fundamentals = _load_fundamentals(args, list(data))
    if args.score_preset:
        spec = preset_score_spec(args.score_preset)
    else:
        weights = {}
        for text in args.weight or []:
            metric, w = text.split("=")
            weights[metric.strip()] = float(w)
        if not weights:
            print("need --score-preset NAME or --weight metric=w ...", file=sys.stderr)
            return 2
        spec = ScoreSpec(weights=weights)
    ranked = score(data, spec, fundamentals)
    if args.top:
        ranked = ranked[: args.top]
    if args.format == "json":
        print(json.dumps([r.to_dict() for r in ranked], indent=2, default=str))
    else:
        print(f"universe: {name}  ranked by {sorted(spec.weights)}")
        print(f"{'rank':>4}  {'ticker':<8}  {'score':>8}")
        for i, r in enumerate(ranked, 1):
            print(f"{i:>4}  {r.ticker:<8}  {r.score:>8.3f}")
    return 0


def cmd_metrics(args) -> int:
    _name, data = _load_universe(args)
    fundamentals = _load_fundamentals(args, list(data))
    ticker = args.ticker.strip().upper()
    if ticker not in data:
        print(f"{ticker} not in universe", file=sys.stderr)
        return 2
    metrics = compute_metrics(data[ticker], fundamentals.get(ticker))
    if args.format == "json":
        print(json.dumps({ticker: metrics}, indent=2, default=str))
    else:
        print(f"metrics for {ticker}:")
        for k in sorted(metrics):
            print(f"  {k:<16} {_fmt_number(metrics[k])}")
    return 0


def cmd_presets(_args) -> int:
    print("filter presets:")
    for name in sorted(PRESETS):
        print(f"  {name}:")
        for c in preset_criteria(name):
            print(f"    - {c.describe()}")
    print("score presets:")
    for name in sorted(SCORE_PRESETS):
        print(f"  {name}: {SCORE_PRESETS[name]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-screener", description="Multi-symbol equity screener")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_data(sp: argparse.ArgumentParser) -> None:
        src = sp.add_mutually_exclusive_group()
        src.add_argument("--demo", action="store_true", help="use the seeded synthetic universe")
        src.add_argument("--universe", help="CSV universe file (ticker column)")
        src.add_argument("--tickers", help="comma-separated tickers")
        sp.add_argument("--source", default="demo", help="bar data source (default: demo)")
        sp.add_argument("--days", type=int, default=300)
        sp.add_argument("--seed", type=int, default=7)
        sp.add_argument("--demo-n", type=int, default=12)
        sp.add_argument("--fundamentals", help="fundamentals CSV path")
        sp.add_argument("--format", choices=["table", "json", "csv"], default="table")

    s = sub.add_parser("scan", help="filter a universe through criteria")
    add_data(s)
    s.add_argument("--preset", choices=sorted(PRESETS))
    s.add_argument("--criterion", action="append", help="metric:op:value (repeatable)")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("score", help="rank a universe by composite z-score")
    add_data(s)
    s.add_argument("--score-preset", choices=sorted(SCORE_PRESETS))
    s.add_argument("--weight", action="append", help="metric=w (repeatable)")
    s.add_argument("--top", type=int, help="show only the top N")
    s.set_defaults(func=cmd_score)

    s = sub.add_parser("metrics", help="show all metrics for one ticker")
    add_data(s)
    s.add_argument("ticker")
    s.set_defaults(func=cmd_metrics)

    s = sub.add_parser("presets", help="list built-in filter and score presets")
    s.set_defaults(func=cmd_presets)

    s = sub.add_parser("license", help="check the license-key hook")
    s.set_defaults(func=lambda a: (print(json.dumps(check_license(), indent=2)), 0)[1])

    s = sub.add_parser("update-check", help="check for a newer release")
    s.set_defaults(func=lambda a: (print(json.dumps(check_update(), indent=2)), 0)[1])

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
