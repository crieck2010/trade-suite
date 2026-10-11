"""Main Streamlit Entry Point for trade_dashboard_app.

Version: 1.1.0
Target Deployment: Streamlit Frontend, packaging-ready for PyInstaller/pywebview.
Strict adherence to:
- Zero-Scroll Rule: critical portfolio metrics visible above the fold on all tabs.
- Engine/UI Separation: pure UI presentation delegating to services layer.
"""

from __future__ import annotations

import streamlit as st

from . import __version__
from .services import get_hardware_metrics, get_portfolio_metrics, get_risk_status
from .tabs import (
    render_tab1,
    render_tab2,
    render_tab3,
    render_tab4,
    render_tab5,
    render_tab6,
    render_tab7,
    render_tab8,
)


def render_hero_metrics() -> None:
    """Renders the top Zero-Scroll hero metrics bar."""
    metrics = get_portfolio_metrics()
    risk = get_risk_status()

    if risk.kill_switch_active:
        st.error(f"🚨 **SYSTEM HALTED: EMERGENCY KILL SWITCH ACTIVE** ({risk.kill_switch_reason})")

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric(
            label="Net Liquidity",
            value=f"${metrics.net_liquidity:,.2f}",
            delta=f"${metrics.day_pnl:+,.2f}",
        )
    with col2:
        st.metric(
            label="Day P&L",
            value=f"${metrics.day_pnl:+,.2f}",
            delta=f"{metrics.day_pnl_pct:+.2f}%",
        )
    with col3:
        st.metric(
            label="YTD P&L",
            value=f"${metrics.ytd_pnl:+,.2f}",
            delta=f"{metrics.ytd_pnl_pct:+.2f}%",
        )
    with col4:
        st.metric(
            label="Buying Power",
            value=f"${metrics.buying_power:,.2f}",
            delta=f"{metrics.margin_utilization_pct:.1f}% margin",
            delta_color="inverse",
        )
    with col5:
        st.metric(
            label="Beta-Weighted Delta",
            value=f"{metrics.beta_weighted_delta:+.1f}",
            delta=f"{metrics.beta_weighted_delta_change:+.1f} today",
        )
    with col6:
        st.metric(
            label="VIX Level",
            value=f"{metrics.vix:.2f}",
            delta="-0.42 (Low Vol)",
            delta_color="inverse",
        )


def render_sidebar() -> None:
    """Renders the sidebar showing hardware thermals, data feed health, and endpoints."""
    hw = get_hardware_metrics()

    st.sidebar.title("🦅 Agentic Trading Desk")
    st.sidebar.caption(f"Command Center v{__version__} | Master Branch")

    st.sidebar.divider()
    st.sidebar.markdown("### 🔌 API Feeds & Connectivity")
    st.sidebar.markdown("🟢 **Alpaca API:** Paper Endpoint Connected")
    st.sidebar.markdown("🟢 **ThetaData V3:** Local Terminal Live (0DTE Skew)")
    st.sidebar.markdown("🟢 **Tailscale VPN:** Active Field Tunnel")

    st.sidebar.divider()
    st.sidebar.markdown("### 🖥️ Local Inference Hardware")
    st.sidebar.markdown(f"**VRAM Allocation:** {hw.vram_used_gb:.0f} GB / {hw.vram_total_gb:.0f} GB")
    st.sidebar.progress(hw.vram_used_gb / hw.vram_total_gb)
    st.sidebar.caption(f"Free Context Cache: ~{hw.vram_free_gb:.0f} GB for KV cache")

    st.sidebar.markdown(f"**Inference Speed:** {hw.token_generation_speed:.1f} tokens/sec")
    st.sidebar.markdown(f"**Prompt Cache Hit:** {hw.prompt_cache_hit_rate_pct:.1f}%")
    st.sidebar.markdown(f"**Thermals:** {hw.gpu_temperature_c:.0f}°C ({hw.throttling_status})")

    st.sidebar.divider()
    st.sidebar.caption("Scope: Research / Backtesting / Paper Only. Human approval required.")


def run_app() -> None:
    """Main execution function for the Streamlit dashboard."""
    st.set_page_config(
        page_title="Agentic Trading Command Center",
        page_icon="🦅",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Sidebar
    render_sidebar()

    # Zero-Scroll Hero Bar
    render_hero_metrics()
    st.divider()

    # Core Navigation Tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
        "🌐 Tab 1: Global Macro & P&L",
        "🧠 Tab 2: Agent Visualizer",
        "📜 Tab 3: Execution Log & Blotter",
        "📈 Tab 4: Strategy & Backtest",
        "🛑 Tab 5: Risk Controls & E-Stop",
        "⚡ Tab 6: 0DTE Options & Vol Surface",
        "🌪️ Tab 7: Portfolio Stress Test & Scenarios",
        "📱 Tab 8: Field Quick-View",
    ])

    with tab1:
        render_tab1()
    with tab2:
        render_tab2()
    with tab3:
        render_tab3()
    with tab4:
        render_tab4()
    with tab5:
        render_tab5()
    with tab6:
        render_tab6()
    with tab7:
        render_tab7()
    with tab8:
        render_tab8()


if __name__ == "__main__":
    run_app()


