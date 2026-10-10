"""check(mandate, proposal): the constitution applied to a decision.

Pure functions on plain data.  A proposal is::

    {
        "orders": [   # each: {symbol, side: buy|sell, qty, price,
                      #         order_type, instrument_type, asset_class, adv}
            ...],
        "target_weights": {"AAPL": 0.05},   # alternative to orders
        "current_positions": {"AAPL": {"weight": 0.04, "sector": "tech",
                                       "unrealized_pnl": -120.0}},
        "equity": 100000.0,
        "regime_conviction": 62,            # trade-regime 0-100
        "current_drawdown": 0.03,           # fraction of peak
        "holds_overnight": True,
    }

Returns ``{"allowed": bool, "violations": [...], "notes": [...]}``.
Each violation names the rule, the limit, and the observed value —
a refusal you can't act on is just a shrug.

Risk-reducing orders (they shrink |weight|) are allowed even under
drawdown or regime stand-down: the mandate constrains *new risk*, never
the exit door.
"""

from __future__ import annotations

_EPS = 1e-9


def _violation(rule: str, detail: str, **kw) -> dict:
    v = {"rule": rule, "detail": detail}
    v.update(kw)
    return v


def resulting_weights(proposal: dict) -> dict[str, float]:
    """Portfolio weights after the proposal is applied.

    ``target_weights`` wins when present (absolute statement of intent);
    otherwise orders are applied on top of ``current_positions`` weights.
    """
    if proposal.get("target_weights") is not None:
        return {s: float(w) for s, w in proposal["target_weights"].items()}
    weights = {s: float(p.get("weight", 0.0))
               for s, p in proposal.get("current_positions", {}).items()}
    equity = float(proposal.get("equity", 0.0))
    for o in proposal.get("orders", []):
        if equity <= 0:
            continue
        sign = 1.0 if o.get("side") == "buy" else -1.0
        dw = sign * float(o.get("qty", 0.0)) * float(o.get("price", 0.0)) / equity
        weights[o["symbol"]] = weights.get(o["symbol"], 0.0) + dw
    return weights


def _risk_reducing(order: dict, current: dict, equity: float) -> bool:
    """True when the order shrinks the position's |weight| (the exit door)."""
    sym = order["symbol"]
    w0 = float(current.get(sym, {}).get("weight", 0.0))
    if abs(w0) < _EPS:
        return False  # opening a position is never "reducing"
    sign = 1.0 if order.get("side") == "buy" else -1.0
    dw = sign * float(order.get("qty", 0.0)) * float(order.get("price", 0.0))
    dw = dw / equity if equity > 0 else 0.0
    return abs(w0 + dw) < abs(w0) - _EPS


def check_leverage(mandate: dict, weights: dict) -> list[dict]:
    out = []
    caps = mandate["leverage_caps"]
    gross = sum(abs(w) for w in weights.values())
    if gross > caps["portfolio"] + _EPS:
        out.append(_violation(
            "leverage_caps.portfolio",
            f"gross exposure {gross:.3f}x exceeds portfolio cap "
            f"{caps['portfolio']:.2f}x",
            limit=caps["portfolio"], observed=round(gross, 4)))
    for sym, w in weights.items():
        if abs(w) > caps["per_position"] + _EPS:
            out.append(_violation(
                "leverage_caps.per_position",
                f"{sym} weight {w:+.3f} exceeds per-position cap "
                f"{caps['per_position']:.0%}",
                symbol=sym, limit=caps["per_position"],
                observed=round(w, 4)))
    return out


def check_concentration(mandate: dict, weights: dict, proposal: dict) -> list[dict]:
    out = []
    conc = mandate["concentration"]
    sectors: dict[str, float] = {}
    current = proposal.get("current_positions", {})
    for sym, w in weights.items():
        if abs(w) > conc["max_single_name_weight"] + _EPS:
            out.append(_violation(
                "concentration.max_single_name_weight",
                f"{sym} |weight| {abs(w):.1%} exceeds single-name cap "
                f"{conc['max_single_name_weight']:.0%}",
                symbol=sym, limit=conc["max_single_name_weight"],
                observed=round(abs(w), 4)))
        sector = current.get(sym, {}).get("sector")
        if sector:
            sectors[sector] = sectors.get(sector, 0.0) + abs(w)
    for sector, w in sectors.items():
        if w > conc["max_sector_weight"] + _EPS:
            out.append(_violation(
                "concentration.max_sector_weight",
                f"sector {sector} weight {w:.1%} exceeds cap "
                f"{conc['max_sector_weight']:.0%}",
                sector=sector, limit=conc["max_sector_weight"],
                observed=round(w, 4)))
    return out


def check_instruments(mandate: dict, proposal: dict) -> list[dict]:
    out = []
    ai = mandate["allowed_instruments"]
    deriv = ai["derivatives"]
    symbols = ai.get("symbols")
    orders = proposal.get("orders", [])
    tw = proposal.get("target_weights", {}) or {}
    names = [o["symbol"] for o in orders] + list(tw.keys())
    for sym in names:
        if symbols is not None and sym not in symbols:
            out.append(_violation(
                "allowed_instruments.symbols",
                f"{sym} is not on the mandate's symbol allowlist",
                symbol=sym))
    for o in orders:
        ac = o.get("asset_class", "equity")  # documented default
        if ac not in ai["asset_classes"]:
            out.append(_violation(
                "allowed_instruments.asset_classes",
                f"{o['symbol']}: asset class {ac!r} not allowed",
                symbol=o["symbol"], observed=ac))
        it = o.get("instrument_type")
        if it is None:
            continue
        if it in deriv["forbidden"]:
            out.append(_violation(
                "allowed_instruments.derivatives.forbidden",
                f"{o['symbol']}: {it} is explicitly forbidden",
                symbol=o["symbol"], observed=it))
        elif ac == "option" and it not in deriv["allowed_types"]:
            # fail closed: an unlisted derivative type is not allowed
            out.append(_violation(
                "allowed_instruments.derivatives.allowed_types",
                f"{o['symbol']}: {it} is not on the allowed derivative list",
                symbol=o["symbol"], observed=it))
    return out


def check_behaviors(mandate: dict, proposal: dict, weights: dict) -> list[dict]:
    """Syntactic forbidden-behavior patterns.  Documented limitation: these
    match *shapes* of orders, not intent."""
    out = []
    forbidden = set(mandate.get("forbidden_behaviors", []))
    orders = proposal.get("orders", [])
    current = proposal.get("current_positions", {})
    equity = float(proposal.get("equity", 0.0))

    if "naked_short_options" in forbidden:
        for o in orders:
            it = o.get("instrument_type", "")
            if it in ("naked_short_call", "naked_short_put"):
                out.append(_violation(
                    "forbidden_behaviors.naked_short_options",
                    f"{o['symbol']}: naked short option ({it}) forbidden",
                    symbol=o["symbol"], observed=it))

    if "overnight_leverage" in forbidden and proposal.get("holds_overnight"):
        gross = sum(abs(w) for w in weights.values())
        if gross > 1.0 + _EPS:
            out.append(_violation(
                "forbidden_behaviors.overnight_leverage",
                f"holding {gross:.2f}x gross overnight exceeds 1.0x",
                observed=round(gross, 4), limit=1.0))

    if "stand_down_trading" in forbidden:
        conv = proposal.get("regime_conviction", 100)
        min_c = mandate["regime_rules"]["min_conviction_to_trade"]
        if conv < min_c:
            for o in orders:
                if not _risk_reducing(o, current, equity):
                    out.append(_violation(
                        "forbidden_behaviors.stand_down_trading",
                        f"{o['symbol']}: conviction {conv}/100 below minimum "
                        f"{min_c} — new risk refused (risk-reducing exits "
                        "still allowed)",
                        symbol=o["symbol"], observed=conv, limit=min_c))
                    break  # one refusal explains the stand-down

    if "martingale_averaging" in forbidden:
        for o in orders:
            sym = o["symbol"]
            pos = current.get(sym, {})
            pnl = pos.get("unrealized_pnl")
            if pnl is None or pnl >= 0:
                continue
            if not _risk_reducing(o, current, equity):
                out.append(_violation(
                    "forbidden_behaviors.martingale_averaging",
                    f"{sym}: adding to a losing position "
                    f"(unrealized {pnl:+.0f}) is averaging down",
                    symbol=sym, observed=pnl))
    return out


def check_orders(mandate: dict, proposal: dict) -> list[dict]:
    out = []
    oc = mandate["order_constraints"]
    for o in proposal.get("orders", []):
        otype = o.get("order_type", "market")
        if otype not in oc["allowed_order_types"]:
            out.append(_violation(
                "order_constraints.allowed_order_types",
                f"{o['symbol']}: order type {otype!r} not allowed",
                symbol=o["symbol"], observed=otype))
        adv = o.get("adv")
        if adv:
            pct = float(o.get("qty", 0.0)) / float(adv)
            if pct > oc["max_order_pct_adv"] + _EPS:
                out.append(_violation(
                    "order_constraints.max_order_pct_adv",
                    f"{o['symbol']}: order is {pct:.1%} of ADV, cap is "
                    f"{oc['max_order_pct_adv']:.0%}",
                    symbol=o["symbol"], observed=round(pct, 4),
                    limit=oc["max_order_pct_adv"]))
    return out


def check_drawdown(mandate: dict, proposal: dict, weights: dict) -> tuple[list[dict], bool]:
    """Returns (violations, hard_stop).  Beyond max drawdown, new risk is
    refused but the exit door stays open."""
    dd = float(proposal.get("current_drawdown", 0.0))
    cap = mandate["max_drawdown"]
    if dd <= cap + _EPS:
        return [], False
    orders = proposal.get("orders", [])
    current = proposal.get("current_positions", {})
    equity = float(proposal.get("equity", 0.0))
    new_risk = [o for o in orders if not _risk_reducing(o, current, equity)]
    if new_risk:
        return [_violation(
            "max_drawdown",
            f"drawdown {dd:.1%} exceeds max {cap:.0%} — new risk refused; "
            f"{len(orders) - len(new_risk)} risk-reducing order(s) still allowed",
            observed=round(dd, 4), limit=cap)], True
    return [], True


def check(mandate: dict, proposal: dict) -> dict:
    """Apply the mandate to a proposal.  Always returns plain data; never
    raises on a well-formed proposal."""
    weights = resulting_weights(proposal)
    violations: list[dict] = []
    notes: list[str] = []

    dd_violations, in_drawdown_stop = check_drawdown(mandate, proposal, weights)
    violations.extend(dd_violations)
    violations.extend(check_leverage(mandate, weights))
    violations.extend(check_concentration(mandate, weights, proposal))
    violations.extend(check_instruments(mandate, proposal))
    violations.extend(check_behaviors(mandate, proposal, weights))
    violations.extend(check_orders(mandate, proposal))

    if in_drawdown_stop:
        notes.append("drawdown stop active: exits allowed, new risk refused")
    conv = proposal.get("regime_conviction")
    if conv is not None and conv < mandate["regime_rules"]["min_conviction_to_trade"]:
        notes.append(f"regime conviction {conv}/100 below minimum "
                     f"{mandate['regime_rules']['min_conviction_to_trade']}")

    return {
        "allowed": not violations,
        "violations": violations,
        "notes": notes,
        "resulting_gross_leverage": round(sum(abs(w) for w in weights.values()), 4),
        "mandate_version": mandate.get("version"),
        "policy_id": mandate.get("policy_id"),
    }
