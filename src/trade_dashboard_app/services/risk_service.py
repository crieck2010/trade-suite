"""Risk management and Kill Switch service for Tab 5 and global controls.

Ensures human-in-the-loop control ("The E-Stop") and strict audit logging.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .audit_service import record_audit_event
from .base import PendingProposal, RiskStatus

_GLOBAL_RISK_STATE = RiskStatus(
    kill_switch_active=False,
    kill_switch_reason=None,
    hyper_gamma_0dte=142.50,
    hyper_gamma_threshold=250.00,
    vix_spike_alert=False,
    max_sector_exposure_pct=30.0,
    current_highest_sector="Energy (XLE)",
    current_highest_sector_pct=22.4,
)

# Simulated in-memory proposal queue
_PENDING_PROPOSALS: List[PendingProposal] = [
    PendingProposal(
        proposal_id="PROP-2026-1011-01",
        timestamp="2026-10-11T14:50:00Z",
        symbol="SPY",
        side="SELL (TO OPEN)",
        quantity=5,
        strategy="0DTE Iron Condor (Delta Wings: 580C/585C - 560P/555P)",
        target_weight_pct=4.5,
        rationale="Regime EXPANSION, VIX 14.85, positive theta decay edge; verified by Consensus Engine.",
        urgency="Normal",
        proposer_agent="Options Strategist",
    ),
    PendingProposal(
        proposal_id="PROP-2026-1011-02",
        timestamp="2026-10-11T15:05:00Z",
        symbol="URA",
        side="BUY",
        quantity=100,
        strategy="Real Asset Macro Tilt (100-share round lot)",
        target_weight_pct=2.0,
        rationale="Levenson Scarcity Framework: Nuclear / Uranium supply deficit thesis. Low beta to SPY.",
        urgency="Normal",
        proposer_agent="Macro Analyst",
    ),
]


def get_risk_status() -> RiskStatus:
    """Returns the current global risk status."""
    return _GLOBAL_RISK_STATE


def trigger_kill_switch(reason: str, actor: str = "Charlie Rieck (Manual Override)") -> RiskStatus:
    """Activates the global emergency Kill Switch and logs the event."""
    _GLOBAL_RISK_STATE.kill_switch_active = True
    _GLOBAL_RISK_STATE.kill_switch_reason = reason
    record_audit_event(
        action="KILL_SWITCH_ACTIVATED",
        actor=actor,
        details={
            "reason": reason,
            "hyper_gamma_at_halt": _GLOBAL_RISK_STATE.hyper_gamma_0dte,
            "status": "ALL_NEW_ORDERS_HALTED",
        },
    )
    return _GLOBAL_RISK_STATE


def reset_kill_switch(actor: str = "Charlie Rieck (Manual Override)") -> RiskStatus:
    """Resets the emergency Kill Switch after human authorization."""
    _GLOBAL_RISK_STATE.kill_switch_active = False
    _GLOBAL_RISK_STATE.kill_switch_reason = None
    record_audit_event(
        action="KILL_SWITCH_RESET",
        actor=actor,
        details={"status": "SYSTEM_RESTORED_TO_NORMAL"},
    )
    return _GLOBAL_RISK_STATE


def get_pending_proposals() -> List[PendingProposal]:
    """Returns the queue of trades awaiting human-in-the-loop approval."""
    return [p for p in _PENDING_PROPOSALS]


def resolve_proposal(proposal_id: str, approved: bool, actor: str = "Charlie Rieck") -> bool:
    """Approves or rejects a staged trade proposal with audit logging."""
    global _PENDING_PROPOSALS
    for p in _PENDING_PROPOSALS:
        if p.proposal_id == proposal_id:
            action = "PROPOSAL_APPROVED" if approved else "PROPOSAL_REJECTED"
            record_audit_event(
                action=action,
                actor=actor,
                details={
                    "proposal_id": proposal_id,
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "strategy": p.strategy,
                    "proposer": p.proposer_agent,
                },
            )
            _PENDING_PROPOSALS = [item for item in _PENDING_PROPOSALS if item.proposal_id != proposal_id]
            return True
    return False


def get_hedge_loop_status() -> Dict[str, Any]:
    """Returns the live status of trade_hedge (v0.1.0)."""
    return {
        "status": "Active (Monitoring Delta & Vol Regime)",
        "net_spy_delta": 150.0,
        "delta_target_band": "[120.0, 180.0]",
        "hysteresis_buffer": "+/- 30 delta",
        "proposed_action": "None (Within Safe Band)",
        "vol_regime": "Low Volatility / Normal Drift",
        "last_cycle_timestamp": "2026-10-11T15:15:00Z",
    }
