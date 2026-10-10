"""Cost-speed-limit gate (Robert Carver, *Systematic Trading*).

Tier-1 gate 6 (adopted 2026-09-27): a strategy may not spend more than
about one third of its gross edge on trading costs, measured in Sharpe
units.

The maths
----------
Every round trip costs ``round_trip_cost`` as a fraction of notional
(commission + spread + slippage, from the configured cost model).
Trading ``turnover_ann`` round trips a year on one unit of notional
therefore bleeds ``turnover_ann * round_trip_cost`` per year in return
terms. A pure return drag ``d`` on a return stream with annualised
volatility ``sigma`` reduces the Sharpe ratio by ``d / sigma`` (to first
order — the drag is treated as deterministic and vol is assumed
unchanged), so the cost drag in Sharpe units is::

    cost_sharpe_drag = turnover_ann * round_trip_cost / instrument_vol_ann

The budget is one third of the strategy's own gross (pre-cost) Sharpe::

    budget = gross_sharpe / 3

PASS iff ``gross_sharpe > 0`` and ``cost_sharpe_drag <= budget``.

Carver's rule of thumb: a typical single rule earns ~0.4 gross Sharpe,
so the familiar default budget is ~0.13 Sharpe/yr. This gate uses the
strategy's *own* gross Sharpe adaptively — a stronger edge earns a
larger turnover budget — rather than hard-coding 0.4.

Why this gate exists alongside "beat benchmark net of costs": the
benchmark gate depends on the cost model being exactly right. This gate
bounds the *sensitivity* to cost-model error — a strategy spending 0.05
of its 0.4 edge on costs survives a 2x slippage mis-estimate; one
spending 0.13 does not — and it structurally favours higher timeframes.

Plain-data contract: inputs are floats, output is a plain dict with
every intermediate. Missing/NaN/invalid inputs fail closed
(``pass=False``) with a reason in ``rationale`` — they never raise.
Zero UI imports, zero network, zero broker code.
"""

from __future__ import annotations

import math

#: Fraction of the gross edge a strategy may spend on trading costs.
BUDGET_FRACTION = 1.0 / 3.0

#: Framework adoption date; the gate applies to trials pre-registered after it.
ADOPTION_DATE = "2026-09-27"


class _InvalidInput(Exception):
    """Internal: a gate input is missing or out of domain (fail closed)."""


def _finite_number(value, name):
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _InvalidInput(f"{name} must be a finite number, got {value!r}")
    if not math.isfinite(value):
        raise _InvalidInput(f"{name} must be a finite number, got {value!r}")
    return float(value)


def _check_budget_fraction(budget_fraction):
    bf = _finite_number(budget_fraction, "budget_fraction")
    if not 0.0 < bf <= 1.0:
        raise _InvalidInput(f"budget_fraction must be in (0, 1], got {bf!r}")
    return bf


def evaluate_cost_speed_limit(
    turnover_ann,
    round_trip_cost,
    instrument_vol_ann,
    gross_sharpe,
    *,
    budget_fraction=BUDGET_FRACTION,
):
    """Evaluate the cost-speed-limit gate for one instrument.

    Parameters
    ----------
    turnover_ann : float
        Annualised round-trip trades per year (>= 0).
    round_trip_cost : float
        Cost of one round trip as a fraction of notional
        (commission + spread + slippage, >= 0).
    instrument_vol_ann : float
        Annualised volatility of the traded instrument as a fraction
        (e.g. daily log-return stdev * sqrt(252); must be > 0).
    gross_sharpe : float
        Pre-cost Sharpe of the strategy from the backtest (must be > 0:
        with no gross edge there is nothing to spend).
    budget_fraction : float, optional
        Fraction of the gross Sharpe spendable on costs (default 1/3,
        Carver's rule).

    Returns
    -------
    dict with every intermediate: ``turnover_ann``,
    ``round_trip_cost``, ``instrument_vol_ann``, ``gross_sharpe``,
    ``budget_fraction``, ``cost_sharpe_drag``, ``budget``, ``pass``,
    ``rationale``. Invalid inputs fail closed (``pass`` is False).
    """
    result = {
        "gate": "cost_speed_limit",
        "turnover_ann": turnover_ann,
        "round_trip_cost": round_trip_cost,
        "instrument_vol_ann": instrument_vol_ann,
        "gross_sharpe": gross_sharpe,
        "budget_fraction": budget_fraction,
        "cost_sharpe_drag": None,
        "budget": None,
        "pass": False,
        "rationale": "",
    }
    try:
        t = _finite_number(turnover_ann, "turnover_ann")
        c = _finite_number(round_trip_cost, "round_trip_cost")
        v = _finite_number(instrument_vol_ann, "instrument_vol_ann")
        s = _finite_number(gross_sharpe, "gross_sharpe")
        bf = _check_budget_fraction(budget_fraction)
        if t < 0:
            raise _InvalidInput(f"turnover_ann must be >= 0, got {t!r}")
        if c < 0:
            raise _InvalidInput(f"round_trip_cost must be >= 0, got {c!r}")
        if v <= 0:
            raise _InvalidInput(f"instrument_vol_ann must be > 0, got {v!r}")
        if s <= 0:
            raise _InvalidInput(
                f"gross_sharpe must be > 0 (no gross edge to spend), got {s!r}"
            )
    except _InvalidInput as exc:
        result["rationale"] = f"FAIL (invalid input): {exc}"
        return result

    drag = t * c / v
    budget = s * bf
    passed = drag <= budget
    result.update(
        {
            "turnover_ann": t,
            "round_trip_cost": c,
            "instrument_vol_ann": v,
            "gross_sharpe": s,
            "budget_fraction": bf,
            "cost_sharpe_drag": drag,
            "budget": budget,
            "pass": bool(passed),
            "rationale": (
                f"cost drag {drag:.4f} SR/yr vs budget {budget:.4f} SR/yr "
                f"(gross Sharpe {s:.3f} x {bf:.3f}): "
                + ("PASS" if passed else "FAIL — turnover too high for the edge")
            ),
        }
    )
    return result


def notional_weighted_cost_vol(instruments):
    """Notional-weighted average cost and vol across instruments.

    ``instruments``: list of dicts with ``round_trip_cost``,
    ``instrument_vol_ann``, and optional ``weight`` (notional traded;
    defaults to 1.0 each, i.e. equal weighting) and ``name``.

    Returns a dict with the weighted ``round_trip_cost`` and
    ``instrument_vol_ann`` plus the normalised weights and per-instrument
    detail. Weighting is by notional: ``w_i = notional_i / total``.

    This is an approximation — it ignores correlation between the
    instruments' cost and vol realisations — but it is conservative
    enough for a gate: diversification can only lower the realised
    portfolio vol relative to the weighted sum.
    """
    if not instruments:
        raise _InvalidInput("instruments must be a non-empty list")
    rows = []
    total = 0.0
    for i, inst in enumerate(instruments):
        if not isinstance(inst, dict):
            raise _InvalidInput(f"instruments[{i}] must be a dict, got {inst!r}")
        c = _finite_number(inst.get("round_trip_cost"), f"instruments[{i}].round_trip_cost")
        v = _finite_number(inst.get("instrument_vol_ann"), f"instruments[{i}].instrument_vol_ann")
        w = _finite_number(inst.get("weight", 1.0), f"instruments[{i}].weight")
        if c < 0:
            raise _InvalidInput(f"instruments[{i}].round_trip_cost must be >= 0")
        if v <= 0:
            raise _InvalidInput(f"instruments[{i}].instrument_vol_ann must be > 0")
        if w < 0:
            raise _InvalidInput(f"instruments[{i}].weight must be >= 0")
        total += w
        rows.append({"name": inst.get("name", f"instrument_{i}"), "weight_raw": w,
                     "round_trip_cost": c, "instrument_vol_ann": v})
    if total <= 0:
        raise _InvalidInput("instrument weights sum to zero")
    cost_w = sum(r["round_trip_cost"] * r["weight_raw"] for r in rows) / total
    vol_w = sum(r["instrument_vol_ann"] * r["weight_raw"] for r in rows) / total
    detail = [
        {**r, "weight": r["weight_raw"] / total} for r in rows
    ]
    return {
        "round_trip_cost": cost_w,
        "instrument_vol_ann": vol_w,
        "instruments": detail,
    }


def evaluate_cost_speed_limit_multi(
    turnover_ann,
    instruments,
    gross_sharpe,
    *,
    budget_fraction=BUDGET_FRACTION,
):
    """Evaluate the gate for a multi-instrument strategy.

    ``instruments`` is notional-weighted (see
    :func:`notional_weighted_cost_vol`) into a single ``round_trip_cost``
    / ``instrument_vol_ann`` pair, then the single-instrument gate runs.
    The returned dict additionally carries the ``instruments`` breakdown.
    Invalid inputs fail closed.
    """
    result = {
        "gate": "cost_speed_limit",
        "turnover_ann": turnover_ann,
        "round_trip_cost": None,
        "instrument_vol_ann": None,
        "gross_sharpe": gross_sharpe,
        "budget_fraction": budget_fraction,
        "cost_sharpe_drag": None,
        "budget": None,
        "pass": False,
        "rationale": "",
        "instruments": None,
    }
    try:
        agg = notional_weighted_cost_vol(instruments)
    except _InvalidInput as exc:
        result["rationale"] = f"FAIL (invalid input): {exc}"
        return result
    result["instruments"] = agg["instruments"]
    single = evaluate_cost_speed_limit(
        turnover_ann,
        agg["round_trip_cost"],
        agg["instrument_vol_ann"],
        gross_sharpe,
        budget_fraction=budget_fraction,
    )
    result.update(
        {
            "turnover_ann": single["turnover_ann"],
            "round_trip_cost": agg["round_trip_cost"],
            "instrument_vol_ann": agg["instrument_vol_ann"],
            "gross_sharpe": single["gross_sharpe"],
            "budget_fraction": single["budget_fraction"],
            "cost_sharpe_drag": single["cost_sharpe_drag"],
            "budget": single["budget"],
            "pass": single["pass"],
            "rationale": "multi-instrument (notional-weighted): " + single["rationale"],
        }
    )
    return result


def cost_speed_limit_gate(gross_sharpe, *, budget_fraction=BUDGET_FRACTION,
                          gate_name="cost_speed_limit"):
    """Thin adapter onto ``trade_overfit.gates.Gate``.

    Returns a Gate on the ``cost_sharpe_drag`` evidence metric with
    ``op="lte"`` and ``threshold = gross_sharpe * budget_fraction`` — the
    same comparison :func:`evaluate_cost_speed_limit` makes, expressed in
    the overfit desk's gate abstraction instead of duplicating it.

    The lazy import keeps this repo dependency-free; ``trade-overfit``
    is only needed where the adapter is used. ``gross_sharpe`` must be
    positive (the gate's own rule: no gross edge, no pass).
    """
    s = _finite_number(gross_sharpe, "gross_sharpe")
    bf = _check_budget_fraction(budget_fraction)
    if s <= 0:
        raise ValueError(f"gross_sharpe must be > 0, got {s!r}")
    from trade_overfit.gates import Gate  # lazy: keeps this repo dependency-free

    return Gate(
        name=gate_name,
        metric="cost_sharpe_drag",
        op="lte",
        threshold=s * bf,
        description=(
            f"Cost speed limit (Carver): annualised trading costs in Sharpe "
            f"units (turnover x round-trip cost / instrument vol) must not "
            f"exceed {bf:.0%} of the gross Sharpe ({s:.3f}), i.e. "
            f"<= {s * bf:.4f} SR/yr. Bounds sensitivity to cost-model error "
            f"and structurally favours higher timeframes."
        ),
    )
