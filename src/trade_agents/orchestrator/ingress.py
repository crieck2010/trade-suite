"""Mattermost & Tailscale Ingress Gateway.

Parses and validates incoming mobile slash commands from Mattermost:
- /trade status
- /trade estop [reason]
- /trade reset-estop
- /trade flatten-0dte
- /trade hedge-delta
- /trade approve <proposal_id>
- /trade reject <proposal_id>
- /trade brief <name> | <thesis> | <ticker>

Enforces Tailscale subnet validation (RFC 6598 CGNAT block 100.64.0.0/10).
Routes commands into the LangGraph state machine and desk services.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .models import IngressMessage, IngressResponse, is_tailscale_ip
from .state_dag import LangGraphCyclicStateDAG

logger = logging.getLogger("trade_agents.orchestrator.ingress")


class MattermostIngressGateway:
    """Gateway parsing Mattermost slash commands and dispatching to trading desk services."""

    def __init__(
        self,
        dag: Optional[LangGraphCyclicStateDAG] = None,
        verification_token: Optional[str] = None,
        enforce_tailscale: bool = True,
    ) -> None:
        self.dag = dag or LangGraphCyclicStateDAG()
        self.verification_token = verification_token
        self.enforce_tailscale = enforce_tailscale

    def handle_request(self, msg: IngressMessage) -> IngressResponse:
        """Main ingress router for incoming Mattermost messages."""
        # 1. Tailscale IP Verification
        if self.enforce_tailscale and not msg.is_authenticated_tailscale:
            logger.warning("Rejected non-Tailscale request from IP: %s", msg.remote_ip)
            return IngressResponse(
                text=f"❌ **ACCESS DENIED:** Untrusted origin IP `{msg.remote_ip}`. Requests must originate within the Tailscale mesh (100.64.0.0/10) or localhost.",
                response_type="ephemeral",
                status_code=403,
            )

        # 2. Optional Mattermost Verification Token Check
        if self.verification_token and msg.token != self.verification_token:
            logger.warning("Invalid Mattermost verification token received.")
            return IngressResponse(
                text="❌ **AUTHENTICATION ERROR:** Invalid Mattermost slash command token.",
                response_type="ephemeral",
                status_code=401,
            )

        # 3. Log inbound to DAG conversation
        self.dag.append_message(
            role="user",
            name=f"{msg.user_name} (Mobile Mattermost)",
            content=f"{msg.command} {msg.text}".strip(),
        )

        # 4. Command Dispatcher
        raw_text = msg.text.strip()
        parts = raw_text.split()
        subcmd = parts[0].lower() if parts else "status"
        args = parts[1:] if len(parts) > 1 else []

        if subcmd == "status":
            return self._handle_status()
        elif subcmd in ("estop", "kill", "halt"):
            reason = " ".join(args) if args else "Emergency halt triggered via mobile Mattermost"
            return self._handle_estop(reason=reason, actor=msg.user_name)
        elif subcmd in ("reset-estop", "resume", "clear-estop"):
            return self._handle_reset_estop(actor=msg.user_name)
        elif subcmd in ("flatten-0dte", "flatten"):
            return self._handle_flatten_0dte(actor=msg.user_name)
        elif subcmd in ("hedge-delta", "hedge"):
            return self._handle_hedge_delta(actor=msg.user_name)
        elif subcmd == "approve":
            if not args:
                return IngressResponse(text="⚠️ Usage: `/trade approve <proposal_id>`", response_type="ephemeral")
            return self._handle_approve(args[0], actor=msg.user_name)
        elif subcmd == "reject":
            if not args:
                return IngressResponse(text="⚠️ Usage: `/trade reject <proposal_id>`", response_type="ephemeral")
            return self._handle_reject(args[0], actor=msg.user_name)
        elif subcmd == "brief":
            return self._handle_brief(" ".join(args), actor=msg.user_name)
        elif subcmd == "help":
            return self._handle_help()
        else:
            return IngressResponse(
                text=f"❓ Unknown command: `{subcmd}`. Type `/trade help` for available operations.",
                response_type="ephemeral",
            )

    def _handle_status(self) -> IngressResponse:
        """Fetches live portfolio and risk metrics formatted for mobile chat."""
        try:
            from trade_dashboard_app.services import (
                get_field_telemetry,
                get_pending_proposals,
            )

            telem = get_field_telemetry()
            proposals = get_pending_proposals()
        except ImportError:
            return IngressResponse(text="⚠️ Dashboard telemetry services unavailable.")

        status_emoji = {
            "NOMINAL": "🟢",
            "ELEVATED_RISK": "🟡",
            "CRITICAL_BREACH": "🚨",
        }.get(telem.system_health, "🟢")

        pnl_sign = "+" if telem.day_pnl >= 0 else ""
        text = (
            f"{status_emoji} **Desk Status: {telem.system_health}**\n\n"
            f"• **Net Liquidity:** `${telem.net_liquidity:,.2f}`\n"
            f"• **Day P&L:** `{pnl_sign}${telem.day_pnl:,.2f}` (`{pnl_sign}{telem.day_pnl_pct:.2f}%`)\n"
            f"• **VIX:** `{telem.vix:.2f}` | **Regime:** `{telem.regime_label}`\n"
            f"• **0DTE Hyper-Gamma:** `${telem.hyper_gamma:.2f}` (Limit: `${telem.hyper_gamma_threshold:.2f}`)\n"
            f"• **Kill Switch:** `{'ENGAGED' if telem.kill_switch_active else 'CLEAR'}`\n"
            f"• **Tailscale Mesh:** `{telem.tailscale_ip}` ({telem.tailscale_latency_ms}ms)\n"
            f"• **Pending Proposals:** `{len(proposals)}` waiting for Charlie"
        )

        attachments = []
        if proposals:
            for p in proposals[:3]:
                attachments.append({
                    "color": "#FFCC00",
                    "title": f"Proposal {p.proposal_id}: {p.symbol} {p.side} {p.quantity}",
                    "text": f"Strategy: {p.strategy} | Rationale: {p.rationale}\n*To approve:* `/trade approve {p.proposal_id}`",
                })

        return IngressResponse(text=text, attachments=attachments)

    def _handle_estop(self, reason: str, actor: str) -> IngressResponse:
        """Engages the physical-style emergency Kill Switch immediately."""
        try:
            from trade_dashboard_app.services import execute_field_emergency_action

            res = execute_field_emergency_action("FULL_E_STOP", actor=f"{actor} (Mattermost)")
            self.dag.append_message(
                role="assistant",
                name="Executive Orchestrator",
                content=f"EMERGENCY E-STOP ENGAGED by {actor}. Reason: {reason}",
            )
            return IngressResponse(
                text=f"🚨 **EMERGENCY KILL SWITCH ENGAGED!**\n\nActor: **{actor}**\nReason: *{reason}*\nAll trading execution and agent proposal staging is **HALTED**.",
                attachments=[{"color": "#D32F2F", "text": "To restore system normal, run `/trade reset-estop`"}],
            )
        except Exception as e:
            return IngressResponse(text=f"❌ Error triggering kill switch: {e}", status_code=500)

    def _handle_reset_estop(self, actor: str) -> IngressResponse:
        """Disengages the emergency Kill Switch."""
        try:
            from trade_dashboard_app.services import execute_field_emergency_action

            res = execute_field_emergency_action("RESET_E_STOP", actor=f"{actor} (Mattermost)")
            self.dag.append_message(
                role="assistant",
                name="Executive Orchestrator",
                content=f"Kill Switch reset by {actor}. Trading desk restored to operational normal.",
            )
            return IngressResponse(
                text=f"🟢 **KILL SWITCH DISENGAGED.** System restored to operational normal by **{actor}**.",
                attachments=[{"color": "#2E7D32", "text": "All pre-trade limits and agent risk loops re-activated."}],
            )
        except Exception as e:
            return IngressResponse(text=f"❌ Error resetting kill switch: {e}", status_code=500)

    def _handle_flatten_0dte(self, actor: str) -> IngressResponse:
        """Submits 0DTE wing liquidation orders."""
        try:
            from trade_dashboard_app.services import execute_field_emergency_action

            res = execute_field_emergency_action("FLATTEN_0DTE_WINGS", actor=f"{actor} (Mattermost)")
            return IngressResponse(
                text=f"🦅 **0DTE Premium Flattening Triggered by {actor}:** Liquidating short options wings to defuse gamma surge.",
                attachments=[{"color": "#F57C00", "text": res.get("message", "Orders dispatched.")}],
            )
        except Exception as e:
            return IngressResponse(text=f"❌ Error flattening wings: {e}", status_code=500)

    def _handle_hedge_delta(self, actor: str) -> IngressResponse:
        """Stages compensating SPY hedge."""
        try:
            from trade_dashboard_app.services import execute_field_emergency_action

            res = execute_field_emergency_action("HEDGE_DELTA_NEUTRAL", actor=f"{actor} (Mattermost)")
            return IngressResponse(
                text=f"⚖️ **Delta Neutralization Triggered by {actor}:** Staging compensating SPY hedge to bring portfolio beta-delta to 0.0.",
                attachments=[{"color": "#F57C00", "text": res.get("message", "Hedge staged.")}],
            )
        except Exception as e:
            return IngressResponse(text=f"❌ Error staging hedge: {e}", status_code=500)

    def _handle_approve(self, proposal_id: str, actor: str) -> IngressResponse:
        """Approves a staged proposal via the human-in-the-loop gate."""
        try:
            from trade_dashboard_app.services import resolve_proposal

            resolve_proposal(proposal_id, approved=True, actor=f"{actor} (Mattermost)")
            self.dag.append_message(
                role="assistant",
                name="Executive Review",
                content=f"Proposal {proposal_id} approved by human gate {actor}.",
            )
            return IngressResponse(
                text=f"✅ **Proposal `{proposal_id}` APPROVED by {actor}.** Execution orders released to paper blotter.",
                attachments=[{"color": "#2E7D32", "text": f"Logged to master audit log."}],
            )
        except Exception as e:
            return IngressResponse(text=f"❌ Error approving proposal: {e}", status_code=500)

    def _handle_reject(self, proposal_id: str, actor: str) -> IngressResponse:
        """Rejects a staged proposal."""
        try:
            from trade_dashboard_app.services import resolve_proposal

            resolve_proposal(proposal_id, approved=False, actor=f"{actor} (Mattermost)")
            self.dag.append_message(
                role="assistant",
                name="Executive Review",
                content=f"Proposal {proposal_id} rejected by human gate {actor}.",
            )
            return IngressResponse(
                text=f"❌ **Proposal `{proposal_id}` REJECTED by {actor}.** Order discarded.",
                attachments=[{"color": "#D32F2F", "text": f"Logged to master audit log."}],
            )
        except Exception as e:
            return IngressResponse(text=f"❌ Error rejecting proposal: {e}", status_code=500)

    def _handle_brief(self, brief_text: str, actor: str) -> IngressResponse:
        """Captures an outside strategy idea per Strategy Intake Guide."""
        if not brief_text:
            return IngressResponse(
                text="⚠️ Usage: `/trade brief <Strategy Name> | <Thesis> | <Universe/Ticker>`",
                response_type="ephemeral",
            )
        self.dag.append_message(
            role="user",
            name=f"{actor} (Idea Intake)",
            content=f"New Strategy Brief: {brief_text}",
        )
        self.dag.route_task(
            task_id=f"INTAKE-{hash(brief_text) % 10000:04d}",
            description=f"Evaluate strategy brief: {brief_text[:60]}...",
            priority="Normal",
        )
        return IngressResponse(
            text=f"📝 **Strategy Brief Captured by {actor}:**\n> {brief_text}\n\nTask added to LangGraph backlog. Executive Orchestrator will triage complexity and data requirements.",
            attachments=[{"color": "#1976D2", "text": "Tracked under Strategy Intake Guide (Occam's Desk C <= 3)."}],
        )

    def _handle_help(self) -> IngressResponse:
        """Returns help manual for Mattermost slash commands."""
        help_text = (
            "🦅 **Agentic AI Trading System — Mattermost Command Reference**\n\n"
            "• `/trade status` — Live Net Liquidity, Day P&L, VIX, Hyper-Gamma, and Pending Proposals.\n"
            "• `/trade estop [reason]` — 🚨 Emergency Kill Switch (Immediately halts trading).\n"
            "• `/trade reset-estop` — 🟢 Disengage Kill Switch & restore operational state.\n"
            "• `/trade flatten-0dte` — 🦅 Liquidate 0DTE short premium wings to defuse gamma.\n"
            "• `/trade hedge-delta` — ⚖️ Neutralize net portfolio beta-delta with SPY.\n"
            "• `/trade approve <id>` — ✅ Human-in-the-loop authorization of a staged proposal.\n"
            "• `/trade reject <id>` — ❌ Reject a staged proposal.\n"
            "• `/trade brief <details>` — 📝 Submit a strategy brief to the LangGraph idea intake pool.\n"
            "• `/trade help` — Show this manual."
        )
        return IngressResponse(text=help_text, response_type="ephemeral")
