"""Tab 1: Global Macro & P&L (The Command Center).

Adheres to:
- Levenson Macro Framework (Real Assets vs. Equities vs. Cash).
- 100-share round lots and 5-spread options sizing.
- Zero-Scroll rule: high-density broker-grade layout.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..services import (
    get_active_positions,
    get_asset_allocation,
    get_macro_regime_status,
    get_portfolio_metrics,
)


def render_tab1() -> None:
    """Renders Tab 1: Global Macro & P&L."""
    metrics = get_portfolio_metrics()
    regime = get_macro_regime_status()
    allocation = get_asset_allocation()
    positions = get_active_positions()

    # Macro Regime & Benner Cycle Banner
    st.markdown("### 🌐 Global Macro & Regime Indicator")
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        st.info(f"**Regime:** {regime['regime_label']}\n\nCu/Au Ratio: {regime['copper_gold_ratio']}")
    with r2:
        st.success(f"**Z-Score:** {regime['ratio_z_score']}\n\nTrend: Above MA200")
    with r3:
        st.warning(f"**Benner Cycle:** {regime['benner_cycle_phase']}")
    with r4:
        st.info(f"**Weather Barometer:**\n\n{regime['weather_barometer']}")

    st.divider()

    # Asset Allocation & Active Positions
    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Asset Allocation (Levenson Framework)")
        alloc_data = {
            "Asset Class": ["Real Assets (Metals/Energy)", "Equities (S&P 500)", "Cash & Short Treasuries"],
            "Target Weight (%)": [
                allocation.real_assets_pct,
                allocation.equities_pct,
                allocation.cash_short_term_pct,
            ],
        }
        df_alloc = pd.DataFrame(alloc_data)
        st.dataframe(df_alloc, use_container_width=True, hide_index=True)

        st.caption(
            "Thesis: Real assets (commodities, hard money, defense) hedge against deglobalization and supply scarcity."
        )

    with col_right:
        st.subheader("Active Positions (100-Share Lots & Spreads)")
        pos_records = [p.to_dict() for p in positions]
        df_pos = pd.DataFrame(pos_records)

        # Reorder and format display columns
        display_cols = [
            "symbol",
            "asset_type",
            "quantity",
            "dte",
            "cost_basis",
            "current_price",
            "unrealized_pnl",
            "delta",
            "gamma",
            "theta",
        ]
        available_cols = [c for c in display_cols if c in df_pos.columns]
        df_display = df_pos[available_cols]

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            column_config={
                "cost_basis": st.column_config.NumberColumn(format="$%.2f"),
                "current_price": st.column_config.NumberColumn(format="$%.2f"),
                "unrealized_pnl": st.column_config.NumberColumn(format="$%.2f"),
                "delta": st.column_config.NumberColumn(format="%.1f"),
            },
        )
