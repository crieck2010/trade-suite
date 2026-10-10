"""ValidationReport: the single JSON-serializable verdict document.

schema_version 1. Everything a reader needs to judge the result —
config, data provenance, costs, gate verdicts, which engine ran — in one
place, because a backtest result divorced from its assumptions is
marketing, not evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


LIMITATIONS = [
    "Reference strategy only: a PASS on demo data proves the validation "
    "pipeline works, not that the strategy makes money.",
    "Trend-following systems bleed in choppy markets; the chop demo exists "
    "to show the gates catching exactly that.",
    "Parameters (20/50/ATR14) are conventions, not optimized values. "
    "Optimizing them on the demo data would BE overfitting.",
    "Demo bars are synthetic (seeded random walks); they carry none of the "
    "microstructure, gaps, or corporate actions of real markets.",
    "Costs are a model (commission + slippage + half-spread), not measured "
    "fills. Real slippage varies with size, venue, and volatility.",
    "Fills are assumed at the next bar's open; stop triggers are evaluated "
    "at bar close — a one-bar simplification, identical in both engines.",
    "Past (or demo) performance does not predict future results.",
]


def build_report(backtest_result: dict, validation: dict,
                 provenance: dict | None = None) -> dict:
    """Assemble the ValidationReport from a backtest result + validation."""
    metrics = backtest_result.get("metrics", {})
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": {
            "name": "swing-trend",
            "family": "long/flat MA-cross + ATR trailing stop",
            "config": backtest_result.get("config", {}),
        },
        "data_provenance": provenance or backtest_result.get("provenance", {}),
        "backtest": {
            "engine": backtest_result.get("engine"),
            "engine_notes": backtest_result.get("notes", []),
            "initial_cash": backtest_result.get("initial_cash"),
            "final_equity": backtest_result.get("final_equity"),
            "metrics": metrics,
            "n_trades": len(backtest_result.get("trades", [])),
            "n_open_positions": len(backtest_result.get("open_positions", [])),
        },
        "costs": {
            "model": backtest_result.get("costs", {}).get("cost_model", {}),
            "summary": {k: v for k, v in backtest_result.get("costs", {}).items()
                        if k != "cost_model"},
            "assumptions": ("Commission per share + slippage in bps + half "
                            "the bid/ask spread, applied to every fill. "
                            "Defaults: $0.005/share, 5 bps slippage, 2 bps "
                            "spread. Override via CostModel."),
        },
        "validation": validation,
        "limitations": list(LIMITATIONS),
    }


def report_to_json(report: dict, indent: int = 2) -> str:
    return json.dumps(report, indent=indent, default=str)
