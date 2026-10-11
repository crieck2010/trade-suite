"""Tab 8: Field Quick-View Mode (Mobile / High-Contrast Tailscale Surveying Card).

Optimized for:
- Field operator mobile access via secure Tailscale VPN tunnel.
- High-contrast direct-sunlight readability with large glanceable telemetry.
- Dedicated thumb-friendly 1-tap E-Stop and granular emergency liquidation actions.
- Audio/Visual breach banners for hyper-gamma or risk limit violations.
- Rapid human-in-the-loop trade proposal approvals directly from the field.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from ..services import (
    execute_field_emergency_action,
    get_field_telemetry,
    get_pending_proposals,
    resolve_proposal,
)


def _render_high_contrast_css() -> None:
    """Injects high-contrast CSS overrides for direct sunlight readability."""
    st.markdown(
        """
        <style>
        .field-card-container {
            background-color: #0b0e14;
            border: 2px solid #232b3b;
            border-radius: 12px;
            padding: 18px;
            margin-bottom: 16px;
        }
        .field-metric-large {
            font-size: 2.4rem;
            font-weight: 800;
            line-height: 1.1;
            letter-spacing: -0.5px;
        }
        .field-metric-sub {
            font-size: 1.1rem;
            font-weight: 600;
        }
        .field-status-nominal {
            color: #00FF66;
            font-weight: 800;
        }
        .field-status-warning {
            color: #FFCC00;
            font-weight: 800;
        }
        .field-status-critical {
            color: #FF3333;
            font-weight: 800;
            animation: pulse-breach 1.5s infinite;
        }
        @keyframes pulse-breach {
            0% { opacity: 1; }
            50% { opacity: 0.55; }
            100% { opacity: 1; }
        }
        .touch-button-danger button {
            background-color: #D32F2F !important;
            color: white !important;
            font-weight: 800 !important;
            height: 3.2rem !important;
            font-size: 1.1rem !important;
            border-radius: 8px !important;
        }
        .touch-button-warning button {
            background-color: #F57C00 !important;
            color: white !important;
            font-weight: 700 !important;
            height: 2.8rem !important;
            font-size: 1.0rem !important;
            border-radius: 8px !important;
        }
        .touch-button-success button {
            background-color: #2E7D32 !important;
            color: white !important;
            font-weight: 700 !important;
            height: 2.8rem !important;
            font-size: 1.0rem !important;
            border-radius: 8px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _trigger_audio_chime(frequency_hz: int = 880, duration_sec: float = 0.5) -> None:
    """Plays an alert beep via Web Audio API for mobile browser environments."""
    audio_js = f"""
    <script>
    try {{
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime({frequency_hz}, audioCtx.currentTime);
        gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + {duration_sec});
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + {duration_sec});
    }} catch (e) {{
        console.warn("Audio autoplay blocked or unsupported:", e);
    }}
    </script>
    """
    components.html(audio_js, height=0, width=0)


def render_tab8() -> None:
    """Renders Tab 8: Field Quick-View Mode."""
    _render_high_contrast_css()
    telemetry = get_field_telemetry()
    proposals = get_pending_proposals()

    # Field Mode Controls Header
    col_hdr1, col_hdr2 = st.columns([3, 1])
    with col_hdr1:
        st.subheader("📱 Field Quick-View (Tailscale Surveying Mode)")
        st.caption("Low-latency mobile-optimized command & monitoring console for field deployment.")
    with col_hdr2:
        audio_alert_enabled = st.checkbox("🔊 Audio Breach Siren", value=True, help="Triggers sound alert on critical breaches")

    # 1. Critical Audio/Visual Breach Banners
    if telemetry.alerts:
        has_critical = any(a.level == "CRITICAL" for a in telemetry.alerts)
        if has_critical and audio_alert_enabled:
            _trigger_audio_chime(frequency_hz=1050, duration_sec=0.6)

        for alert in telemetry.alerts:
            if alert.level == "CRITICAL":
                st.error(f"🚨 **{alert.title}** — {alert.message}")
            elif alert.level == "WARNING":
                st.warning(f"⚠️ **{alert.title}** — {alert.message}")
            else:
                st.info(f"ℹ️ **{alert.title}** — {alert.message}")

    # 2. Main Mobile Glance Card
    st.markdown("### ⚡ Glanceable Portfolio State")
    card_col1, card_col2, card_col3 = st.columns(3)

    pnl_sign = "+" if telemetry.day_pnl >= 0 else ""
    pnl_color_class = "field-status-nominal" if telemetry.day_pnl >= 0 else "field-status-critical"
    health_class = {
        "NOMINAL": "field-status-nominal",
        "ELEVATED_RISK": "field-status-warning",
        "CRITICAL_BREACH": "field-status-critical",
    }.get(telemetry.system_health, "field-status-nominal")

    with card_col1:
        with st.container(border=True):
            st.caption("TOTAL NET LIQUIDITY")
            st.markdown(f"<div class='field-metric-large'>${telemetry.net_liquidity:,.2f}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='field-metric-sub {pnl_color_class}'>Day P&L: {pnl_sign}${telemetry.day_pnl:,.2f} ({pnl_sign}{telemetry.day_pnl_pct:.2f}%)</div>",
                unsafe_allow_html=True,
            )

    with card_col2:
        with st.container(border=True):
            st.caption("SYSTEM HEALTH & RISK LIMITS")
            st.markdown(f"<div class='field-metric-large {health_class}'>{telemetry.system_health}</div>", unsafe_allow_html=True)
            gamma_pct = (telemetry.hyper_gamma / telemetry.hyper_gamma_threshold) * 100
            st.markdown(
                f"<div class='field-metric-sub'>0DTE Gamma: <b>${telemetry.hyper_gamma:.2f}</b> / ${telemetry.hyper_gamma_threshold:.2f} ({gamma_pct:.0f}%)</div>",
                unsafe_allow_html=True,
            )

    with card_col3:
        with st.container(border=True):
            st.caption("MACRO & TAILSCALE TUNNEL")
            st.markdown(f"<div class='field-metric-large'>VIX {telemetry.vix:.1f}</div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='field-metric-sub'>Regime: <b>{telemetry.regime_label}</b> | Tailscale: <b>{telemetry.tailscale_latency_ms}ms</b> (<code>{telemetry.tailscale_ip}</code>)</div>",
                unsafe_allow_html=True,
            )

    st.divider()

    # 3. Dedicated 1-Tap Emergency Field Actions
    st.markdown("### 🛑 1-Tap Field Emergency Actions")
    st.caption("Large touch targets designed for rapid intervention in high-stress field conditions.")

    if telemetry.kill_switch_active:
        st.error(f"🚨 **KILL SWITCH IS CURRENTLY ACTIVE** — Reason: {telemetry.kill_switch_reason}")
        if st.button("🟢 DISENGAGE KILL SWITCH & RESTORE TRADING", use_container_width=True, type="primary"):
            res = execute_field_emergency_action("RESET_E_STOP")
            st.toast(res["message"])
            st.rerun()
    else:
        e_col1, e_col2, e_col3 = st.columns(3)

        with e_col1:
            st.markdown('<div class="touch-button-danger">', unsafe_allow_html=True)
            if st.button("🚨 ONE-TAP E-STOP (HALT ALL)", key="field_btn_estop", use_container_width=True):
                res = execute_field_emergency_action("FULL_E_STOP")
                st.toast(res["message"])
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            st.caption("Freezes all agents & halts new orders instantly.")

        with e_col2:
            st.markdown('<div class="touch-button-warning">', unsafe_allow_html=True)
            if st.button("🦅 FLATTEN 0DTE WINGS", key="field_btn_flatten", use_container_width=True):
                res = execute_field_emergency_action("FLATTEN_0DTE_WINGS")
                st.toast(res["message"])
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            st.caption("Closes short options legs to neutralize gamma surge.")

        with e_col3:
            st.markdown('<div class="touch-button-warning">', unsafe_allow_html=True)
            if st.button("⚖️ HEDGE DELTA TO 0.0 (SPY)", key="field_btn_hedge", use_container_width=True):
                res = execute_field_emergency_action("HEDGE_DELTA_NEUTRAL")
                st.toast(res["message"])
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            st.caption("Submits compensating hedge to zero out directional risk.")

    st.divider()

    # 4. Human-In-The-Loop Field Proposal Gate
    st.markdown(f"### 📋 Staged Trade Proposals ({len(proposals)} Pending Charlie's Approval)")

    if not proposals:
        st.info("✅ All systems clear. No proposals pending authorization.")
    else:
        for p in proposals:
            with st.container(border=True):
                prop_info, prop_actions = st.columns([3, 2])
                with prop_info:
                    st.markdown(f"**Proposal `{p.proposal_id}`:** **{p.symbol}** ({p.side} {p.quantity} shares/contracts)")
                    st.write(f"**Strategy:** {p.strategy} | **Target Weight:** {p.target_weight_pct:.1f}%")
                    st.caption(f"**Proposer:** `{p.proposer_agent}` | **Rationale:** {p.rationale}")

                with prop_actions:
                    act_col1, act_col2 = st.columns(2)
                    with act_col1:
                        st.markdown('<div class="touch-button-success">', unsafe_allow_html=True)
                        if st.button(f"✅ APPROVE", key=f"field_app_{p.proposal_id}", use_container_width=True):
                            resolve_proposal(p.proposal_id, approved=True, actor="Charlie Rieck (Field Mobile)")
                            st.toast(f"Approved {p.proposal_id}")
                            st.rerun()
                        st.markdown("</div>", unsafe_allow_html=True)

                    with act_col2:
                        st.markdown('<div class="touch-button-danger">', unsafe_allow_html=True)
                        if st.button(f"❌ REJECT", key=f"field_rej_{p.proposal_id}", use_container_width=True):
                            resolve_proposal(p.proposal_id, approved=False, actor="Charlie Rieck (Field Mobile)")
                            st.toast(f"Rejected {p.proposal_id}")
                            st.rerun()
                        st.markdown("</div>", unsafe_allow_html=True)
