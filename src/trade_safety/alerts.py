"""Alert sinks for safety events (E-Stop trips, breaker trips, watchdog).

A sink must never raise into the trading path: a failed phone alert is
logged, not fatal. ``MattermostWebhookSink`` posts to the same Mattermost
instance the orchestrator gateway uses; ``MemoryAlertSink`` is for tests
and drills; ``NullAlertSink`` is the silent default.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


class NullAlertSink:
    def send(self, title: str, body: str) -> None:
        logger.info("SAFETY ALERT (null sink): %s — %s", title, body)


class MemoryAlertSink:
    def __init__(self) -> None:
        self.alerts: list[dict[str, Any]] = []

    def send(self, title: str, body: str) -> None:
        self.alerts.append({"title": title, "body": body})


class MattermostWebhookSink:
    """Best-effort Mattermost incoming-webhook alert (stdlib urllib)."""

    def __init__(self, webhook_url: str, timeout_s: float = 3.0) -> None:
        self.webhook_url = webhook_url
        self.timeout_s = timeout_s

    def send(self, title: str, body: str) -> None:
        try:
            payload = json.dumps({"text": f"**{title}**\n{body}"}).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_s):
                pass
        except Exception as exc:
            logger.error("Mattermost alert failed: %s", exc)
