"""Configurable pass/fail gates with per-gate evidence. The desk's verdict."""

from __future__ import annotations

from dataclasses import dataclass, field

from .dsr import dsr_from_returns
from .metrics import cost_haircut, max_drawdown, performance_summary, sharpe_ratio
from .regimes import regime_report
from .walkforward import walk_forward

_OPS = {
    "gte": lambda v, t: v >= t,
    "gt": lambda v, t: v > t,
    "lte": lambda v, t: v <= t,
    "lt": lambda v, t: v < t,
}


@dataclass
class Gate:
    """One pass/fail rule: ``metric`` looked up in the evidence dict must
    satisfy ``op`` against ``threshold``."""
    name: str
    metric: str
    op: str  # one of gte, gt, lte, lt
    threshold: float
    description: str = ""

    def __post_init__(self) -> None:
        if self.op not in _OPS:
            raise ValueError(f"unknown op {self.op!r}; expected one of {sorted(_OPS)}")


# The default gate set. Every default is documented here because gates are
# conventions, not laws of nature — tune them to your mandate.
DEFAULT_GATES: list[Gate] = [
    Gate(
        name="deflated_sharpe",
        metric="dsr",
        op="gte",
        threshold=0.95,
        description="DSR >= 0.95: under the null of no skill, the chance the "
                    "true Sharpe is positive is at least 95% after correcting "
                    "for the number of trials.",
    ),
    Gate(
        name="oos_sharpe",
        metric="median_oos_sharpe",
        op="gt",
        threshold=1.0,
        description="Median walk-forward out-of-sample Sharpe > 1.0: the edge "
                    "must survive unseen data, not just the fitted window.",
    ),
    Gate(
        name="max_drawdown",
        metric="max_drawdown",
        op="gt",
        threshold=-0.15,
        description="Max drawdown > -15% (i.e. drawdown shallower than 15%): "
                    "the strategy must be survivable, not just profitable.",
    ),
    Gate(
        name="regime_stability",
        metric="worst_regime_sharpe",
        op="gt",
        threshold=0.0,
        description="Worst-regime Sharpe > 0: the edge must not lose money in "
                    "either the calm or the stress regime.",
    ),
    Gate(
        name="beats_benchmark_net",
        metric="excess_return_vs_benchmark_after_costs",
        op="gt",
        threshold=0.0,
        description="Annualized excess return vs benchmark, after the cost "
                    "haircut, > 0: edge must beat buy-and-hold net of costs. "
                    "Skipped (not failed) when no benchmark series is supplied.",
    ),
    Gate(
        name="sortino",
        metric="sortino",
        op="gte",
        threshold=1.5,
        description="Sortino >= 1.5: risk-adjusted return against downside "
                    "volatility only. Sharpe punishes upside jumps; Sortino "
                    "does not, so positively-skewed (trend-style) edges are "
                    "judged on their pain, not their lottery tickets. For "
                    "symmetric returns Sortino ~= sqrt(2) x Sharpe, so 1.5 is "
                    "calibrated to the same elite bar as OOS Sharpe > 1.0. "
                    "A secondary gate — DSR stays the primary statistical gate "
                    "because the multiple-testing deflation math is built for "
                    "Sharpe and has no clean Sortino analogue.",
    ),
    Gate(
        name="calmar",
        metric="calmar",
        op="gte",
        threshold=2.0,
        description="Calmar >= 2.0: annualized return at least twice the "
                    "maximum drawdown (e.g. 20%/yr at a 10% maxDD). Return "
                    "per unit of pain — complements the max-drawdown gate, "
                    "which caps the pain but ignores how much return bought "
                    "it. A secondary gate alongside Sortino.",
    ),
]

# Named presets: same seven gates, different strictness.
PRESETS: dict[str, list[Gate]] = {
    "standard": DEFAULT_GATES,
    "strict": [
        Gate("deflated_sharpe", "dsr", "gte", 0.99,
             "DSR >= 0.99: near-certainty the true Sharpe is positive."),
        Gate("oos_sharpe", "median_oos_sharpe", "gt", 1.5,
             "Median OOS Sharpe > 1.5."),
        Gate("max_drawdown", "max_drawdown", "gt", -0.10,
             "Drawdown shallower than 10%."),
        Gate("regime_stability", "worst_regime_sharpe", "gt", 0.25,
             "Worst-regime Sharpe > 0.25."),
        Gate("beats_benchmark_net", "excess_return_vs_benchmark_after_costs",
             "gt", 0.02, "Beats benchmark by > 2%/yr net of costs."),
        Gate("sortino", "sortino", "gte", 2.0,
             "Sortino >= 2.0: elite downside-adjusted return."),
        Gate("calmar", "calmar", "gte", 3.0,
             "Calmar >= 3.0: return at least 3x the max drawdown."),
    ],
    "lenient": [
        Gate("deflated_sharpe", "dsr", "gte", 0.90, "DSR >= 0.90."),
        Gate("oos_sharpe", "median_oos_sharpe", "gt", 0.5,
             "Median OOS Sharpe > 0.5."),
        Gate("max_drawdown", "max_drawdown", "gt", -0.20,
             "Drawdown shallower than 20%."),
        Gate("regime_stability", "worst_regime_sharpe", "gt", -0.25,
             "Worst-regime Sharpe > -0.25 (tolerates mild regime weakness)."),
        Gate("beats_benchmark_net", "excess_return_vs_benchmark_after_costs",
             "gt", -0.01, "Within 1%/yr of benchmark net of costs."),
        Gate("sortino", "sortino", "gte", 1.0,
             "Sortino >= 1.0: downside-adjusted return at least matches "
             "the Sharpe-scale bar for symmetric returns."),
        Gate("calmar", "calmar", "gte", 1.0,
             "Calmar >= 1.0: annualized return covers the max drawdown."),
    ],
}


def preset_gates(name: str) -> list[Gate]:
    if name not in PRESETS:
        raise ValueError(f"unknown gate preset {name!r}; expected one of {sorted(PRESETS)}")
    return list(PRESETS[name])


def evaluate_gates(evidence: dict, gates: list[Gate] | None = None) -> list[dict]:
    """Evaluate gates against an evidence dict. A gate with missing or None
    evidence FAILS (missing data never passes — suite convention)."""
    gates = DEFAULT_GATES if gates is None else gates
    out = []
    for g in gates:
        value = evidence.get(g.metric)
        passed = value is not None and _OPS[g.op](value, g.threshold)
        out.append({
            "name": g.name,
            "metric": g.metric,
            "op": g.op,
            "threshold": g.threshold,
            "value": value,
            "passed": bool(passed),
            "description": g.description,
        })
    return out


def validate(returns: list[float],
             benchmark: list[float] | None = None,
             rf_annual: float = 0.0,
             cost_bps_per_trade: float = 0.0,
             trades_per_year: float = 252.0,
             trial_sharpes: list[float] | None = None,
             train_len: int = 252,
             test_len: int = 63,
             anchored: bool = False,
             regime_labels: list[str] | None = None,
             gates: list[Gate] | None = None,
             periods: int = 252) -> dict:
    """Run the full overfitting-desk pipeline on a returns series.

    Steps: cost haircut -> performance metrics -> DSR (N trials) ->
    walk-forward -> regime splits -> gates -> PASS/FAIL verdict.

    ``trial_sharpes``: in-sample Sharpes of every strategy tried (defaults to
    ``[sharpe]``, i.e. N=1, no selection-bias correction).
    """
    net = cost_haircut(returns, cost_bps_per_trade, trades_per_year, periods)
    summary = performance_summary(net, rf_annual, periods)
    dsr = dsr_from_returns(net, trial_sharpes, rf_annual, periods)
    wf = walk_forward(net, train_len=train_len, test_len=test_len,
                      anchored=anchored, rf_annual=rf_annual, periods=periods)
    reg = regime_report(net, labels=regime_labels, rf_annual=rf_annual, periods=periods)

    bench_excess = None
    if benchmark is not None and len(benchmark) == len(net):
        bench_ann = performance_summary(benchmark, rf_annual, periods)["annualized_return"]
        strat_ann = summary["annualized_return"]
        if bench_ann is not None and strat_ann is not None:
            bench_excess = strat_ann - bench_ann

    evidence = {
        "dsr": dsr["dsr"],
        "median_oos_sharpe": wf["summary"]["median_oos_sharpe"],
        "max_drawdown": summary["max_drawdown"],
        "worst_regime_sharpe": reg["worst_regime_sharpe"],
        "excess_return_vs_benchmark_after_costs": bench_excess,
        "sortino": summary["sortino"],
        "calmar": summary["calmar"],
    }
    gates = DEFAULT_GATES if gates is None else gates
    if benchmark is None:
        # The benchmark gate is not applicable without a benchmark series:
        # drop it rather than failing on missing evidence.
        gates = [g for g in gates if g.name != "beats_benchmark_net"]
    gate_results = evaluate_gates(evidence, gates)
    verdict = "PASS" if all(g["passed"] for g in gate_results) else "FAIL"
    return {
        "verdict": verdict,
        "n_gates_passed": sum(1 for g in gate_results if g["passed"]),
        "n_gates": len(gate_results),
        "evidence": evidence,
        "gates": gate_results,
        "metrics": summary,
        "dsr": dsr,
        "walk_forward": wf["summary"],
        "regimes": reg,
        "config": {
            "rf_annual": rf_annual,
            "cost_bps_per_trade": cost_bps_per_trade,
            "trades_per_year": trades_per_year,
            "n_trials": dsr["n_trials"],
            "train_len": train_len,
            "test_len": test_len,
            "anchored": anchored,
        },
    }
