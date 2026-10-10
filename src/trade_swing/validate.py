"""Validation: overfit gates + honesty checks, via lazy trade-overfit.

Runs the sibling's deflated-Sharpe / walk-forward / regime gates on the
cost-adjusted returns, then layers three WARN-level sanity checks of our
own (sample size, cost drag, concentration). Verdicts:

- PASS / FAIL per gate, with the numeric margin to the threshold.
- WARN for "technically passes but don't trust it" conditions.
- SKIPPED (loud, never silent) when trade-overfit is not installed.

Overall verdict: FAIL if any gate fails; WARN if any warning fires;
SKIPPED if the sibling is absent; PASS otherwise.
"""

from __future__ import annotations

import importlib


def _try_import_trade_overfit():
    try:
        gates = importlib.import_module("trade_overfit.gates")
        dsr = importlib.import_module("trade_overfit.dsr")
        walkforward = importlib.import_module("trade_overfit.walkforward")
        regimes = importlib.import_module("trade_overfit.regimes")
        metrics = importlib.import_module("trade_overfit.metrics")
    except ImportError:
        return None
    return {"gates": gates, "dsr": dsr, "walkforward": walkforward,
            "regimes": regimes, "metrics": metrics}


def _returns_from_curve(equity_curve: list[dict]) -> list[float]:
    out = []
    for prev, cur in zip(equity_curve, equity_curve[1:]):
        out.append(cur["equity"] / prev["equity"] - 1.0 if prev["equity"] else 0.0)
    return out


def _skipped_result(reason: str, gate_names: list[str]) -> dict:
    return {
        "status": "SKIPPED",
        "reason": reason,
        "gate_preset": None,
        "gates": [{"name": n, "verdict": "SKIPPED", "value": None,
                   "threshold": None, "margin": None,
                   "description": "trade-overfit not installed"} for n in gate_names],
        "warnings": [],
        "evidence": {},
    }


def _warn_checks(backtest_result: dict) -> list[dict]:
    """Our own honesty layer. A gate can pass while the result is still
    untrustworthy; these say so out loud."""
    warnings = []
    trades = backtest_result.get("trades", [])
    costs = backtest_result.get("costs", {})
    n = len(trades)
    if n < 30:
        warnings.append({
            "name": "sample_size",
            "verdict": "WARN",
            "value": n,
            "threshold": 30,
            "description": f"Only {n} closed trades: gates are computed on a "
                           "thin sample. Prefer hundreds of trades or treat "
                           "any PASS as provisional.",
        })
    drag = costs.get("cost_drag")
    if drag is not None and drag > 0.5:
        warnings.append({
            "name": "cost_drag",
            "verdict": "WARN",
            "value": drag,
            "threshold": 0.5,
            "description": f"Costs erase {drag:.0%} of gross P&L: the edge, "
                           "if any, lives inside the cost assumptions.",
        })
    if trades:
        pnls = [abs(t["pnl_net"]) for t in trades]
        total = sum(pnls)
        if total > 0:
            concentration = max(pnls) / total
            if concentration > 0.5:
                warnings.append({
                    "name": "concentration",
                    "verdict": "WARN",
                    "value": concentration,
                    "threshold": 0.5,
                    "description": "One trade is >50% of total absolute P&L: "
                                   "the result is a story about one trade, "
                                   "not a strategy.",
                })
    return warnings


def run_validation(backtest_result: dict, gate_preset: str = "standard",
                   benchmark_returns: list[float] | None = None,
                   warn_checks: bool = True) -> dict:
    """Validate a ``run_backtest`` result. Plain data in, plain data out."""
    gate_names = ["deflated_sharpe", "oos_sharpe", "max_drawdown",
                  "regime_stability", "beats_benchmark_net"]
    of = _try_import_trade_overfit()
    if of is None:
        return _skipped_result(
            "trade-overfit is not installed: gate verdicts cannot be "
            "computed. Install trade-overfit and re-run; until then this "
            "report proves nothing.", gate_names)

    rets = _returns_from_curve(backtest_result["equity_curve"])
    if len(rets) < 2:
        return _skipped_result("equity curve too short for gates", gate_names)

    # --- evidence (mirrors trade_overfit.gates.validate, built by hand so
    # --- the WARN layer and verdict mapping stay in this repo) ---
    dsr = of["dsr"].dsr_from_returns(rets)  # N=1: params were NOT optimized
    wf = of["walkforward"].walk_forward(rets, train_len=252, test_len=63)
    reg = of["regimes"].regime_report(rets)
    summary = of["metrics"].performance_summary(rets)

    bench_excess = None
    if benchmark_returns is not None and len(benchmark_returns) == len(rets):
        strat_ann = summary.get("annualized_return")
        bench_ann = of["metrics"].performance_summary(
            benchmark_returns).get("annualized_return")
        if strat_ann is not None and bench_ann is not None:
            bench_excess = strat_ann - bench_ann

    evidence = {
        "dsr": dsr.get("dsr"),
        "median_oos_sharpe": (wf.get("summary") or {}).get("median_oos_sharpe"),
        "max_drawdown": summary.get("max_drawdown"),
        "worst_regime_sharpe": reg.get("worst_regime_sharpe"),
        "excess_return_vs_benchmark_after_costs": bench_excess,
    }

    gates = of["gates"].preset_gates(gate_preset)
    raw = of["gates"].evaluate_gates(evidence, gates)
    verdicts = []
    for g in raw:
        margin = None
        if g["value"] is not None:
            margin = (g["value"] - g["threshold"] if g["op"] in ("gte", "gt")
                      else g["threshold"] - g["value"])
        verdicts.append({
            "name": g["name"],
            "verdict": "PASS" if g["passed"] else "FAIL",
            "metric": g["metric"],
            "op": g["op"],
            "value": g["value"],
            "threshold": g["threshold"],
            "margin": margin,
            "description": g["description"],
        })

    warnings = _warn_checks(backtest_result) if warn_checks else []

    if any(v["verdict"] == "FAIL" for v in verdicts):
        status = "FAIL"
    elif warnings:
        status = "WARN"
    else:
        status = "PASS"

    return {
        "status": status,
        "reason": None,
        "gate_preset": gate_preset,
        "gates": verdicts,
        "warnings": warnings,
        "evidence": {k: v for k, v in evidence.items()},
        "n_windows_walkforward": len(wf.get("windows", [])),
    }
