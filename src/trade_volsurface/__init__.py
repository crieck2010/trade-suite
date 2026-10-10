"""Volatility surface toolkit for the trade-suite.

Implied-volatility solver, model-free surface construction with
total-variance interpolation, raw SVI smile fits, no-arbitrage
diagnostics, smile analytics (risk reversal, butterfly, risk-neutral
density, Dupire local vol), and plain-data adapters for
trade-data-options, trade-agents, trade-risk, and trade-montecarlo.
Stdlib-only.
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import analytics, arbitrage, black_scholes, surface, svi
from .adapters import (
    from_option_chain,
    local_vol_grid,
    stress_surface,
    to_agent_surface,
)
from .surface import Quote, VolSurface
from .svi import SVIFit, fit_svi_slice, fit_svi_surface

__all__ = [
    "Quote",
    "SVIFit",
    "VolSurface",
    "analytics",
    "arbitrage",
    "black_scholes",
    "fit_svi_slice",
    "fit_svi_surface",
    "from_option_chain",
    "local_vol_grid",
    "stress_surface",
    "surface",
    "svi",
    "to_agent_surface",
    "__version__",
]
