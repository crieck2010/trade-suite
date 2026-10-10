"""CLI: signals, backtest, validate, report, demo, presets, license, update-check."""

from __future__ import annotations

import argparse
import json
import sys


def _table(rows: list[list], headers: list[str]) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)),
             "  ".join("-" * w for w in widths)]
    for r in rows:
        lines.append("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))
    return "\n".join(lines)


def _emit(obj, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
    else:
        print(obj if isinstance(obj, str) else json.dumps(obj, indent=2, default=str))


def _demo_bars_or_die(args):
    from .demo import demo_bars, BASKETS
    bars = demo_bars(seed=args.seed)
    if args.basket == "all":
        symbols = [s for b in BASKETS.values() for s in b]
    elif args.basket in BASKETS:
        symbols = BASKETS[args.basket]
    else:
        sys.exit(f"unknown basket {args.basket!r}; choose from "
                 f"{sorted(BASKETS) + ['all']}")
    sub = {s: bars[s] for s in symbols}
    return sub, symbols


def _add_demo_args(p):
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--basket", default="trend",
                   help="trend | chop | all (default: trend)")
    p.add_argument("--preset", default="balanced",
                   help="conservative | balanced | aggressive")
    p.add_argument("--json", action="store_true")


def cmd_signals(args):
    from .presets import get_preset
    sub, _ = _demo_bars_or_die(args)
    cfg = get_preset(args.preset)["config"]
    from .strategy import generate_signals
    out = {}
    for symbol, bars in sub.items():
        sigs = generate_signals(bars, cfg)
        recent = [s for s in sigs if s["signal"] != "flat"][-5:]
        out[symbol] = [{"date": s["date"], "signal": s["signal"],
                        "close": next(b["close"] for b in bars if b["date"] == s["date"])}
                       for s in recent]
    _emit(out, args.json)


def _run_pipeline(args):
    from .backtest import run_backtest
    from .demo import demo_benchmark
    from .presets import get_preset
    from .report import build_report
    from .validate import run_validation
    sub, symbols = _demo_bars_or_die(args)
    preset = get_preset(args.preset)
    provenance = {"source": "demo", "basket": args.basket, "symbols": symbols,
                  "seed": args.seed, "preset": args.preset,
                  "delay": "n/a (synthetic)"}
    bt = run_backtest(sub, config=preset["config"], cost_model=preset["costs"],
                      provenance=provenance)
    bench = demo_benchmark(sub, symbols)
    val = run_validation(bt, benchmark_returns=bench)
    return build_report(bt, val, provenance)


def cmd_backtest(args):
    report = _run_pipeline(args)
    b = report["backtest"]
    if args.json:
        _emit({"engine": b["engine"], "metrics": b["metrics"],
               "n_trades": b["n_trades"],
               "costs": report["costs"]["summary"]}, True)
    else:
        m = b["metrics"]
        rows = [
            ["engine", b["engine"]],
            ["trades", b["n_trades"]],
            ["total return", f"{m['total_return']:.2%}"],
            ["CAGR", f"{m['cagr']:.2%}"],
            ["Sharpe", f"{m['sharpe_ratio']:.2f}" if m["sharpe_ratio"] is not None else "n/a"],
            ["max drawdown", f"{m['max_drawdown']:.2%}"],
            ["win rate", f"{m['win_rate']:.1%}" if m["win_rate"] is not None else "n/a"],
            ["profit factor", f"{m['profit_factor']:.2f}" if m["profit_factor"] not in (None, float("inf")) else "n/a"],
            ["total costs", f"${report['costs']['summary']['total_cost']:,.2f}"],
        ]
        print(_table(rows, ["metric", "value (net of costs)"]))


def cmd_validate(args):
    report = _run_pipeline(args)
    v = report["validation"]
    if args.json:
        _emit(v, True)
    else:
        print(f"overall verdict: {v['status']}")
        if v.get("reason"):
            print(f"reason: {v['reason']}")
        rows = [[g["name"], g["verdict"],
                 f"{g['value']:.4f}" if isinstance(g["value"], float) else g["value"],
                 f"{g['threshold']:.4f}" if isinstance(g["threshold"], float) else g["threshold"]]
                for g in v["gates"]]
        print(_table(rows, ["gate", "verdict", "value", "threshold"]))
        for w in v["warnings"]:
            print(f"WARN [{w['name']}]: {w['description']}")


def cmd_report(args):
    _emit(_run_pipeline(args), True)


def cmd_demo(args):
    from .demo import run_demo
    reports = run_demo(seed=args.seed)
    if args.json:
        _emit({k: {"status": r["validation"]["status"],
                   "metrics": r["backtest"]["metrics"]}
               for k, r in reports.items()}, True)
    else:
        rows = []
        for basket, r in reports.items():
            v = r["validation"]
            m = r["backtest"]["metrics"]
            rows.append([basket, v["status"], r["backtest"]["n_trades"],
                         f"{m['sharpe_ratio']:.2f}" if m["sharpe_ratio"] is not None else "n/a",
                         f"{m['max_drawdown']:.1%}"])
        print(_table(rows, ["basket", "verdict", "trades", "sharpe", "max DD"]))
        print("\nPipeline check: trend should PASS, chop should FAIL/WARN.")
        t, c = reports["trend"]["validation"]["status"], reports["chop"]["validation"]["status"]
        if "SKIPPED" in (t, c):
            print(f"CANNOT EVALUATE (trend={t}, chop={c}): trade-overfit is "
                  f"not installed, so no gate verdicts exist. Install it and "
                  f"re-run; a SKIPPED verdict proves nothing.")
        else:
            print("PASS" if t == "PASS" and c in ("FAIL", "WARN")
                  else "CHECK FAILED", f"(trend={t}, chop={c})")


def cmd_presets(args):
    from .presets import PRESETS
    rows = [[name, p["description"]] for name, p in PRESETS.items()]
    print(_table(rows, ["preset", "description"]))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="trade-swing",
                                 description="Reference swing-trend strategy + validation loop")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("signals", help="recent non-flat signals per symbol")
    _add_demo_args(p); p.set_defaults(func=cmd_signals)
    p = sub.add_parser("backtest", help="run the backtest (costs applied)")
    _add_demo_args(p); p.set_defaults(func=cmd_backtest)
    p = sub.add_parser("validate", help="backtest + overfit gates + verdict")
    _add_demo_args(p); p.set_defaults(func=cmd_validate)
    p = sub.add_parser("report", help="full JSON validation report")
    _add_demo_args(p); p.set_defaults(func=cmd_report)
    p = sub.add_parser("demo", help="trend vs chop discrimination check")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_demo)
    p = sub.add_parser("presets", help="list parameter presets")
    p.set_defaults(func=cmd_presets)
    p = sub.add_parser("license", help="license-key hook (stub)")
    p.set_defaults(func=lambda a: _emit(__import__("trade_swing.licensing", fromlist=["check_license"]).check_license(), False))
    p = sub.add_parser("update-check", help="check for a newer release")
    p.set_defaults(func=lambda a: _emit(__import__("trade_swing.licensing", fromlist=["check_update"]).check_update(), False))

    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    main()
