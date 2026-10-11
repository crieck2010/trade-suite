"""Portfolio Stress Testing and Scenario Analysis service for Tab 7.

Simulates:
- Macro shocks: Delta SPX (%), Delta VIX (points), Delta 10Y Yield (bps).
- Non-linear Taylor expansion for 0DTE options Greeks (Delta + 0.5*Gamma*dS^2 + Vega*dVIX).
- Duration risk on Treasury/TLT legs (addressing known REGCOND-1 2022 bond crash mode).
- Automated hedge proposal generation via trade_hedge rules.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

try:
    from trade_hedge.hedges import delta_trim_rule
except ImportError:
    delta_trim_rule = None


@dataclass
class ScenarioPreset:
    """Historical or hypothetical market stress scenario."""
    name: str
    description: str
    delta_spx_pct: float
    delta_vix_pts: float
    delta_yield_bps: float


@dataclass
class ShockResult:
    """Projected portfolio outcome under market shock."""
    scenario_name: str
    delta_spx_pct: float
    delta_vix_pts: float
    delta_yield_bps: float
    initial_nlv: float
    projected_nlv: float
    total_dollar_pnl: float
    total_pct_pnl: float
    equity_legs_pnl: float
    duration_leg_pnl: float
    options_legs_pnl: float
    post_shock_delta: float
    gamma_surge_factor: float
    post_shock_gamma: float
    breach_kill_threshold: bool
    proposed_hedge_action: str
    proposed_hedge_qty: int
    proposed_hedge_instrument: str
    proposed_hedge_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


HISTORICAL_PRESETS: List[ScenarioPreset] = [
    ScenarioPreset(
        name="2020 COVID Crash (March 2020)",
        description="Severe equity liquidation, massive VIX explosion, flight to Treasuries.",
        delta_spx_pct=-9.5,
        delta_vix_pts=25.0,
        delta_yield_bps=-35.0,
    ),
    ScenarioPreset(
        name="2022 Correlated Bond-Equity Crash",
        description="Equities drop and rates surge simultaneously (TLT down ~30%). REGCOND-1 pain mode.",
        delta_spx_pct=-3.5,
        delta_vix_pts=8.0,
        delta_yield_bps=35.0,
    ),
    ScenarioPreset(
        name="Intraday 0DTE Gamma Squeeze",
        description="Fast 2% market move in final 90 minutes. 0DTE short premium challenged.",
        delta_spx_pct=-2.0,
        delta_vix_pts=5.5,
        delta_yield_bps=5.0,
    ),
    ScenarioPreset(
        name="Melt-Up Expansion Day",
        description="Aggressive risk-on bid; industrial metals and equities surge, VIX compresses.",
        delta_spx_pct=2.5,
        delta_vix_pts=-2.5,
        delta_yield_bps=10.0,
    ),
]


def evaluate_portfolio_shock(
    delta_spx_pct: float = -3.0,
    delta_vix_pts: float = 10.0,
    delta_yield_bps: float = 25.0,
    scenario_name: str = "Custom Market Shock",
    initial_nlv: float = 142500.0,
) -> ShockResult:
    """Evaluates the impact of simultaneous market, vol, and rate shocks on the active book."""
    spx_spot = 5815.0
    spx_move_dollar = spx_spot * (delta_spx_pct / 100.0)

    # 1. Equity & Metal legs: SPY ($59,750, beta 1.0), CPER ($20,400, beta 0.85), XLE ($8,800, beta 0.95)
    spy_val = 59750.0
    cper_val = 20400.0
    xle_val = 8800.0

    pnl_spy = spy_val * (delta_spx_pct / 100.0) * 1.0
    pnl_cper = cper_val * (delta_spx_pct / 100.0) * 0.85
    pnl_xle = xle_val * (delta_spx_pct / 100.0) * 0.95
    equity_legs_pnl = pnl_spy + pnl_cper + pnl_xle

    # 2. Duration / Treasury leg (TLT: $20,000, modified duration ~16.5 years)
    tlt_val = 20000.0
    tlt_duration = 16.5
    # Price change approx: -Duration * DeltaYield
    duration_leg_pnl = -tlt_val * tlt_duration * (delta_yield_bps / 10000.0)

    # 3. 0DTE Options leg: 5x Iron Condors / Iron Flies on SPY
    # Initial: Delta = 2.0, Gamma = 0.15, Vega = -45.0, Max loss per fly = $375
    opt_delta = 2.0
    opt_gamma = 0.15
    opt_vega = -45.0
    max_opt_loss = -1875.0  # 5 spreads * $375

    # Taylor expansion: Delta*dS + 0.5*Gamma*dS^2 + Vega*dVIX
    # S = SPY spot (~$580), dS = $580 * (delta_spx_pct / 100)
    spy_spot = 580.0
    ds = spy_spot * (delta_spx_pct / 100.0)

    # Short gamma is convexly negative: as spot moves, loss accelerates
    linear_comp = opt_delta * ds
    # Non-linear short gamma loss (negative sign because short premium)
    gamma_comp = -0.5 * opt_gamma * (ds ** 2) * 10.0
    # Vega impact (short vega loses when VIX spikes)
    vega_comp = opt_vega * delta_vix_pts

    raw_opt_pnl = linear_comp + gamma_comp + vega_comp
    # Bound by maximum spread risk
    options_legs_pnl = max(max_opt_loss, raw_opt_pnl)

    # 4. Total Projected P&L and Drawdown
    total_dollar_pnl = equity_legs_pnl + duration_leg_pnl + options_legs_pnl
    projected_nlv = initial_nlv + total_dollar_pnl
    total_pct_pnl = (total_dollar_pnl / initial_nlv) * 100.0

    # 5. Post-shock Greeks & Gamma Surge
    # Delta expands as spot drops through strikes:
    post_shock_delta = 150.0 + (ds * 0.8) + (opt_gamma * ds * 10.0)
    # Gamma surge accelerates when SPX moves >= 1.5%
    abs_move = abs(delta_spx_pct)
    gamma_surge_factor = 1.0 + (abs_move * 0.45)
    post_shock_gamma = 142.50 * gamma_surge_factor

    # E-Stop Threshold: $250.00 hyper-gamma limit
    breach_kill = post_shock_gamma >= 250.00 or total_pct_pnl <= -3.0

    # 6. Auto-Hedge Simulation (trade_hedge integration)
    target_delta = 0.0
    hysteresis = 30.0
    delta_gap = post_shock_delta - target_delta

    if abs(delta_gap) > hysteresis:
        hedge_action = "SELL (TRIM)" if delta_gap > 0 else "BUY (COVER)"
        hedge_qty = int(round(abs(delta_gap)))
        hedge_inst = "SPY"
        hedge_reason = (
            f"trade_hedge: Net delta ({post_shock_delta:+.1f}) exceeds +/-{hysteresis:.0f} hysteresis band. "
            f"Neutralize {abs(delta_gap):.0f} delta to protect capital."
        )
    else:
        hedge_action = "NONE"
        hedge_qty = 0
        hedge_inst = "SPY"
        hedge_reason = f"trade_hedge: Net delta ({post_shock_delta:+.1f}) within safe hysteresis tolerance."

    return ShockResult(
        scenario_name=scenario_name,
        delta_spx_pct=delta_spx_pct,
        delta_vix_pts=delta_vix_pts,
        delta_yield_bps=delta_yield_bps,
        initial_nlv=initial_nlv,
        projected_nlv=round(projected_nlv, 2),
        total_dollar_pnl=round(total_dollar_pnl, 2),
        total_pct_pnl=round(total_pct_pnl, 2),
        equity_legs_pnl=round(equity_legs_pnl, 2),
        duration_leg_pnl=round(duration_leg_pnl, 2),
        options_legs_pnl=round(options_legs_pnl, 2),
        post_shock_delta=round(post_shock_delta, 1),
        gamma_surge_factor=round(gamma_surge_factor, 2),
        post_shock_gamma=round(post_shock_gamma, 2),
        breach_kill_threshold=breach_kill,
        proposed_hedge_action=hedge_action,
        proposed_hedge_qty=hedge_qty,
        proposed_hedge_instrument=hedge_inst,
        proposed_hedge_reason=hedge_reason,
    )


def generate_gamma_curve_points(
    delta_vix: float = 10.0,
    delta_yield: float = 25.0,
    nlv: float = 142500.0,
) -> List[Dict[str, Any]]:
    """Generates a multi-point P&L curve across SPX moves from -5% to +5%."""
    points = []
    for move in [-5.0, -4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0]:
        res = evaluate_portfolio_shock(
            delta_spx_pct=move,
            delta_vix_pts=delta_vix,
            delta_yield_bps=delta_yield,
            initial_nlv=nlv,
        )
        points.append({
            "SPX Move (%)": move,
            "Total P&L ($)": res.total_dollar_pnl,
            "Equities ($)": res.equity_legs_pnl,
            "Duration ($)": res.duration_leg_pnl,
            "0DTE Options ($)": res.options_legs_pnl,
            "Post-Shock Delta": res.post_shock_delta,
            "Hyper-Gamma ($)": res.post_shock_gamma,
        })
    return points
