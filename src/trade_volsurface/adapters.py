"""Interop adapters: plain-data bridges to sibling suite modules.

Sibling imports are lazy (inside functions) so trade-volsurface stays
importable and testable on its own.
"""

from __future__ import annotations

from .arbitrage import check_surface
from .analytics import skew_quotes
from .surface import VolSurface


# ------------------------------------------------------- trade-data-options

def from_option_chain(rows: list[dict], s0: float, r: float = 0.03) -> VolSurface:
    """Build a surface from duck-typed option-chain rows.

    Each row: {"T": years, "K": strike, "iv": ...} or
    {"T": ..., "K": ..., "price": ..., "kind": "call"|"put"}.
    Matches the dicts trade-data-options chain analytics produce —
    without importing it.
    """
    return VolSurface.from_rows(s0, r, rows)


# ------------------------------------------------------------- trade-agents

def to_agent_surface(surface: VolSurface) -> dict:
    """Agent-ready surface summary: term structure, skew, arb status."""
    return {
        "source": "trade-volsurface",
        "s0": surface.s0,
        "r": surface.r,
        "expiries": surface.expiries,
        "atm_term_structure": [
            {"T": T, "iv": iv} for T, iv in surface.atm_term_structure()],
        "skew": [skew_quotes(surface, T) for T in surface.expiries],
        "arbitrage": check_surface(surface),
    }


# ---------------------------------------------------------------- trade-risk

def stress_surface(surface: VolSurface, iv_bump: float) -> VolSurface:
    """Parallel-bump every IV by ``iv_bump`` vol points for scenario work.

    Reprice the book on the bumped surface; the P&L difference is the
    vol-shock scenario for trade-risk limits.
    """
    stressed = surface.bumped(iv_bump)
    return stressed


# -------------------------------------------------------- trade-montecarlo

def local_vol_grid(fits: dict, s0: float, r: float, strikes: list[float],
                   expiries: list[float]) -> list[dict]:
    """Local-vol grid (Dupire/SVI) as plain rows for MC scenario engines.

    A trade-montecarlo local-vol simulator can consume these rows
    directly: {"K":..., "T":..., "local_vol":...}.
    """
    from .analytics import local_vol
    return [{"K": K, "T": T,
             "local_vol": local_vol(fits, K, T, s0, r)}
            for T in expiries for K in strikes]
