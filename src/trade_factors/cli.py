"""Command-line interface for trade-factors."""

from __future__ import annotations

import argparse
import csv
import json

from . import __version__
from .adapters import to_agent_factor_report
from .factors import demo_factors, load_french_csv
from .licensing import check_license, check_update
from .models import grs_test, panel_regressions


def load_factors(source: str):
    if source == "demo":
        return demo_factors()
    return load_french_csv(source)


def read_assets_csv(path: str) -> tuple[list[str], dict[str, list[float]]]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    dates = [r["date"] for r in rows]
    names = [c for c in rows[0] if c != "date"]
    assets = {n: [float(r[n]) for r in rows] for n in names}
    return dates, assets


def align(factors, dates):
    """Trim factor data to the asset dates (inner join on date strings)."""
    idx = [i for i, d in enumerate(factors.dates) if d in set(dates)]
    keep = set(dates)
    return type(factors)(
        [d for d in factors.dates if d in keep],
        {k: [v for d, v in zip(factors.dates, col) if d in keep]
         for k, col in factors.factors.items()},
        factors.freq,
    )


def cmd_factors(args: argparse.Namespace) -> int:
    f = load_factors(args.source)
    s = f.summary()
    if args.format == "json":
        print(json.dumps({"freq": f.freq, "nobs": len(f.dates),
                          "summary": s}, indent=2))
        return 0
    print(f"{len(f.dates)} {f.freq} observations")
    for nm, st in s.items():
        print(f"{nm:>6}: ann.mean {st['annualized_mean']:+.2%}  "
              f"ann.vol {st['annualized_vol']:.2%}")
    return 0


def cmd_regress(args: argparse.Namespace) -> int:
    factors = load_factors(args.factors)
    dates, assets = read_assets_csv(args.assets)
    factors = align(factors, dates)
    assets = {a: factors.excess(r) for a, r in assets.items()}
    results = panel_regressions(assets, factors, args.model)
    if args.format == "json":
        print(json.dumps(to_agent_factor_report(results), indent=2))
        return 0
    for a, r in results.items():
        d = r.summary_dict()
        betas = " ".join(f"{k}={v:+.2f}" for k, v in d["params"].items()
                         if k != "alpha")
        print(f"{a}: alpha={d['params']['alpha']:+.4f} "
              f"(t={d['tvalues']['alpha']:+.2f}) {betas} R²={d['rsquared']:.3f}")
    return 0


def cmd_grs(args: argparse.Namespace) -> int:
    factors = load_factors(args.factors)
    dates, assets = read_assets_csv(args.assets)
    factors = align(factors, dates)
    assets = {a: factors.excess(r) for a, r in assets.items()}
    results = panel_regressions(assets, factors, args.model)
    g = grs_test(results, factors, args.model)
    print(f"GRS F({g['df1']},{g['df2']}) = {g['F']:.3f}, p = {g['pvalue']:.4f}")
    print("reject: all alphas jointly zero" if g["pvalue"] < 0.05
          else "fail to reject: alphas jointly zero")
    return 0


def cmd_license(_args: argparse.Namespace) -> int:
    print(json.dumps(check_license(), indent=2))
    return 0


def cmd_update_check(_args: argparse.Namespace) -> int:
    print(json.dumps(check_update(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="trade-factors",
                                 description="Fama-French factor analysis")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("factors", help="summarize a factor dataset")
    p.add_argument("--source", default="demo",
                   help="'demo' or path to a Ken French CSV")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_factors)

    p = sub.add_parser("regress", help="time-series factor regressions")
    p.add_argument("--assets", required=True, help="CSV: date,A,B,... (returns)")
    p.add_argument("--factors", default="demo")
    p.add_argument("--model", choices=["ff3", "ff5", "carhart"], default="ff5")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.set_defaults(func=cmd_regress)

    p = sub.add_parser("grs", help="GRS test of joint alphas")
    p.add_argument("--assets", required=True)
    p.add_argument("--factors", default="demo")
    p.add_argument("--model", choices=["ff3", "ff5", "carhart"], default="ff5")
    p.set_defaults(func=cmd_grs)

    p = sub.add_parser("license", help="check the license-key hook")
    p.set_defaults(func=cmd_license)
    p = sub.add_parser("update-check", help="check for a newer release")
    p.set_defaults(func=cmd_update_check)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
