"""The rules engine: exposures + config -> hedge PROPOSALS.

Every rule is a pure function of (exposures, config, market_state). No I/O,
no hidden state, no orders — proposals are plain dicts:

    {"action": str, "instrument": str|None, "qty": float|None,
     "reason": str, "expected_delta_impact": float|None, "rule_id": str,
     "details": dict}

Rules implemented:

- ``delta_trim_rule`` — beta-adjusted net delta outside the hysteresis band
  -> propose an offsetting position in the configured hedge instrument.
- ``vol_regime_rule`` — trailing realized vol above threshold -> propose a
  gross-exposure scale-down factor (vol targeting).
- ``exposure_cap_rule`` — gross/net cap breach -> per-symbol trim proposals
  (highest-beta-first, or pro-rata when configured).
"""

from __future__ import annotations

import math

HEDGE_INSTRUMENT_DEFAULT = "SPY"  # configurable; mapping it to a real
                                   # tradable instrument is user config,
                                   # not this repo's job.


def _stdev(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var) if var > 0 else 0.0


def trailing_realized_vol(returns: list[float], window: int = 63) -> float | None:
    """Annualized realized vol from the trailing `window` returns. None if
    fewer than 2 observations."""
    if len(returns) < 2:
        return None
    tail = [float(r) for r in returns[-window:]]
    sd = _stdev(tail)
    if sd is None:
        return None
    return sd * math.sqrt(252.0)


def delta_trim_rule(exposures: dict, config: dict) -> tuple[list[dict], dict]:
    """Propose a hedge when beta-adjusted net delta is outside the hysteresis
    band [target - band, target + band].

    Hedge ratio: qty = -(delta_dollars - target_dollars) / hedge_price, i.e.
    h = -Δ_portfolio / Δ_hedge, so the post-hedge portfolio delta lands on
    the target. Inside the band: no proposal (no churn). The hedge
    instrument's own beta is assumed to be 1.0; a per-instrument beta can be
    passed via config["hedge_instrument_beta"].
    """
    d = exposures.get("net_delta_frac_beta_adj")
    equity = exposures.get("equity")
    target = float(config.get("delta_target", 0.0))
    band = float(config.get("hysteresis_band", 0.02))
    instrument = config.get("hedge_instrument", HEDGE_INSTRUMENT_DEFAULT)
    hedge_beta = float(config.get("hedge_instrument_beta", 1.0))
    prices = exposures.get("prices", {})

    diag = {"evaluated": True, "rule_id": "delta_trim",
            "delta_frac": d, "target": target, "band": band}
    if d is None or equity in (None, 0):
        return [], {**diag, "reason": "no equity base for delta fractions"}
    hedge_px = prices.get(instrument)
    if hedge_px is None or hedge_beta == 0:
        return [], {**diag, "reason": f"no price for hedge instrument {instrument!r}"}

    deviation = d - target
    if abs(deviation) <= band:
        return [], {**diag, "reason": "inside hysteresis band — no churn"}

    # Dollar delta to remove, converted into hedge-instrument shares.
    excess_dollars = deviation * float(equity)
    qty = -excess_dollars / (float(hedge_px) * hedge_beta)
    qty = round(qty, 4)
    side = "sell" if qty < 0 else "buy"
    proposal = {
        "action": "hedge_delta",
        "instrument": instrument,
        "qty": qty,
        "reason": (
            f"beta-adjusted net delta {d:+.2%} of equity is outside "
            f"hysteresis band [{target - band:+.2%}, {target + band:+.2%}]; "
            f"{side} {abs(qty):,.4f} {instrument} to return delta to target {target:+.2%}"
        ),
        "expected_delta_impact": qty * float(hedge_px) * hedge_beta,
        "rule_id": "delta_trim",
        "details": {"delta_frac": d, "target": target, "band": band,
                    "hedge_price": float(hedge_px), "hedge_beta": hedge_beta},
    }
    return [proposal], {**diag, "reason": "breach — proposal emitted"}


def vol_regime_rule(
    exposures: dict,
    config: dict,
    market_state: dict,
) -> tuple[list[dict], dict]:
    """Vol-targeting: if trailing realized portfolio vol exceeds
    ``vol_target * vol_act_threshold``, propose scaling gross exposure by
    f = min(1, vol_target / realized_vol).

    Vol comes from market_state["portfolio_returns"] (internal estimator),
    or from the trade-volforecast adapter when installed and
    config["use_volforecast"] is true. Never raises on missing data — the
    rule is unevaluated, not failed.
    """
    vol_target = float(config.get("vol_target", 0.15))
    act = float(config.get("vol_act_threshold", 1.25))
    window = int(config.get("vol_realized_window", 63))
    diag = {"evaluated": False, "rule_id": "vol_regime",
            "vol_target": vol_target, "threshold": act}

    realized = None
    source = "internal"
    if config.get("use_volforecast"):
        try:
            from .adapters import vol_from_volforecast
            realized = vol_from_volforecast(
                market_state.get("portfolio_returns") or [])
            source = "trade-volforecast"
        except Exception:
            realized = None
    if realized is None:
        realized = trailing_realized_vol(
            market_state.get("portfolio_returns") or [], window)
    if realized is None:
        return [], {**diag, "reason": "no return history for vol estimate"}

    diag = {**diag, "evaluated": True, "realized_vol": realized, "source": source}
    if realized <= vol_target * act:
        return [], {**diag, "reason": "realized vol within tolerance"}

    scale = min(1.0, vol_target / realized) if realized > 0 else 1.0
    proposal = {
        "action": "scale_exposure",
        "instrument": None,
        "qty": None,
        "reason": (
            f"trailing {window}d realized vol {realized:.1%} exceeds "
            f"{act:.2f}x target {vol_target:.1%}; scale gross exposure by {scale:.2f}"
        ),
        "expected_delta_impact": None,
        "rule_id": "vol_regime",
        "details": {"realized_vol": realized, "vol_target": vol_target,
                    "scale": scale, "source": source},
    }
    return [proposal], {**diag, "reason": "vol regime breach — proposal emitted"}


def exposure_cap_rule(exposures: dict, config: dict) -> tuple[list[dict], dict]:
    """Gross/net cap breaches -> per-symbol trim proposals.

    Ordering (config["cap_trim_mode"]):
    - "highest_beta_first" (default): trim highest-|beta| names first, then
      largest |dollar value|, emitting per-symbol reduce proposals until the
      breach is covered.
    - "pro_rata": distribute the required cut proportionally across all
      positions.
    """
    gross_frac = exposures.get("gross_frac")
    net_frac = exposures.get("net_frac")
    gross_cap = float(config.get("gross_cap", 2.0))
    net_cap = float(config.get("net_cap", 1.0))
    mode = config.get("cap_trim_mode", "highest_beta_first")
    equity = exposures.get("equity")
    diag = {"evaluated": True, "rule_id": "exposure_cap",
            "gross_frac": gross_frac, "net_frac": net_frac,
            "gross_cap": gross_cap, "net_cap": net_cap, "mode": mode}

    breaches: list[tuple[str, float]] = []  # (which, dollars to cut)
    if gross_frac is not None and gross_frac > gross_cap and equity:
        breaches.append(("gross", (gross_frac - gross_cap) * float(equity)))
    if net_frac is not None and abs(net_frac) > net_cap and equity:
        breaches.append(("net", (abs(net_frac) - net_cap) * float(equity)))
    if not breaches:
        return [], {**diag, "reason": "within caps"}

    per_symbol = exposures.get("per_symbol", {})
    proposals: list[dict] = []
    for which, cut_dollars in breaches:
        remaining = cut_dollars
        if mode == "pro_rata":
            total = sum(abs(s["value"]) for s in per_symbol.values())
            ordered = list(per_symbol.items())
            alloc = (lambda v: cut_dollars * abs(v) / total) if total else (lambda v: 0.0)
        else:  # highest_beta_first
            ordered = sorted(
                per_symbol.items(),
                key=lambda kv: (abs(kv[1]["beta"]), abs(kv[1]["value"])),
                reverse=True,
            )
            alloc = None
        for sym, s in ordered:
            if remaining <= 0:
                break
            sym_cut = alloc(s["value"]) if alloc else min(abs(s["value"]), remaining)
            if sym_cut <= 0:
                continue
            qty = sym_cut / s["price"] if s["price"] else 0.0
            qty = -math.copysign(qty, s["qty"])  # trim against the position
            qty = round(qty, 4)
            proposals.append({
                "action": "reduce",
                "instrument": sym,
                "qty": qty,
                "reason": (
                    f"{which} exposure cap breach: trim {sym} by "
                    f"${sym_cut:,.0f} to cover ${cut_dollars:,.0f} excess"
                ),
                "expected_delta_impact": qty * s["price"],
                "rule_id": "exposure_cap",
                "details": {"cap": gross_cap if which == "gross" else net_cap,
                            "which": which, "mode": mode,
                            "trim_dollars": sym_cut},
            })
            remaining -= sym_cut
    return proposals, {**diag, "reason": f"{len(breaches)} cap breach(es) — proposals emitted"}


def propose_hedges(
    exposures: dict,
    config: dict,
    market_state: dict,
) -> tuple[list[dict], dict]:
    """Run every hedge rule. Returns (proposals, diagnostics)."""
    proposals: list[dict] = []
    diagnostics: dict = {}
    for rule in (delta_trim_rule, exposure_cap_rule):
        new, diag = rule(exposures, config)
        proposals.extend(new)
        diagnostics[diag["rule_id"]] = diag
    new, diag = vol_regime_rule(exposures, config, market_state)
    proposals.extend(new)
    diagnostics[diag["rule_id"]] = diag
    return proposals, diagnostics
