"""Agent visualization service for Tab 2 (The Orchestrator's Brain).

Bridges to trade_agents (debate protocol, researcher reputation, clawback decay)
and LangGraph cyclic state loops.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .base import (
    AgentNodeStatus,
    AgentReputation,
    DebateTurn,
    HardwareInferenceMetrics,
)


def get_business_state() -> Dict[str, Any]:
    """Returns the LangGraph BusinessState dictionary for inspection."""
    return {
        "execution_loop": "LangGraph Cyclic v1.1",
        "messages": [
            {
                "timestamp": "2026-10-11T14:45:00Z",
                "role": "user",
                "content": "Assess 0DTE Iron Condor entry on SPY. Macro regime EXPANSION, VIX 14.85. Verify with Executive Review Node.",
            },
            {
                "timestamp": "2026-10-11T14:45:02Z",
                "role": "assistant",
                "name": "Executive Orchestrator",
                "content": "Parsed objective. Objective passes mandate check. Routing task T-010 to Options Strategist and Macro Analyst.",
            },
            {
                "timestamp": "2026-10-11T14:45:15Z",
                "role": "assistant",
                "name": "Options Strategist",
                "content": "Computed delta wings: 580/585 Call Spread, 560/555 Put Spread. Net credit $1.25. Max risk $3.75. Sizing: 5 contracts (multiples of 5 rule).",
            },
        ],
        "task_backlog": [
            {"id": "T-010", "task": "ThetaData V3 IV skew check on SPY 0DTE", "priority": "High", "status": "completed"},
            {"id": "T-011", "task": "Verify hyper-gamma buffer < $250.00", "priority": "Critical", "status": "in_progress"},
            {"id": "T-012", "task": "Format Alpaca paper execution payload", "priority": "Normal", "status": "pending"},
        ],
        "active_assignments": [
            {"agent": "Macro Analyst", "task_id": "T-011", "status": "evaluating_tail_risk"},
            {"agent": "Options Strategist", "task_id": "T-012", "status": "payload_staging"},
        ],
        "completed_artifacts": [
            "trade-strategies/docs/validation/regcond-1/evidence.json",
            "scratch/0dte_iron_condor_quote.json",
        ],
        "review_feedback": "Passed Tier-1 Pre-Trade gates. Awaiting final human-in-the-loop click.",
    }


def get_node_topology() -> List[AgentNodeStatus]:
    """Returns the live status of the 5 core LangGraph nodes."""
    return [
        AgentNodeStatus(
            node_id="ingest",
            name="Mattermost Ingest",
            status="Listening",
            detail="Tailscale VPN tunnel active; awaiting incoming webhooks",
            pulse_active=True,
        ),
        AgentNodeStatus(
            node_id="node_a",
            name="Node A: Exec Orchestrator",
            status="Active",
            detail="Parsing and routing task T-011",
            pulse_active=True,
        ),
        AgentNodeStatus(
            node_id="node_b",
            name="Node B: Dispatcher",
            status="Active",
            detail="Allocating threads: 2/30 local agent pool occupied",
            pulse_active=True,
        ),
        AgentNodeStatus(
            node_id="node_c",
            name="Node C: Worker Pool",
            status="Processing",
            detail="Options Strategist & Macro Analyst calculating delta wings",
            pulse_active=True,
        ),
        AgentNodeStatus(
            node_id="node_d",
            name="Node D: Exec Review",
            status="Standby",
            detail="Awaiting complete payload for automated gate check",
            pulse_active=False,
        ),
    ]


def get_debate_transcript() -> List[DebateTurn]:
    """Returns the live debate transcript stream (trade_agents v0.2.0)."""
    return [
        DebateTurn(
            turn_index=1,
            speaker="Macro Bull Agent",
            role="Bull Challenger",
            argument="Copper:Gold ratio z-score sits at +1.24 above 200MA. Economic regime is firm EXPANSION. Risk assets remain supported.",
            reputation_score=1.45,
            vote_weight=0.35,
        ),
        DebateTurn(
            turn_index=2,
            speaker="Defensive Bear Agent",
            role="Bear Challenger",
            argument="VIX is compressed at 14.85, but 0DTE realized volatility spikes in final 90 minutes. Spreads must hold wide wings.",
            reputation_score=1.28,
            vote_weight=0.28,
        ),
        DebateTurn(
            turn_index=3,
            speaker="Risk Desk Arbiter",
            role="Risk Manager",
            argument="Concur with Bull thesis for target direction, but enforce 100-share / 5-spread lot cap. Hyper-gamma limit is $250.00.",
            reputation_score=1.82,
            vote_weight=0.37,
        ),
        DebateTurn(
            turn_index=4,
            speaker="Consensus Engine",
            role="Consensus",
            argument="CONSENSUS REACHED: Approve 5x SPY Iron Condor. Wing width: $5.00. Delta neutrality targeted. Proposal staged for Charlie.",
            reputation_score=1.00,
            vote_weight=1.00,
        ),
    ]


def get_agent_reputation_leaderboard() -> List[AgentReputation]:
    """Returns the agent leaderboard with realized OOS Sharpe, clawback decay, and voting power."""
    return [
        AgentReputation(
            agent_name="REGCOND-1 Macro Specialist",
            realized_oos_sharpe=1.385,
            clawback_decay_pct=0.0,
            effective_voting_weight=0.38,
            calibration_brier=0.12,
            status="Active (Tier-1 Validated)",
        ),
        AgentReputation(
            agent_name="Options Hyper-Gamma Desk",
            realized_oos_sharpe=1.210,
            clawback_decay_pct=2.5,
            effective_voting_weight=0.32,
            calibration_brier=0.16,
            status="Active (Incubation)",
        ),
        AgentReputation(
            agent_name="Mean-Reversion Intraday Agent",
            realized_oos_sharpe=0.650,
            clawback_decay_pct=15.0,
            effective_voting_weight=0.18,
            calibration_brier=0.28,
            status="Probation (Clawback Applied)",
        ),
        AgentReputation(
            agent_name="Overfit Trend-Follower",
            realized_oos_sharpe=-0.150,
            clawback_decay_pct=65.0,
            effective_voting_weight=0.12,
            calibration_brier=0.45,
            status="Sidelined (Failed DSR Gate)",
        ),
    ]


def get_hardware_metrics() -> HardwareInferenceMetrics:
    """Returns local inference and hardware metrics."""
    return HardwareInferenceMetrics(
        vram_used_gb=448.0,
        vram_total_gb=512.0,
        vram_free_gb=64.0,  # Keeping ~64GB free for KV context cache
        token_generation_speed=78.4,
        prompt_cache_hit_rate_pct=94.2,
        gpu_temperature_c=54.0,
        throttling_status="Nominal (0 Throttling Events)",
    )
