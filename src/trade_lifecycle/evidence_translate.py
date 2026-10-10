"""Tier-1 evidence -> trade-swing ValidationReport (schema v1) translator.

TRANSLATION, NOT RE-VALIDATION.

This module converts the two-tier framework's machine-readable Tier-1
entry evidence (the ``tier1_evidence.json`` contract owned by
trade-allocate, see trade-strategies ``docs/validation/GATES.md``) into
the trade-swing ``ValidationReport`` (schema v1) shape that
``trade-lifecycle``'s ``gate_research_to_validated`` consumes.

The rule is absolute: same numbers, same verdicts, zero new claims.
Every field in the emitted report traces to a field in the source
evidence. Fields the schema expects but the Tier-1 evidence cannot
supply are set to ``None`` with an explicit note — never invented, never
silently zero-filled. ``numbers_recomputed`` is always ``False``.

Why this exists: REGCOND-1 is Tier-1 validated under the adopted
two-tier framework, but its evidence lives in the Tier-1 shape while the
lifecycle gate requires the schema-v1 report shape. Re-running
validation would produce a *new* evaluation (new timestamp, new data
window); this translation preserves the original evaluation of
2026-09-27 and only changes the envelope it travels in.

Config binding: the report's ``strategy.config`` is hashed with the
lifecycle's own ``config_hash`` (canonical JSON, SHA-256 — see
``trade_lifecycle.gates.config_hash``). The strategy must be registered
with the byte-identical config file (``docs/validation/regcond-1/config.json``);
any parameter change alters the hash and the gate refuses. This module
invents no hashing convention.
"""

from __future__ import annotations

from datetime import datetime, timezone

TIER1_EVIDENCE_SCHEMA_VERSION = 1
VALIDATION_REPORT_SCHEMA_VERSION = 1


def _translator_version() -> str:
    """Package version, resolved lazily to avoid a circular import."""
    try:
        from . import __version__
        return __version__
    except Exception:  # pragma: no cover - defensive only
        return "0.0.0-unknown"


class EvidenceTranslationError(ValueError):
    """Raised when Tier-1 evidence cannot be faithfully translated.

    Fail closed: an unmappable gate, a missing required field, or an
    unexpected evidence schema refuses translation rather than emitting
    a report that misrepresents the source.
    """


# Source gate name -> schema-v1 report gate mapping.
# "op" follows trade-swing's convention ("gt"/"gte"); every Tier-1 gate
# is a strict ">" threshold per docs/validation/GATES.md.
# Descriptions quote the adopted framework's gate table.
TIER1_GATE_MAP = (
    {
        "source": "oos_sharpe_median",
        "metric": "median_oos_sharpe",
        "op": "gt",
        "description": "OOS Sharpe (median across walk-forward folds) > 0.3 "
                       "-- Tier 1 entry gate (two-tier/tier-1)",
    },
    {
        "source": "max_drawdown",
        "metric": "max_drawdown",
        "op": "gt",
        "description": "Max drawdown shallower than -25% "
                       "-- Tier 1 entry gate (two-tier/tier-1)",
    },
    {
        "source": "deflated_sharpe",
        "metric": "dsr",
        "op": "gt",
        "description": "Deflated Sharpe Ratio > 0.8 (n_trials=2) "
                       "-- Tier 1 entry gate (two-tier/tier-1)",
    },
    {
        "source": "excess_return_vs_benchmark_net_per_yr",
        "metric": "excess_return_vs_benchmark_after_costs",
        "op": "gt",
        "description": "Excess return vs 60/40 SPY/TLT benchmark, net of "
                       "costs > 0 -- Tier 1 entry gate (two-tier/tier-1)",
    },
    {
        "source": "sortino",
        "metric": "sortino",
        "op": "gt",
        "description": "Sortino > 0.75 -- Tier 1 entry gate (two-tier/tier-1)",
    },
)

_GATE_INDEX = {g["source"]: g for g in TIER1_GATE_MAP}


def frozen_config_regcond1() -> dict:
    """The canonical machine config for REGCOND-1, transcribed from the
    frozen pre-registration (trade-strategies
    docs/validation/regcond-1/PRE-REGISTRATION.md, frozen 2026-09-26;
    amended 2026-09-27 for the gate set only -- the spec is unchanged).

    This dict -- and the byte-identical ``config.json`` written from it --
    is what must be passed to ``trade-lifecycle register --config``; the
    lifecycle stores ``config_hash`` of it and the translated report must
    reproduce the same hash or promotion is refused.
    """
    return {
        "strategy_id": "REGCOND-1",
        "universe": ["SPY", "CPER", "TLT", "GLD"],
        "signal": {
            "type": "copper_gold_regime",
            "engine": "trade-macro",
            "indicator": "copper_gold",
            "preset": "standard",
            "ratio": "CPER_close / GLD_close",
            "z_window_days": 252,
            "ma_window_days": 200,
            "expansion": {"z_gt": 1.0, "ratio_above_ma": True},
            "contraction": {"z_lt": -1.0, "ratio_below_ma": True},
            "persist_days": 5,
        },
        "rebalance": {
            "cadence": "monthly",
            "signal_as_of": "last trading day of prior month",
            "act_on": "first trading day of month",
        },
        "weights": {
            "EXPANSION": {"SPY": 0.6, "CPER": 0.2, "TLT": 0.2, "GLD": 0.0},
            "CONTRACTION": {"SPY": 0.2, "CPER": 0.0, "TLT": 0.4, "GLD": 0.4},
            "NEUTRAL": {"SPY": 0.25, "CPER": 0.25, "TLT": 0.25, "GLD": 0.25},
        },
        "constraints": {"long_only": True, "leverage": 1.0, "shorting": False},
        "costs": {"bps_per_side": 5, "fill": "next trading day open (t+1)"},
        "walk_forward": {
            "train_weeks": 104,
            "test_weeks": 26,
            "step_weeks": 26,
            "embargo_days": 5,
        },
        "pre_registration": {
            "source": "trade-strategies/docs/validation/regcond-1/"
                      "PRE-REGISTRATION.md",
            "frozen": "2026-09-26",
            "amendment": "2026-09-27 (gate set only; spec unchanged)",
        },
    }


def _margin(op: str, value: float, threshold: float) -> float:
    """Passing headroom, following trade-swing's derivation exactly."""
    if op == "gt":
        return value - threshold
    if op == "gte":
        return value - threshold
    if op == "lt":
        return threshold - value
    if op == "lte":
        return threshold - value
    raise EvidenceTranslationError(f"Unknown op {op!r} in gate map.")


def _require(mapping: dict, key: str, where: str):
    value = mapping.get(key)
    if value is None:
        raise EvidenceTranslationError(
            f"Cannot translate: {where} has no {key!r}. Refusing rather "
            "than inventing it.")
    return value


def translate_tier1_to_validation_report(
    evidence: dict,
    config: dict,
    *,
    strategy_name: str | None = None,
    strategy_family: str = "regime-conditioned cross-asset tilt",
    source_path: str = "tier1_evidence.json",
    generated_utc: str | None = None,
    n_windows_walkforward: int | None = None,
    n_windows_source: str | None = None,
) -> dict:
    """Translate Tier-1 evidence into a schema-v1 ValidationReport.

    ``evidence`` is the parsed ``tier1_evidence.json`` dict.
    ``config`` is the frozen strategy config dict (must be the same dict
    passed to ``trade-lifecycle register --config``).
    """
    if not isinstance(evidence, dict):
        raise EvidenceTranslationError(
            "Evidence must be a dict (parsed tier1_evidence.json).")
    if evidence.get("schema_version") != TIER1_EVIDENCE_SCHEMA_VERSION:
        raise EvidenceTranslationError(
            f"Evidence schema_version is {evidence.get('schema_version')!r}, "
            f"expected {TIER1_EVIDENCE_SCHEMA_VERSION} -- refusing rather "
            "than misreading the format.")
    src_gates = evidence.get("gates")
    if not isinstance(src_gates, list) or not src_gates:
        raise EvidenceTranslationError(
            "Evidence lists no gates; nothing was actually checked.")

    report_gates = []
    for g in src_gates:
        name = _require(g, "name", "gate entry")
        spec = _GATE_INDEX.get(name)
        if spec is None:
            raise EvidenceTranslationError(
                f"Gate {name!r} is not in the Tier-1 gate map -- refusing "
                "rather than misreading it.")
        value = _require(g, "value", f"gate {name!r}")
        threshold = _require(g, "threshold", f"gate {name!r}")
        passed = g.get("passed")
        if not isinstance(passed, bool):
            raise EvidenceTranslationError(
                f"Gate {name!r} has no boolean 'passed' -- refusing rather "
                "than inferring the verdict.")
        report_gates.append({
            "name": name,
            "verdict": "PASS" if passed else "FAIL",
            "metric": spec["metric"],
            "op": spec["op"],
            "value": value,
            "threshold": threshold,
            "margin": _margin(spec["op"], value, threshold),
            "description": spec["description"],
        })

    status = "PASS" if all(g["verdict"] == "PASS"
                           for g in report_gates) else "FAIL"
    evaluated_at = _require(evidence, "evaluated_at", "evidence")
    now_iso = generated_utc or datetime.now(timezone.utc).isoformat()

    metrics = {g["metric"]: g["value"] for g in report_gates}

    return {
        "schema_version": VALIDATION_REPORT_SCHEMA_VERSION,
        "generated_utc": now_iso,
        "strategy": {
            "name": strategy_name or _require(evidence, "strategy_id",
                                              "evidence"),
            "family": strategy_family,
            "config": config,
        },
        "data_provenance": {
            "source": ("trade-strategies/docs/validation/regcond-1/"
                       + source_path),
            "evidence_ref": evidence.get("evidence_ref"),
            "evaluated_at": evaluated_at,
            "evaluator": evidence.get("evaluator"),
            "framework": evidence.get("framework"),
            "framework_ref": evidence.get("framework_ref"),
            "pre_registration": evidence.get("pre_registration"),
            "n_trials": evidence.get("n_trials"),
            "note": "Machine-readable Tier-1 entry evidence. The frozen "
                    "strategy spec is trade-strategies/docs/validation/"
                    "regcond-1/PRE-REGISTRATION.md.",
        },
        "backtest": {
            "engine": None,
            "engine_notes": [
                "Tier-1 evidence carries no engine-level backtest record; "
                "per-trade and equity-curve detail are unavailable in this "
                "translation and are set to null, never zero-filled.",
            ],
            "initial_cash": None,
            "final_equity": None,
            "metrics": metrics,
            "n_trades": None,
            "n_open_positions": None,
        },
        "costs": {
            "model": {"cost_model": "5 bps per side; fills at the next "
                                   "trading day's open (t+1)"},
            "summary": {"cost_bps_per_side": 5, "fill_lag": "t+1"},
            "assumptions": "Documented retail cost assumption for liquid US "
                           "ETFs (frozen pre-registration). All reported "
                           "gate values are net of these costs.",
        },
        "validation": {
            "status": status,
            "reason": (f"All {len(report_gates)} Tier-1 gates "
                       f"{status}. Translated from {source_path} evaluated "
                       f"{evaluated_at} -- a format translation, not a new "
                       "validation run."),
            "gate_preset": evidence.get("framework"),
            "gates": report_gates,
            "warnings": [],
            "evidence": metrics,
            "n_windows_walkforward": n_windows_walkforward,
            "n_windows_source": n_windows_source,
        },
        "limitations": [
            "Secular-trend contamination: the copper:gold label is partly a "
            "secular-copper-weakness tag over this sample (frozen "
            "pre-registration known limitation).",
            "Label lag: 252-day z + 200-day MA + 5-day persistence; fast "
            "regime changes can be missed for a full month (frozen known "
            "limitation).",
            "Thin cycle count (~2-3 full cycles in-sample); the premium must "
            "survive across walk-forward folds, not ride one cycle (frozen "
            "known limitation).",
            "CPER/GLD are ETF proxies with expense drag and tracking error "
            "vs the metals (frozen known limitation).",
            "TRANSLATION: this report is a format translation of Tier-1 "
            "evidence evaluated 2026-09-27, not a new trade-swing validation "
            "run. No numbers were recomputed; backtest-level fields "
            "unavailable in the source are null, never zero-filled.",
        ],
        "translation": {
            "translator": "trade_lifecycle.evidence_translate",
            "translator_version": _translator_version(),
            "kind": "format translation -- NOT a re-validation",
            "source_file": source_path,
            "source_schema_version": evidence.get("schema_version"),
            "source_evaluated_at": evaluated_at,
            "source_evaluator": evidence.get("evaluator"),
            "source_framework": evidence.get("framework"),
            "translated_at": now_iso,
            "numbers_recomputed": False,
            "new_claims": [],
        },
    }


def build_regcond1_report(evidence_path: str, out_dir: str,
                          *, generated_utc: str | None = None) -> dict:
    """Build the REGCOND-1 artifacts: config.json + validation-report-v1.json.

    Reads the real ``tier1_evidence.json``, translates it against the
    frozen config, and writes both files to ``out_dir``. Returns paths,
    the config hash, and the translated report.
    """
    import json
    import os

    from .gates import config_hash

    with open(evidence_path, "r", encoding="utf-8") as fh:
        evidence = json.load(fh)
    config = frozen_config_regcond1()
    report = translate_tier1_to_validation_report(
        evidence,
        config,
        source_path="tier1_evidence.json",
        generated_utc=generated_utc,
        # Supplementary trace: trade-strategies
        # docs/validation/regcond-1/evidence.json walk_forward.n_folds.
        n_windows_walkforward=13,
        n_windows_source=("trade-strategies/docs/validation/regcond-1/"
                          "evidence.json walk_forward.n_folds"),
    )
    os.makedirs(out_dir, exist_ok=True)
    config_path = os.path.join(out_dir, "config.json")
    report_path = os.path.join(out_dir, "validation-report-v1.json")
    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    return {
        "config_path": config_path,
        "report_path": report_path,
        "config_hash": config_hash(config),
        "report": report,
    }
