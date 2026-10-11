"""Tab 7: Portfolio Stress Testing & Scenario Analysis.

Integrates:
- Real-time macro shock simulation: Delta SPX (%), Delta VIX (pts), Delta 10Y Yield (bps).
- Multi-asset P&L decomposition: Equities/Metals, Duration (TLT), and 0DTE Short Premium.
- Non-linear Hyper-Gamma surge visualizer for 0DTE option spreads.
- Automated hedge proposal generation via trade_hedge (v0.1.0).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..services import (
    HISTORICAL_PRESETS,
    evaluate_portfolio_shock,
    generate_gamma_curve_points,
    record_audit_event,
)


def render_tab7() -> None:
    """Renders Tab 7: Portfolio Stress Testing & Scenarios."""
    st.subheader("🌪️ Portfolio Stress Testing & Scenario Analysis")

    # 1. Scenario Presets & Interactive Sliders
    col_presets, col_sliders = st.columns([1, 2])

    preset_names = [p.name for p in HISTORICAL_PRESETS] + ["Custom Shock (Manual Sliders)"]
    with col_presets:
        st.markdown("### 🏛️ Historical Presets")
        selected_preset_name = st.selectbox("Select Scenario Preset", preset_names, index=1)

        # Find matching preset
        chosen_preset = next((p for p in HISTORICAL_PRESETS if p.name == selected_preset_name), None)
        if chosen_preset:
            st.caption(f"**Description:** {chosen_preset.description}")
            default_spx = chosen_preset.delta_spx_pct
            default_vix = chosen_preset.delta_vix_pts
            default_yield = chosen_preset.delta_yield_bps
        else:
            default_spx = -3.0
            default_vix = 10.0
            default_yield = 25.0

    with col_sliders:
        st.markdown("### 🎛️ Market Shock Controls")
        s_col1, s_col2, s_col3 = st.columns(3)
        with s_col1:
            shock_spx = st.slider("Δ SPX Equity Shock (%)", min_value=-15.0, max_value=10.0, value=float(default_spx), step=0.5)
        with s_col2:
            shock_vix = st.slider("Δ VIX Vol Spike (pts)", min_value=-5.0, max_value=35.0, value=float(default_vix), step=0.5)
        with s_col3:
            shock_yield = st.slider("Δ 10Y Yield Shock (bps)", min_value=-60.0, max_value=60.0, value=float(default_yield), step=5.0)

    # 2. Evaluate Shock
    result = evaluate_portfolio_shock(
        delta_spx_pct=shock_spx,
        delta_vix_pts=shock_vix,
        delta_yield_bps=shock_yield,
        scenario_name=selected_preset_name,
    )

    st.divider()

    # 3. Projected Outcome Banner & Hero Metrics
    st.markdown("### 📊 Projected Portfolio Outcome")
    if result.breach_kill_threshold:
        st.error(
            f"🚨 **RISK LIMIT BREACH DETECTED!** Hyper-Gamma surges to **${result.post_shock_gamma:.2f}** "
            f"(Threshold: $250.00) or Drawdown reaches **{result.total_pct_pnl:.2f}%**. E-Stop / Auto-Hedge trigger required!"
        )
    else:
        st.success(
            f"🟢 **Within Risk Capacity:** Total drawdown **{result.total_pct_pnl:.2f}%** remains within normal risk tolerance."
        )

    r1, r2, r3, r4, r5 = st.columns(5)
    with r1:
        st.metric("Projected Net Liq", f"${result.projected_nlv:,.2f}", f"${result.total_dollar_pnl:+,.2f}")
    with r2:
        st.metric("Total Projected P&L", f"{result.total_pct_pnl:+.2f}%", f"${result.total_dollar_pnl:+,.2f}")
    with r3:
        st.metric("Post-Shock Delta", f"{result.post_shock_delta:+.1f}", f"{result.post_shock_delta - 150.0:+.1f} shift")
    with r4:
        st.metric("Hyper-Gamma (0DTE)", f"${result.post_shock_gamma:.2f}", f"{result.gamma_surge_factor:.2f}x surge")
    with r5:
        st.metric("Duration Loss (TLT)", f"${result.duration_leg_pnl:+,.2f}", f"{shock_yield:+.0f} bps yield")

    # 4. P&L Decomposition Table
    st.divider()
    col_decomp, col_hedge = st.columns([1, 1])

    with col_decomp:
        st.subheader("P&L Decomposition by Asset Leg")
        decomp_data = {
            "Asset Segment": [
                "Equities & Metals (SPY, CPER, XLE)",
                "Treasuries / Duration Leg (TLT)",
                "0DTE Short Options Spreads",
                "Total Portfolio Impact",
            ],
            "Projected P&L ($)": [
                f"${result.equity_legs_pnl:+,.2f}",
                f"${result.duration_leg_pnl:+,.2f}",
                f"${result.options_legs_pnl:+,.2f}",
                f"${result.total_dollar_pnl:+,.2f}",
            ],
            "Mechanism": [
                f"Beta-weighted equity drop ({shock_spx:+.1f}%)",
                f"-16.5y duration sensitivity to {shock_yield:+.0f} bps yield shift",
                f"Taylor expansion: Vega ({shock_vix:+.1f} VIX) + negative Gamma convexity",
                "Combined simultaneous macro stress",
            ],
        }
        st.dataframe(pd.DataFrame(decomp_data), use_container_width=True, hide_index=True)

    with col_hedge:
        st.subheader("🤖 Automated Hedge Simulation (trade_hedge)")
        with st.container(border=True):
            st.markdown(f"**Proposed Hedge Action:** `{result.proposed_hedge_action}`")
            st.markdown(f"**Instrument:** **{result.proposed_hedge_instrument}** | **Quantity:** **{result.proposed_hedge_qty} shares**")
            st.write(f"**Rationale:** {result.proposed_hedge_reason}")

            if result.proposed_hedge_action != "NONE":
                if st.button("Stage Auto-Hedge Order to Desk (Human Review Gate)", use_container_width=True):
                    record_audit_event(
                        action="AUTO_HEDGE_PROPOSED_FROM_STRESS_TEST",
                        actor="Charlie Rieck (Stress Simulation)",
                        details={
                            "action": result.proposed_hedge_action,
                            "instrument": result.proposed_hedge_instrument,
                            "qty": result.proposed_hedge_qty,
                            "scenario": selected_preset_name,
                            "post_shock_delta": result.post_shock_delta,
                        },
                    )
                    st.toast(f"Staged hedge order for {result.proposed_hedge_qty} {result.proposed_hedge_instrument}!")

    # 5. Gamma Surge & Convexity Curve Across SPX Moves
    st.divider()
    st.subheader("📈 Non-Linear Convexity & 0DTE Gamma Surge Curve")
    st.caption("Visualizes the non-linear acceleration of short option losses as spot moves across strikes into long wings.")

    curve_points = generate_gamma_curve_points(
        delta_vix=shock_vix,
        delta_yield=shock_yield,
        nlv=result.initial_nlv,
    )
    df_curve = pd.DataFrame(curve_points)
    st.dataframe(
        df_curve,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Total P&L ($)": st.column_config.NumberColumn(format="$%.2f"),
            "Equities ($)": st.column_config.NumberColumn(format="$%.2f"),
            "Duration ($)": st.column_config.NumberColumn(format="$%.2f"),
            "0DTE Options ($)": st.column_config.NumberColumn(format="$%.2f"),
            "Hyper-Gamma ($)": st.column_config.NumberColumn(format="$%.2f"),
        },
    )
