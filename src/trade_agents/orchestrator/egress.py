"""Mattermost Egress Notifier.

Dispatches real-time outbound alert notifications to Mattermost Incoming Webhooks:
- Emergency E-Stop triggers and resets
- 0DTE Hyper-Gamma limit breaches
- Staged agent trade proposals requiring Charlie's human authorization
- Daily P&L and macro regime shifts

Conforms to Zero-Overhead and Fail-Soft principles:
- Uses stdlib urllib only.
- Never crashes if webhook URL is unset or offline.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("trade_agents.orchestrator.egress")


class MattermostEgressNotifier:
    """Dispatches webhook alerts to a configured Mattermost incoming webhook endpoint."""

    def __init__(self, webhook_url: Optional[str] = None) -> None:
        self.webhook_url = webhook_url or os.getenv("MATTERMOST_WEBHOOK_URL", "")

    def is_configured(self) -> bool:
        return bool(self.webhook_url.strip())

    def send_notification(
        self,
        text: str,
        title: Optional[str] = None,
        color: str = "#1976D2",
        fields: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Sends a formatted notification payload to Mattermost."""
        if not self.is_configured():
            logger.info("Mattermost webhook URL not configured; skipping notification: %s", text)
            return False

        attachment: Dict[str, Any] = {
            "color": color,
            "text": text,
        }
        if title:
            attachment["title"] = title
        if fields:
            attachment["fields"] = fields

        payload = {
            "username": "Agentic Trading Bot",
            "icon_emoji": ":eagle:",
            "attachments": [attachment],
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("Failed to send Mattermost notification: %s", e)
            return False

    def notify_kill_switch_engaged(self, reason: str, actor: str) -> bool:
        """Dispatches high-priority alert when Kill Switch is engaged."""
        return self.send_notification(
            title="🚨 CRITICAL: EMERGENCY KILL SWITCH ENGAGED",
            text=f"The desk Kill Switch has been engaged by **{actor}**.\n\n**Reason:** *{reason}*\nAll new order submission and agent risk staging is **HALTED**.",
            color="#D32F2F",
            fields=[
                {"title": "Action", "value": "Execute `/trade reset-estop` to clear", "short": True},
                {"title": "Operator", "value": actor, "short": True},
            ],
        )

    def notify_hyper_gamma_breach(self, gamma: float, threshold: float) -> bool:
        """Dispatches warning when 0DTE hyper-gamma exposure exceeds safety limit."""
        return self.send_notification(
            title="⚠️ ALERT: 0DTE HYPER-GAMMA LIMIT BREACH",
            text=f"Current 0DTE hyper-gamma exposure **${gamma:.2f}** has breached the threshold limit **${threshold:.2f}**.",
            color="#FF9800",
            fields=[
                {"title": "Current Gamma", "value": f"${gamma:.2f}", "short": True},
                {"title": "Threshold", "value": f"${threshold:.2f}", "short": True},
                {"title": "Quick Action", "value": "`/trade flatten-0dte`", "short": True},
            ],
        )

    def notify_proposal_staged(
        self,
        proposal_id: str,
        symbol: str,
        side: str,
        quantity: int,
        strategy: str,
        rationale: str,
    ) -> bool:
        """Dispatches an interactive approval notification to Charlie on mobile."""
        return self.send_notification(
            title=f"📋 TRADE PROPOSAL STAGED: {proposal_id}",
            text=(
                f"**Symbol:** `{symbol}` ({side} {quantity} units)\n"
                f"**Strategy:** {strategy}\n"
                f"**Rationale:** {rationale}\n\n"
                f"👉 **To Approve:** `/trade approve {proposal_id}`\n"
                f"👉 **To Reject:** `/trade reject {proposal_id}`"
            ),
            color="#FFCC00",
        )
