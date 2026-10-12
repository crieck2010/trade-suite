"""Tab 2: Agent Visualizer (The Orchestrator's Brain).

Visualizes:
- The LangGraph cyclic state loops (Node A -> Node B -> Node C -> Node D).
- The State Dictionary Inspector (task backlog, active assignments, messages).
- The Live Debate Transcript Stream (trade_agents v0.2.0).
- The Agent Reputation Leaderboard (realized OOS Sharpe, clawback decay).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..services import (
    dispatch_mobile_mattermost_command,
    get_agent_reputation_leaderboard,
    get_business_state,
    get_debate_transcript,
    get_hardware_metrics,
    get_mattermost_gateway_status,
    get_node_topology,
)


def render_tab2() -> None:
    """Renders Tab 2: Agent Visualizer."""
    nodes = get_node_topology()
    state = get_business_state()
    debate = get_debate_transcript()
    reputation = get_agent_reputation_leaderboard()
    hw = get_hardware_metrics()

    # 1. Cyclic Graph State / Node Topology
    st.subheader("Cyclic Graph State (LangGraph Multi-Agent Cluster)")
    cols = st.columns(len(nodes))
    for col, node in zip(cols, nodes):
        with col:
            if node.status == "Active":
                st.success(f"**{node.name}**\n\n🟢 {node.status}\n\n_{node.detail}_")
            elif node.status == "Listening":
                st.info(f"**{node.name}**\n\n📡 {node.status}\n\n_{node.detail}_")
            elif node.status == "Processing":
                st.warning(f"**{node.name}**\n\n⚙️ {node.status}\n\n_{node.detail}_")
            else:
                st.error(f"**{node.name}**\n\n🔴 {node.status}\n\n_{node.detail}_")

    st.divider()

    # 2. Live Debate Transcript & State Dictionary Inspector
    col_debate, col_state = st.columns([3, 2])

    with col_debate:
        st.subheader("Live Debate Transcript Stream (trade_agents v0.2.0)")
        for turn in debate:
            with st.chat_message(name=turn.speaker, avatar="🤖"):
                st.markdown(f"**[{turn.role}]** (Reputation: {turn.reputation_score:.2f} | Vote: {turn.vote_weight:.2f})")
                st.write(turn.argument)

    with col_state:
        st.subheader("BusinessState Dictionary Inspector")
        with st.expander("Active Assignments & Task Backlog", expanded=True):
            st.json({
                "active_assignments": state.get("active_assignments"),
                "task_backlog": state.get("task_backlog"),
            })
        with st.expander("Message History & Review Feedback", expanded=False):
            st.json({
                "messages": state.get("messages"),
                "review_feedback": state.get("review_feedback"),
            })
        with st.expander("Completed Artifacts", expanded=False):
            st.write(state.get("completed_artifacts", []))

    st.divider()

    # 3. Mattermost & Tailscale Ingress Gateway Console
    st.subheader("📱 Mattermost & Tailscale Ingress Gateway")
    gw_status = get_mattermost_gateway_status()

    with st.container(border=True):
        gw_c1, gw_c2 = st.columns([2, 3])
        with gw_c1:
            st.markdown(f"**Gateway State:** `🟢 {gw_status['status']}`")
            st.caption(f"Endpoint: `{gw_status['endpoint']}`")
            st.markdown(f"**Tailscale Mesh Security:** `{gw_status['mesh_security']}`")
            st.caption(f"Authorized Node IP: `{gw_status['tailscale_ip']}` (Port {gw_status['port']})")

        with gw_c2:
            st.markdown("**Test Mobile Slash Command Simulator:**")
            t_col1, t_col2 = st.columns([3, 1])
            with t_col1:
                test_cmd = st.text_input("Mattermost Command", value="/trade status", key="mm_test_input")
            with t_col2:
                send_clicked = st.button("🚀 Dispatch", key="mm_send_btn", use_container_width=True)

            if send_clicked and test_cmd:
                cmd_parts = test_cmd.strip().split(maxsplit=1)
                cmd_name = cmd_parts[0]
                cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
                result = dispatch_mobile_mattermost_command(
                    command=cmd_name,
                    text=cmd_args,
                    user_name="Charlie Rieck (Field Simulator)",
                    remote_ip="100.82.140.22",
                )
                st.markdown(f"**Gateway Response ({result.get('response_type', 'in_channel')}):**")
                st.info(result.get("text", ""))

    st.divider()

    # 3. Agent Reputation Leaderboard
    st.subheader("Agent Reputation Leaderboard (Realized OOS Sharpe & Clawback Decay)")
    rep_records = [
        {
            "Agent": r.agent_name,
            "Realized OOS Sharpe": f"{r.realized_oos_sharpe:.3f}",
            "Clawback Decay": f"{r.clawback_decay_pct:.1f}%",
            "Effective Voting Weight": f"{r.effective_voting_weight:.2f}",
            "Brier Calibration": f"{r.calibration_brier:.2f}",
            "Gate Status": r.status,
        }
        for r in reputation
    ]
    st.dataframe(pd.DataFrame(rep_records), use_container_width=True, hide_index=True)
    st.caption("Reputation decays via clawback when out-of-sample Sharpe drops; voting power in debates is reputation-weighted.")
