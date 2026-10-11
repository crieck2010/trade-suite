"""Tab 6: 0DTE Options & Volatility Surface (EM-Decay Monitor).

Integrates:
- trade_data_options.em_decay: 83% EM-decay entry trigger for 0DTE Iron Fly
- trade_macro.skip_days: Tail-risk calendar conditioning (FOMC, OpEx, Month-End)
- trade_macro.weather: Composite weather barometer for sizing context
- Realized Vol (RV) vs. Implied Vol (IV) variance risk premium spread
- VIX / VIX3M Term Structure contango/backwardation curve
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..services import (
    get_em_decay_status,
    get_iron_fly_setup,
    get_skip_day_status,
    get_vol_surface_spread,
)


def render_tab6() -> None:
    """Renders Tab 6: 0DTE Options & EM-Decay Monitor."""
    st.subheader("⚡ 0DTE Options & Volatility Surface Monitor")

    # Interactive simulation sliders in expander
    with st.expander("⚙️ Real-Time 0DTE Quote Inputs & Calibration", expanded=False):
        c_in1, c_in2, c_in3, c_in4 = st.columns(4)
        with c_in1:
            sim_opening_em = st.number_input("Opening EM (points)", min_value=1.0, max_value=200.0, value=48.50, step=0.5)
        with c_in2:
            sim_call = st.number_input("Current ATM Call Mid", min_value=0.05, max_value=100.0, value=19.80, step=0.1)
        with c_in3:
            sim_put = st.number_input("Current ATM Put Mid", min_value=0.05, max_value=100.0, value=20.00, step=0.1)
        with c_in4:
            sim_spx = st.number_input("Underlying SPX Spot", min_value=1000.0, max_value=10000.0, value=5815.40, step=1.0)

    # Fetch models
    em = get_em_decay_status(
        opening_em=sim_opening_em,
        call_mid=sim_call,
        put_mid=sim_put,
        underlying_price=sim_spx,
    )
    skip = get_skip_day_status()
    vol = get_vol_surface_spread()
    fly = get_iron_fly_setup(strike=round(sim_spx / 5.0) * 5.0)

    # 1. EM-Decay Entry Trigger Barometer
    st.markdown("### 🎯 Expected Move (EM) Decay Barometer (Hypothesis Threshold: 83.0%)")

    # Banner status
    if em.triggered:
        st.success(f"🟢 **{em.trigger_message}**")
    else:
        st.warning(f"🟡 **{em.trigger_message}**")

    # Metric Row
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Opening EM", f"${em.opening_em_points:.2f}", "Initial Straddle")
    with m2:
        st.metric("Current Straddle", f"${em.current_straddle:.2f}", f"C: ${em.current_call:.2f} | P: ${em.current_put:.2f}")
    with m3:
        st.metric("Decay Remaining", f"{em.decay_pct:.2f}%", f"{em.decay_pct - em.threshold_pct:+.2f}% vs 83% target")
    with m4:
        st.metric("Entry Threshold", f"{em.threshold_pct:.1f}%", "Pre-Registered")
    with m5:
        st.metric("SPX Spot", f"{em.underlying_price:.2f}", "ATM Benchmark")

    # Visual Decay Progress Bar
    progress_val = max(0.0, min(1.0, em.decay_fraction))
    st.progress(progress_val, text=f"Remaining Premium: {em.decay_pct:.1f}% (Entry fires when line drops below 83.0%)")

    st.divider()

    # 2. Left: 0DTE Iron Fly Setup | Right: Skip-Day Conditioning & Vol Spread
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("🦅 Pre-Registered 0DTE Iron-Fly Architecture")
        st.caption("Strategy Reference: `trade_strategies/research/0dte-em-decay-ironfly.md`")

        fly_data = {
            "Parameter": [
                "Underlying Index",
                "ATM Short Straddle",
                "Long Call Wing",
                "Long Put Wing",
                "Initial Wing Width",
                "Estimated Net Credit",
                "Max Risk per Fly",
                "Breakeven Range",
                "Position Sizing Rule",
                "Account Exposure Cap",
                "Risk Cut Rule",
                "Hedge Adds Rule",
            ],
            "Specification": [
                fly.underlying,
                f"Sell {fly.atm_strike:.0f} C & P",
                f"Buy {fly.call_long:.0f} C (+{fly.wing_width:.0f} pts)",
                f"Buy {fly.put_long:.0f} P (-{fly.wing_width:.0f} pts)",
                f"{fly.wing_width:.0f} points (step schedule: 50 -> 20)",
                f"${fly.estimated_credit:.2f}",
                f"${fly.max_risk_per_spread:.2f}",
                f"${fly.breakeven_lower:.2f} — ${fly.breakeven_upper:.2f}",
                f"{fly.recommended_lots} contracts (multiples of 5 rule)",
                f"<= 30% Account Equity (<= {fly.max_account_risk_pct}% per fly)",
                fly.cut_rule,
                fly.adds_rule,
            ],
        }
        st.dataframe(pd.DataFrame(fly_data), use_container_width=True, hide_index=True)

    with col_right:
        st.subheader("🛡️ Tail-Risk Conditioning & Volatility Surface")

        # Skip Days
        st.markdown("**Calendar Tail-Risk Filter (`trade_macro.skip_days`):**")
        s1, s2, s3 = st.columns(3)
        with s1:
            st.metric("FOMC Decision Day", "No (Clean)" if not skip.fomc_active else "YES (SKIP)", delta="Rate Volatility", delta_color="off")
        with s2:
            st.metric("Monthly OpEx Day", "No (Clean)" if not skip.opex_active else "YES (SKIP)", delta="Gamma Pinning", delta_color="off")
        with s3:
            st.metric("Month-End Rebalance", "No (Clean)" if not skip.month_end_active else "YES (SKIP)", delta="Flow Imbalance", delta_color="off")

        if skip.is_skip_day:
            st.error(f"🚨 **{skip.verdict}** (Fired: {', '.join(skip.reasons)})")
        else:
            st.success(f"🟢 **{skip.verdict}**")

        st.divider()

        # Vol Surface Spread & VIX Term Structure
        st.markdown("**Variance Risk Premium (IV vs. RV) & VIX Term Structure:**")
        v1, v2, v3 = st.columns(3)
        with v1:
            st.metric("0DTE Implied Vol (IV)", f"{vol.iv_0dte:.1f}%", f"+{vol.iv_rv_spread:.1f}% vs RV (Rich)", delta_color="normal")
        with v2:
            st.metric("Garman-Klass Realized (RV)", f"{vol.rv_garman_klass:.1f}%", "Intraday OHLC")
        with v3:
            st.metric("VIX / VIX3M Ratio", f"{vol.vix_ratio:.2f}", vol.term_structure, delta_color="inverse")

        st.caption(
            "When IV > RV and VIX term structure is in Contango (Ratio < 1.0), variance risk premium selling holds positive statistical expectancy."
        )
