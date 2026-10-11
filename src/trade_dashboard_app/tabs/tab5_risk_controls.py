"""Tab 5: Risk Management, Controls & Kill Switch (The E-Stop).

Provides:
- Physical-style UI Kill Switch to immediately halt trading execution.
- Human-in-the-loop pending trade proposal approvals (Charlie is the final gate).
- Hyper-gamma 0DTE threshold monitor.
- Live master audit trail reader (audit_log.json).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..services import (
    get_hedge_loop_status,
    get_pending_proposals,
    get_risk_status,
    read_audit_log,
    reset_kill_switch,
    resolve_proposal,
    trigger_kill_switch,
)


def render_tab5() -> None:
    """Renders Tab 5: Risk Controls & Manual Overrides."""
    risk = get_risk_status()
    hedge = get_hedge_loop_status()
    proposals = get_pending_proposals()
    audit_events = read_audit_log(limit=15)

    st.subheader("Global Risk Controls & Emergency Override")

    # 1. Big Red Button: Kill Switch
    st.markdown("### 🛑 Emergency Kill Switch (The 'E-Stop')")
    k_col1, k_col2 = st.columns([2, 1])

    with k_col1:
        if risk.kill_switch_active:
            st.error(
                f"🚨 **KILL SWITCH ENGAGED!**\n\nReason: {risk.kill_switch_reason or 'Manual intervention'}\n\n"
                "All new order submission is HALTED. Agents are frozen from proposing new risk."
            )
            if st.button("🟢 Disengage Kill Switch & Restore System Normal", use_container_width=True):
                reset_kill_switch(actor="Charlie Rieck (UI Override)")
                st.rerun()
        else:
            st.success("🟢 System Operational: All risk limit gates healthy. Pre-trade checks ACTIVE.")
            kill_reason = st.text_input("Enter Kill Switch Trigger Rationale (Required for Audit)", "")
            if st.button("🚨 TRIGGER EMERGENCY KILL SWITCH (HALT ALL)", type="primary", use_container_width=True):
                reason = kill_reason.strip() or "Manual emergency halt triggered from Tab 5 UI"
                trigger_kill_switch(reason=reason, actor="Charlie Rieck (UI Override)")
                st.rerun()

    with k_col2:
        st.metric(
            "Hyper-Gamma Exposure (0DTE)",
            f"${risk.hyper_gamma_0dte:.2f}",
            f"Limit: ${risk.hyper_gamma_threshold:.2f}",
        )
        st.metric("Top Sector Concentration", f"{risk.current_highest_sector_pct:.1f}%", risk.current_highest_sector)

    st.divider()

    # 2. Human-In-The-Loop Pending Proposals
    st.subheader("Human-In-The-Loop: Staged Agent Proposals (Charlie Approval Gate)")
    if not proposals:
        st.info("No proposals pending review. Agents are operating within normal parameters.")
    else:
        for p in proposals:
            with st.container(border=True):
                p_c1, p_c2, p_c3 = st.columns([3, 1, 1])
                with p_c1:
                    st.markdown(f"**Proposal:** `{p.proposal_id}` | **Symbol:** **{p.symbol}** ({p.side} {p.quantity} units)")
                    st.write(f"**Strategy:** {p.strategy} | **Target Weight:** {p.target_weight_pct:.1f}%")
                    st.caption(f"**Agent Rationale:** {p.rationale} (Proposer: {p.proposer_agent})")
                with p_c2:
                    if st.button(f"✅ Approve", key=f"app_{p.proposal_id}", use_container_width=True):
                        resolve_proposal(p.proposal_id, approved=True, actor="Charlie Rieck")
                        st.toast(f"Approved {p.proposal_id}")
                        st.rerun()
                with p_c3:
                    if st.button(f"❌ Reject", key=f"rej_{p.proposal_id}", use_container_width=True):
                        resolve_proposal(p.proposal_id, approved=False, actor="Charlie Rieck")
                        st.toast(f"Rejected {p.proposal_id}")
                        st.rerun()

    st.divider()

    # 3. Master Audit Trail Reader
    st.subheader("Master Audit Log (audit_log.json)")
    if audit_events:
        audit_rows = []
        for e in audit_events:
            audit_rows.append({
                "Timestamp": e.get("timestamp"),
                "Action": e.get("action"),
                "Actor": e.get("actor"),
                "Details": str(e.get("details", {})),
            })
        st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No audit events recorded yet.")
