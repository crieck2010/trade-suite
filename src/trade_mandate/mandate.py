"""The Mandate schema: the PM agent's written constitution.

A mandate is a plain-data dict (schema_version 1, JSON-serializable) that
constrains every allocation decision.  All fields are optional with
documented defaults; ``new_mandate()`` validates types and ranges so a
malformed mandate fails at construction, never mid-decision.
"""

from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = 1

KNOWN_ORDER_TYPES = {"market", "limit", "stop", "stop_limit"}
KNOWN_ASSET_CLASSES = {"equity", "etf", "option", "future", "crypto", "cash"}
KNOWN_DERIVATIVE_TYPES = {
    "long_call", "long_put", "covered_call", "cash_secured_put",
    "credit_spread", "debit_spread", "iron_condor", "iron_butterfly",
    "collar", "naked_short_call", "naked_short_put",
}
KNOWN_BEHAVIORS = {
    "naked_short_options",
    "overnight_leverage",
    "stand_down_trading",
    "martingale_averaging",
}

DEFAULTS: dict = {
    "max_drawdown": 0.15,          # fraction of peak equity; new risk refused beyond
    "vol_target": 0.12,            # annualized portfolio volatility target
    "allowed_instruments": {
        "asset_classes": ["equity", "etf"],
        "symbols": None,           # None = any symbol within the asset classes
        "derivatives": {
            "allowed_types": ["long_call", "long_put", "covered_call",
                              "credit_spread", "iron_butterfly"],
            "forbidden": ["naked_short_call", "naked_short_put"],
        },
    },
    "leverage_caps": {
        "portfolio": 1.5,          # gross exposure multiple of equity
        "per_position": 0.25,      # single position weight cap from leverage side
    },
    "concentration": {
        "max_single_name_weight": 0.10,
        "max_sector_weight": 0.35,
    },
    "forbidden_behaviors": [
        "naked_short_options",
        "overnight_leverage",
        "stand_down_trading",
        "martingale_averaging",
    ],
    "order_constraints": {
        "max_order_pct_adv": 0.05,  # single order <= 5% of average daily volume
        "allowed_order_types": ["market", "limit"],
    },
    "regime_rules": {
        "min_conviction_to_trade": 25,  # trade-regime conviction 0-100
        "stand_down_flat": True,        # below min conviction: no NEW risk
    },
}


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_mandate(m: dict) -> list[str]:
    """Return a list of problems; empty means the mandate is well-formed."""
    problems: list[str] = []
    if m.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    dd = m.get("max_drawdown")
    if not _is_num(dd) or not 0 < dd < 1:
        problems.append("max_drawdown must be a fraction in (0, 1)")
    vt = m.get("vol_target")
    if not _is_num(vt) or vt <= 0:
        problems.append("vol_target must be positive (annualized)")
    lev = m.get("leverage_caps", {})
    for k in ("portfolio", "per_position"):
        v = lev.get(k)
        if not _is_num(v) or v <= 0:
            problems.append(f"leverage_caps.{k} must be positive")
    conc = m.get("concentration", {})
    for k in ("max_single_name_weight", "max_sector_weight"):
        v = conc.get(k)
        if not _is_num(v) or not 0 < v <= 1:
            problems.append(f"concentration.{k} must be in (0, 1]")
    for b in m.get("forbidden_behaviors", []):
        if b not in KNOWN_BEHAVIORS:
            problems.append(f"unknown forbidden_behavior: {b!r}")
    oc = m.get("order_constraints", {})
    adv = oc.get("max_order_pct_adv")
    if not _is_num(adv) or not 0 < adv <= 1:
        problems.append("order_constraints.max_order_pct_adv must be in (0, 1]")
    for t in oc.get("allowed_order_types", []):
        if t not in KNOWN_ORDER_TYPES:
            problems.append(f"unknown order type: {t!r}")
    rr = m.get("regime_rules", {})
    mc = rr.get("min_conviction_to_trade")
    if not _is_num(mc) or not 0 <= mc <= 100:
        problems.append("regime_rules.min_conviction_to_trade must be in [0, 100]")
    ai = m.get("allowed_instruments", {})
    for a in ai.get("asset_classes", []):
        if a not in KNOWN_ASSET_CLASSES:
            problems.append(f"unknown asset class: {a!r}")
    deriv = ai.get("derivatives", {})
    for t in deriv.get("allowed_types", []) + deriv.get("forbidden", []):
        if t not in KNOWN_DERIVATIVE_TYPES:
            problems.append(f"unknown derivative type: {t!r}")
    overlap = set(deriv.get("allowed_types", [])) & set(deriv.get("forbidden", []))
    if overlap:
        problems.append(f"derivative types both allowed and forbidden: {sorted(overlap)}")
    return problems


def new_mandate(policy_id: str, **overrides) -> dict:
    """Build a mandate from defaults plus overrides; raises on invalid input.

    Nested dicts merge one level deep (e.g. ``leverage_caps={"portfolio": 2.0}``
    keeps the default ``per_position``).
    """
    if not policy_id or not isinstance(policy_id, str):
        raise ValueError("policy_id must be a non-empty string")
    mandate: dict = {
        "schema_version": SCHEMA_VERSION,
        "policy_id": policy_id,
        "version": 1,
        "effective_date": None,  # set on first ratification
    }
    for key, default in DEFAULTS.items():
        value = overrides.get(key, default)
        if isinstance(default, dict) and isinstance(value, dict):
            merged = dict(default)
            merged.update(value)
            # merge the nested derivatives dict too, one more level
            if key == "allowed_instruments" and "derivatives" in value:
                d = dict(default["derivatives"])
                d.update(value["derivatives"])
                merged["derivatives"] = d
            mandate[key] = merged
        else:
            # deep-ish copy for lists so presets can't alias each other
            mandate[key] = json.loads(json.dumps(value))
    problems = validate_mandate(mandate)
    if problems:
        raise ValueError("invalid mandate: " + "; ".join(problems))
    return mandate


def mandate_checksum(mandate: dict) -> str:
    """SHA-256 over the canonical JSON of the mandate (excluding any
    ``checksum`` field).  Deterministic: key order and float rendering are
    normalized, so the same mandate always hashes the same."""
    payload = {k: v for k, v in mandate.items() if k != "checksum"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_markdown(mandate: dict) -> str:
    """Human-readable rendering of the mandate.

    This is the ``<policy_id>.md`` artifact that trade-lifecycle's
    ``policy.resolve_policy()`` discovers and checksums.  The .md is the
    human constitution; the .json is the machine constitution.  Both are
    written together and both are checksum-verified.
    """
    ai = mandate["allowed_instruments"]
    deriv = ai["derivatives"]
    lines = [
        f"# Investment Mandate: {mandate['policy_id']}",
        "",
        f"Version {mandate['version']} · schema v{mandate['schema_version']} · "
        f"effective {mandate.get('effective_date') or 'UNRATIFIED'}",
        "",
        "This document is the portfolio manager's constitution.  Every "
        "allocation decision is checked against it; violations refuse.  "
        "Amendments require explicit human sign-off (see history).",
        "",
        "## Risk limits",
        "",
        f"- Max drawdown: {mandate['max_drawdown']:.0%} of peak equity "
        "(new risk refused beyond)",
        f"- Volatility target: {mandate['vol_target']:.0%} annualized",
        f"- Portfolio leverage cap: {mandate['leverage_caps']['portfolio']:.2f}x",
        f"- Per-position cap: {mandate['leverage_caps']['per_position']:.0%}",
        f"- Max single-name weight: "
        f"{mandate['concentration']['max_single_name_weight']:.0%}",
        f"- Max sector weight: "
        f"{mandate['concentration']['max_sector_weight']:.0%}",
        "",
        "## Instruments",
        "",
        f"- Asset classes: {', '.join(ai['asset_classes'])}",
        "- Symbols: " + ("any within asset classes"
                         if ai["symbols"] is None
                         else ", ".join(ai["symbols"])),
        f"- Allowed derivatives: {', '.join(deriv['allowed_types']) or 'none'}",
        f"- Forbidden derivatives: {', '.join(deriv['forbidden']) or 'none'}",
        "",
        "## Forbidden behaviors",
        "",
    ]
    for b in mandate["forbidden_behaviors"]:
        lines.append(f"- `{b}`")
    lines += [
        "",
        "## Order constraints",
        "",
        f"- Max single order: "
        f"{mandate['order_constraints']['max_order_pct_adv']:.0%} of ADV",
        "- Allowed order types: "
        f"{', '.join(mandate['order_constraints']['allowed_order_types'])}",
        "",
        "## Regime rules",
        "",
        f"- Minimum conviction to open new risk: "
        f"{mandate['regime_rules']['min_conviction_to_trade']:.0f}/100",
        f"- Stand-down goes flat: "
        f"{mandate['regime_rules']['stand_down_flat']}",
        "",
        f"Checksum (mandate payload): `{mandate.get('checksum', '—')}`",
        "",
    ]
    return "\n".join(lines)
