"""Command-line interface for trade-overfit."""

from __future__ import annotations

import argparse
import csv
import json
import sys

from . import __version__
from .demo import demo_noise_strategies, demo_selection_bias, demo_true_edge
from .dsr import dsr_from_returns
from .gates import PRESETS, evaluate_gates, preset_gates, validate
from .licensing import check_license, check_update
from .metrics import performance_summary
from .walkforward import walk_forward


def read_returns_csv(path: str) -> list[float]:
    """Read a single column of returns; skips a non-numeric header row."""
    out: list[float] = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            try:
                out.append(float(row[0]))
            except ValueError:
                continue  # header or junk row
    if not out:
        raise SystemExit(f"no numeric returns found in {path}")
    return out


def _emit(payload: dict, fmt: str) -> int:
    if fmt == "json":
        print(json.dumps(payload, indent=2, default=str))
    elif fmt == "csv":
        _emit_csv(payload)
    else:
        _emit_table(payload)
    return 0


def _emit_csv(payload: dict) -> None:
    kind = payload.get("_kind", "verdict")
    if kind == "gates":
        w = csv.writer(sys.stdout)
        w.writerow(["gate", "metric", "op", "threshold", "value", "passed"])
        for g in payload["gates"]:
            w.writerow([g["name"], g["metric"], g["op"], g["threshold"], g["value"], g["passed"]])
    elif kind == "metrics":
        w = csv.writer(sys.stdout)
        w.writerow(["metric", "value"])
        for k, v in payload["metrics"].items():
            w.writerow([k, v])
    else:
        w = csv.writer(sys.stdout)
        w.writerow(["field", "value"])
        w.writerow(["verdict", payload["verdict"]])
        w.writerow(["gates_passed", f'{payload["n_gates_passed"]}/{payload["n_gates"]}'])
        for g in payload["gates"]:
            w.writerow([f'gate:{g["name"]}', "PASS" if g["passed"] else "FAIL"])


def _fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.4f}"
    return str(v)


def _emit_table(payload: dict) -> None:
    kind = payload.get("_kind", "verdict")
    if kind == "gates":
        print(f'{"gate":<22}{"value":>12}{"threshold":>12}{"result":>8}')
        for g in payload["gates"]:
            mark = "PASS" if g["passed"] else "FAIL"
            print(f'{g["name"]:<22}{_fmt(g["value"]):>12}{_fmt(g["threshold"]):>12}{mark:>8}')
    elif kind == "metrics":
        for k, v in payload["metrics"].items():
            print(f"{k:<28}{_fmt(v)}")
    elif kind == "dsr":
        d = payload["dsr"]
        for k in ("sharpe_hat", "n_obs", "n_trials", "expected_sharpe_under_null", "dsr"):
            print(f"{k:<28}{_fmt(d[k])}")
    elif kind == "walkforward":
        s = payload["summary"]
        for k in ("n_windows", "median_oos_sharpe", "mean_oos_sharpe",
                  "oos_hit_rate", "mean_is_sharpe", "degradation"):
            print(f"{k:<28}{_fmt(s[k])}")
    else:  # verdict
        print(f'verdict: {payload["verdict"]} '
              f'({payload["n_gates_passed"]}/{payload["n_gates"]} gates passed)')
        print(f'{"gate":<22}{"value":>12}{"threshold":>12}{"result":>8}')
        for g in payload["gates"]:
            mark = "PASS" if g["passed"] else "FAIL"
            print(f'{g["name"]:<22}{_fmt(g["value"]):>12}{_fmt(g["threshold"]):>12}{mark:>8}')


def _common_output(p: argparse.ArgumentParser) -> None:
    p.add_argument("--format", choices=["table", "json", "csv"], default="table")
    p.add_argument("--rf", type=float, default=0.0, help="annualized risk-free rate")


def _common_series(p: argparse.ArgumentParser) -> None:
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", help="CSV file with one returns column")
    src.add_argument("--demo", choices=["edge", "noise-winner"],
                     help="seeded demo series: true edge, or best-of-1000 noise winner")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--benchmark", help="CSV file with benchmark returns column")
    p.add_argument("--cost-bps", type=float, default=0.0)
    p.add_argument("--trades-per-year", type=float, default=252.0)
    p.add_argument("--trials", type=int, default=1,
                   help="number of strategies tried (N for the DSR)")


def _load_series(args) -> tuple[list[float], list[float] | None, list[float] | None]:
    trials = None
    if args.csv:
        rets = read_returns_csv(args.csv)
    elif args.demo == "edge":
        rets = demo_true_edge(seed=args.seed)
    else:  # noise-winner: reconstruct the best-of-1000 noise series deterministically
        demo = demo_selection_bias(seed=args.seed)
        rets = demo_noise_strategies(
            demo["n_strategies"], demo["n_obs"], args.seed)[demo["best_idx"]]
        trials = demo["trial_sharpes"]
    bench = read_returns_csv(args.benchmark) if args.benchmark else None
    return rets, bench, trials


def cmd_validate(args) -> int:
    rets, bench, trials = _load_series(args)
    n_trials = len(trials) if trials else args.trials
    if n_trials > 1 and not trials:
        print("note: --trials > 1 but no trial Sharpes available; "
              "DSR needs the trial Sharpe distribution for a real correction",
              file=sys.stderr)
    verdict = validate(rets, benchmark=bench, rf_annual=args.rf,
                       cost_bps_per_trade=args.cost_bps,
                       trades_per_year=args.trades_per_year,
                       trial_sharpes=trials,
                       gates=preset_gates(args.preset))
    verdict["_kind"] = "verdict"
    return _emit(verdict, args.format)


def cmd_dsr(args) -> int:
    rets, _, trials = _load_series(args)
    d = dsr_from_returns(rets, trials, rf_annual=args.rf)
    return _emit({"_kind": "dsr", "dsr": d}, args.format)


def cmd_walkforward(args) -> int:
    rets, _, _ = _load_series(args)
    wf = walk_forward(rets, train_len=args.train_len, test_len=args.test_len,
                      anchored=args.anchored, rf_annual=args.rf)
    wf["_kind"] = "walkforward"
    return _emit(wf, args.format)


def cmd_gates(args) -> int:
    rets, bench, trials = _load_series(args)
    verdict = validate(rets, benchmark=bench, rf_annual=args.rf,
                       cost_bps_per_trade=args.cost_bps,
                       trades_per_year=args.trades_per_year,
                       trial_sharpes=trials,
                       gates=preset_gates(args.preset))
    return _emit({"_kind": "gates", "gates": verdict["gates"],
                  "n_gates_passed": verdict["n_gates_passed"],
                  "n_gates": verdict["n_gates"]}, args.format)


def cmd_metrics(args) -> int:
    rets, _, _ = _load_series(args)
    summary = performance_summary(rets, rf_annual=args.rf)
    return _emit({"_kind": "metrics", "metrics": summary}, args.format)


def cmd_presets(args) -> int:
    for name, gates in PRESETS.items():
        print(f"[{name}]")
        for g in gates:
            print(f"  {g.name:<22}{g.op} {g.threshold}")
    return 0


def cmd_license(args) -> int:
    print(json.dumps(check_license(args.key), indent=2))
    return 0


def cmd_update_check(args) -> int:
    print(json.dumps(check_update(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade-overfit",
                                description="The overfitting desk: validate strategies, kill fake alpha.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="full desk pipeline: metrics -> DSR -> walk-forward -> regimes -> gates")
    _common_series(v); _common_output(v)
    v.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    v.set_defaults(func=cmd_validate)

    d = sub.add_parser("dsr", help="deflated Sharpe ratio of a returns series")
    _common_series(d); _common_output(d)
    d.set_defaults(func=cmd_dsr)

    w = sub.add_parser("walk-forward", help="walk-forward train/test analysis")
    _common_series(w); _common_output(w)
    w.add_argument("--train-len", type=int, default=252)
    w.add_argument("--test-len", type=int, default=63)
    w.add_argument("--anchored", action="store_true")
    w.set_defaults(func=cmd_walkforward)

    g = sub.add_parser("gates", help="evaluate the gate set and show per-gate evidence")
    _common_series(g); _common_output(g)
    g.add_argument("--preset", choices=sorted(PRESETS), default="standard")
    g.set_defaults(func=cmd_gates)

    m = sub.add_parser("metrics", help="performance summary of a returns series")
    _common_series(m); _common_output(m)
    m.set_defaults(func=cmd_metrics)

    pr = sub.add_parser("presets", help="list gate presets and thresholds")
    pr.set_defaults(func=cmd_presets)

    li = sub.add_parser("license", help="license-key hook (stubbed)")
    li.add_argument("--key", default=None)
    li.set_defaults(func=cmd_license)

    u = sub.add_parser("update-check", help="check for a newer release (stubbed)")
    u.set_defaults(func=cmd_update_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
