"""trade-eda CLI: correlation, covariance, and EDA from the terminal."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from . import __version__, analyze, demo_bars
from . import adapters
from .licensing import check_license, check_update


def _load_bars(args) -> dict[str, list[dict]]:
    if args.source == "demo":
        return demo_bars(n_days=args.days, seed=args.seed)
    # Wide CSV: date,SYM1,SYM2,... with closes (first column ignored).
    bars: dict[str, list[dict]] = {}
    with open(args.source, newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows or len(rows[0]) < 2:
        raise ValueError("CSV needs a date column plus >= 2 symbol columns")
    syms = [c for c in rows[0].keys()][1:]
    for s in syms:
        sb = []
        for r in rows:
            try:
                c = float(r[s])
            except (TypeError, ValueError):
                continue
            sb.append({"symbol": s, "timestamp": r[rows[0].keys().__iter__().__next__()],
                       "close": c, "volume": None})
        bars[s] = sb
    return bars


def _emit(obj) -> int:
    json.dump(obj, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def cmd_matrix(args) -> int:
    rep = analyze(_load_bars(args), method=args.method, lookback=args.lookback)
    return _emit({"symbols": rep["symbols"], "method": args.method,
                  "matrix": rep["correlation"]["matrix"]})


def cmd_cov(args) -> int:
    rep = analyze(_load_bars(args), shrinkage=args.shrinkage,
                  lookback=args.lookback)
    return _emit({"symbols": rep["symbols"],
                  "shrinkage": rep["covariance"]["shrinkage"],
                  "shrinkage_delta": rep["covariance"]["shrinkage_delta"],
                  "matrix": rep["covariance"]["matrix"]})


def cmd_describe(args) -> int:
    rep = analyze(_load_bars(args), lookback=args.lookback)
    return _emit(rep["describe"])


def cmd_quality(args) -> int:
    rep = analyze(_load_bars(args), lookback=args.lookback)
    return _emit(rep["quality"])


def cmd_report(args) -> int:
    return _emit(analyze(_load_bars(args), method=args.method,
                         shrinkage=args.shrinkage, lookback=args.lookback))


def cmd_risk(args) -> int:
    return _emit(adapters.corr_for_risk(_load_bars(args)))


def cmd_agent(args) -> int:
    return _emit(adapters.to_agent_eda_report(_load_bars(args)))


def _src(p):
    p.add_argument("--source", default="demo",
                   help="'demo' or path to a wide closes CSV")
    p.add_argument("--days", type=int, default=500)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--lookback", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="trade-eda",
                                 description="Correlation/covariance/EDA")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("matrix", help="correlation matrix"); _src(s)
    s.add_argument("--method", default="pearson",
                   choices=["pearson", "spearman"])
    s.set_defaults(func=cmd_matrix)

    s = sub.add_parser("cov", help="covariance matrix"); _src(s)
    s.add_argument("--shrinkage", default="ledoit_wolf",
                   choices=["ledoit_wolf", "sample"])
    s.set_defaults(func=cmd_cov)

    s = sub.add_parser("describe", help="per-asset summary stats"); _src(s)
    s.set_defaults(func=cmd_describe)

    s = sub.add_parser("quality", help="data-quality report"); _src(s)
    s.set_defaults(func=cmd_quality)

    s = sub.add_parser("report", help="full EDA report"); _src(s)
    s.add_argument("--method", default="pearson",
                   choices=["pearson", "spearman"])
    s.add_argument("--shrinkage", default="ledoit_wolf",
                   choices=["ledoit_wolf", "sample"])
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("risk", help="concentration report for trade-risk")
    _src(s); s.set_defaults(func=cmd_risk)

    s = sub.add_parser("agent", help="agent-ready EDA brief"); _src(s)
    s.set_defaults(func=cmd_agent)

    s = sub.add_parser("license", help="license-key hook")
    s.set_defaults(func=lambda a: _emit(check_license()))
    s = sub.add_parser("update-check", help="check GitHub for a newer release")
    s.set_defaults(func=lambda a: _emit(check_update()))
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"trade-eda: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
