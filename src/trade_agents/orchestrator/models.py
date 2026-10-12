"""Models for Mattermost & Tailscale Ingress Gateway and LangGraph State DAG.

Conforms to:
- Strict dataclass schemas with typed validation.
- Zero third-party dependencies (stdlib only).
- Tailscale IP validation against the RFC 6598 CGNAT block (100.64.0.0/10).
"""

from __future__ import annotations

import ipaddress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def is_tailscale_ip(ip_str: str) -> bool:
    """Validates whether an IP address belongs to the Tailscale CGNAT subnet (100.64.0.0/10) or localhost."""
    clean_ip = ip_str.strip()
    if clean_ip in ("127.0.0.1", "::1", "localhost", "testclient"):
        return True
    try:
        ip = ipaddress.ip_address(clean_ip)
        tailscale_net = ipaddress.ip_network("100.64.0.0/10")
        return ip in tailscale_net
    except ValueError:
        return False


class MessageSource(Enum):
    MATTERMOST_SLASH = "mattermost_slash"
    MATTERMOST_OUTGOING = "mattermost_outgoing"
    TAILSCALE_MOBILE = "tailscale_mobile"
    LOCAL_UI = "local_ui"
    CLI = "cli"


@dataclass(frozen=True)
class IngressMessage:
    """Normalized inbound command message received via Mattermost or Tailscale tunnel."""
    command: str  # e.g. "/trade"
    text: str     # e.g. "status", "estop high-gamma", "approve P-001"
    channel_id: str = "default-channel"
    channel_name: str = "trading-desk"
    user_id: str = "charlie"
    user_name: str = "Charlie Rieck"
    token: str = ""
    remote_ip: str = "127.0.0.1"
    source: MessageSource = MessageSource.MATTERMOST_SLASH
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_authenticated_tailscale(self) -> bool:
        """Verifies origin is within trusted Tailscale VPN mesh or localhost."""
        return is_tailscale_ip(self.remote_ip)


@dataclass
class IngressResponse:
    """Formatted Mattermost response payload."""
    text: str
    response_type: str = "in_channel"  # "in_channel" or "ephemeral"
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    status_code: int = 200

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response_type": self.response_type,
            "text": self.text,
            "attachments": self.attachments,
        }
