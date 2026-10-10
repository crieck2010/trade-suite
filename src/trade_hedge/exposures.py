"""Portfolio exposure measurement. Pure functions, plain data in/out.

A "position" is a dict: {"symbol": str, "qty": float} (qty signed; + = long).
Prices are a dict: {symbol: price}. Betas are a dict: {symbol: beta},
defaulting to 1.0 per symbol when absent.

All exposure fractions are expressed as fractions of account equity.
Fractions are None (never invented) when equity is missing or zero.
"""

from __future__ import annotations


def _betas_for(positions: list[dict], config: dict) -> dict[str, float]:
    cfg_betas = config.get("betas") or {}
    out: dict[str, float] = {}
    for p in positions:
        sym = p["symbol"]
        try:
            b = float(cfg_betas.get(sym, 1.0))
        except (TypeError, ValueError):
            b = 1.0
        out[sym] = b
    return out


def compute_exposures(
    positions: list[dict],
    prices: dict[str, float],
    config: dict | None = None,
) -> dict:
    """Measure portfolio exposure from positions + latest prices.

    Returns a plain dict with per-symbol deltas (shares and dollars),
    net delta (raw and beta-adjusted), gross/net exposure as fractions of
    equity, and concentration stats (top-N share, Herfindahl index).

    Raises KeyError naming the symbol when a price is missing — the caller
    (scheduler/safety) is expected to halt before this runs on stale data.
    """
    config = config or {}
    equity = config.get("equity")
    betas = _betas_for(positions, config)
    top_n = int(config.get("concentration_top_n", 5))

    per_symbol: dict[str, dict] = {}
    missing: list[str] = []
    for p in positions:
        sym = p["symbol"]
        qty = float(p["qty"])
        px = prices.get(sym)
        if px is None:
            missing.append(sym)
            continue
        px = float(px)
        value = qty * px
        per_symbol[sym] = {
            "qty": qty,
            "price": px,
            "value": value,                    # signed dollars
            "delta_dollars": value,             # 1 share moves $1 per $1 of price
            "beta": betas[sym],
            "beta_adj_delta": value * betas[sym],
        }
    if missing:
        raise KeyError(f"missing prices for: {', '.join(sorted(missing))}")

    net_delta = sum(s["delta_dollars"] for s in per_symbol.values())
    net_delta_beta_adj = sum(s["beta_adj_delta"] for s in per_symbol.values())
    gross = sum(abs(s["value"]) for s in per_symbol.values())

    # Concentration on gross market-value weights.
    weights = {s: abs(d["value"]) / gross for s, d in per_symbol.items()} if gross > 0 else {}
    herfindahl = sum(w * w for w in weights.values())
    ordered = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    top_n_share = sum(w for _, w in ordered[:top_n])

    def frac(x: float) -> float | None:
        if equity is None or equity == 0:
            return None
        return x / float(equity)

    return {
        "n_positions": len(per_symbol),
        "per_symbol": per_symbol,
        "prices": {s: d["price"] for s, d in per_symbol.items()},
        "net_delta_dollars": net_delta,
        "net_delta_dollars_beta_adj": net_delta_beta_adj,
        "net_delta_frac": frac(net_delta),
        "net_delta_frac_beta_adj": frac(net_delta_beta_adj),
        "gross_dollars": gross,
        "gross_frac": frac(gross),
        "net_frac": frac(net_delta),
        "net_frac_beta_adj": frac(net_delta_beta_adj),
        "herfindahl": herfindahl,
        "top_n_share": top_n_share,
        "top_n": top_n,
        "equity": equity,
    }
