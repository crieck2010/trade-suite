"""Command-line interface for trade-volforecast."""

from __future__ import annotations

import argparse
import csv
import json

from . import __version__, evaluate
from .adapters import to_agent_vol_report, vol_for_optimize, vol_for_risk
from .demo import demo_bars
from .ewma import ewma_forecast
from .garch import fit_garch, fit_gjr, garch_forecast
from .har import har_fit, har_predict
from .licensing import check_license, check_update
from .realized import ESTIMATORS, realized_vol, realized_var_series


def _load_bars(source: str, n: int = 750) -> list[dict]:
    if source == "demo":
        return demo_bars(n)
    bars = []
    with open(source, newline="") as fh:
        for row in csv.DictReader(fh):
            bars.append({k: float(row[k]) for k in ("open", "high", "low", "close")})
    if len(bars) < 60:
        raise SystemExit("need at least 60 bars")
    return bars


def _fmt(fc: dict) -> str:
    ts = ", ".join(f"{v:.2%}" for v in fc["term_structure"][:5])
    return f"{fc['model']}: {fc['vol_annualized']:.2%}  term[{fc['horizon_days']}] {ts}..."


def cmd_realized(args: argparse.Namespace) -> int:
    bars = _load_bars(args.source)
    rows = realized_vol(bars, estimator=args.estimator, window=args.window)
    vols = [r["vol"] for r in rows]
    print(f"{args.estimator}: {len(rows)} windows, last vol {vols[-1]:.2%}, "
          f"mean {sum(vols)/len(vols):.2%}, max {max(vols):.2%}")
    if args.format == "json":
        print(json.dumps(rows[-5:], indent=2))
    return 0


def cmd_garch(args: argparse.Namespace) -> int:
    from .realized import log_returns
    bars = _load_bars(args.source)
    rets = log_returns(bars)
    fit = fit_gjr(rets) if args.asymmetric else fit_garch(rets)
    fc = garch_forecast(fit, horizon=args.horizon)
    p = fit["params"]
    print(f"{fit['model']}: params {[f'{x:.4f}' for x in p]}  "
          f"persistence {fit['persistence']:.4f}  AIC {fit['aic']:.1f}")
    print(_fmt(fc))
    if args.format == "json":
        print(json.dumps({k: fit[k] for k in ("model", "params", "persistence", "aic", "bic")}, indent=2))
    return 0


def cmd_har(args: argparse.Namespace) -> int:
    bars = _load_bars(args.source)
    rv = realized_var_series(bars, window=args.window)
    fit = har_fit(rv)
    fc = har_predict(fit, horizon=args.horizon)
    print(f"har: βd {fit['beta_daily']:.3f} βw {fit['beta_weekly']:.3f} "
          f"βm {fit['beta_monthly']:.3f}  R² {fit['r_squared']:.3f}")
    print(_fmt(fc))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from .realized import log_returns
    bars = _load_bars(args.source)
    rets = log_returns(bars)
    rv = realized_var_series(bars, window=args.window)
    # walk-forward, one-step-ahead: refit every `step` bars on trailing data
    step, hist = 63, 252
    vols, fc_e, fc_g, fc_h = [], [], [], []
    gf = fit_garch(rets[:hist])
    hf = har_fit(rv[: hist - args.window + 1])
    for t in range(hist, len(rv)):
        vols.append(rv[t] ** 0.5 * (252 ** 0.5))
        fc_e.append(ewma_forecast(rets[: t + args.window - 1], horizon=1)["vol_annualized"])
        if (t - hist) % step == 0:
            gf = fit_garch(rets[: t + args.window - 1])
            hf = har_fit(rv[:t])
        fc_g.append(garch_forecast(gf, horizon=1)["vol_annualized"])
        fc_h.append(har_predict(hf, horizon=1)["vol_annualized"])
    table = evaluate.compare(vols, {"ewma": fc_e, "garch": fc_g, "har": fc_h})
    for name, row in table.items():
        print(f"{name:6s}  MSE {row['mse']:.6f}  MAE {row['mae']:.4f}  MZ-R² {row['mz_r2']:.3f}")
    return 0


def cmd_forecast(args: argparse.Namespace) -> int:
    bars = _load_bars(args.source)
    out = vol_for_optimize(bars, horizon=args.horizon, method=args.method)
    print(_fmt(out))
    if args.format == "json":
        print(json.dumps({k: out[k] for k in ("method", "vol_annualized", "term_structure")}, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    bars = _load_bars(args.source)
    rep = to_agent_vol_report(bars, horizon=args.horizon)
    print(json.dumps({k: (f"{v:.2%}" if isinstance(v, float) else v)
                      for k, v in rep.items() if k != "garch" and k != "har" and k != "ewma"}, indent=2))
    for name in ("garch", "har", "ewma"):
        print(f"{name:6s} → {_fmt(rep[name])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-volforecast", description="Volatility forecasting (stdlib-only)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def _src(sp):
        sp.add_argument("--source", default="demo", help="'demo' or path to OHLC CSV")
        sp.add_argument("--format", choices=["text", "json"], default="text")

    s = sub.add_parser("realized", help="rolling realized vol"); _src(s)
    s.add_argument("--estimator", choices=sorted(ESTIMATORS), default="yang_zhang")
    s.add_argument("--window", type=int, default=21)
    s.set_defaults(func=cmd_realized)

    s = sub.add_parser("garch", help="fit GARCH/GJR + forecast"); _src(s)
    s.add_argument("--asymmetric", action="store_true", help="fit GJR-GARCH (leverage)")
    s.add_argument("--horizon", type=int, default=10)
    s.set_defaults(func=cmd_garch)

    s = sub.add_parser("har", help="fit HAR-RV + forecast"); _src(s)
    s.add_argument("--window", type=int, default=21)
    s.add_argument("--horizon", type=int, default=10)
    s.set_defaults(func=cmd_har)

    s = sub.add_parser("compare", help="walk-forward horse race: ewma vs garch vs har"); _src(s)
    s.add_argument("--window", type=int, default=21)
    s.set_defaults(func=cmd_compare)

    s = sub.add_parser("forecast", help="one-shot forward vol forecast"); _src(s)
    s.add_argument("--method", choices=["garch", "har", "ewma"], default="garch")
    s.add_argument("--horizon", type=int, default=21)
    s.set_defaults(func=cmd_forecast)

    s = sub.add_parser("report", help="agent-ready vol briefing"); _src(s)
    s.add_argument("--horizon", type=int, default=10)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("risk", help="current vol regime snapshot"); _src(s)
    s.set_defaults(func=lambda a: (print(json.dumps(vol_for_risk(_load_bars(a.source)), indent=2)), 0)[1])

    s = sub.add_parser("license", help="license-key hook"); s.set_defaults(
        func=lambda a: (print(json.dumps(check_license(), indent=2)), 0)[1])
    s = sub.add_parser("update-check", help="check GitHub for a newer release"); s.set_defaults(
        func=lambda a: (print(json.dumps(check_update(), indent=2)), 0)[1])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
