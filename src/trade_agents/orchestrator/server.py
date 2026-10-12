"""Lightweight HTTP Ingress Webhook Server for Mattermost & Tailscale.

Receives inbound Mattermost slash commands and mobile webhooks over the secure
Tailscale VPN tunnel.

Zero third-party dependencies: stdlib http.server.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from .ingress import MattermostIngressGateway
from .models import IngressMessage, MessageSource

logger = logging.getLogger("trade_agents.orchestrator.server")


class MattermostWebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler parsing incoming Mattermost payloads."""

    gateway: MattermostIngressGateway = MattermostIngressGateway()

    def do_GET(self) -> None:
        if self.path in ("/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "status": "UP",
                "service": "Mattermost-Tailscale-Ingress-Gateway",
                "version": "1.0.0",
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path not in ("/webhook/mattermost", "/webhook/mattermost/", "/api/v1/mattermost"):
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        content_type = self.headers.get("Content-Type", "")

        # Mattermost slash commands send application/x-www-form-urlencoded
        if "application/x-www-form-urlencoded" in content_type:
            parsed = urllib.parse.parse_qs(body)
            params = {k: v[0] for k, v in parsed.items()}
        else:
            try:
                params = json.loads(body)
            except Exception:
                params = {}

        # Extract client IP
        remote_ip = self.headers.get("X-Forwarded-For", self.client_address[0])

        msg = IngressMessage(
            command=params.get("command", "/trade"),
            text=params.get("text", "status"),
            channel_id=params.get("channel_id", "default"),
            channel_name=params.get("channel_name", "desk"),
            user_id=params.get("user_id", "charlie"),
            user_name=params.get("user_name", "Charlie"),
            token=params.get("token", ""),
            remote_ip=remote_ip,
            source=MessageSource.MATTERMOST_SLASH,
        )

        resp = self.gateway.handle_request(msg)

        self.send_response(resp.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp.to_dict()).encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        logger.debug("%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args)


def run_server(
    host: str = "0.0.0.0",
    port: int = 8065,
    gateway: Optional[MattermostIngressGateway] = None,
    blocking: bool = True,
) -> HTTPServer:
    """Launches the Mattermost Webhook server."""
    if gateway is not None:
        MattermostWebhookHandler.gateway = gateway

    server = HTTPServer((host, port), MattermostWebhookHandler)
    logger.info("Mattermost Ingress Gateway listening on http://%s:%d/webhook/mattermost", host, port)

    if blocking:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
    else:
        t = threading.Thread(target=server.serve_forever, daemon=True, name="Mattermost-Ingress-Server")
        t.start()

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Mattermost & Tailscale Ingress Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind")
    parser.add_argument("--port", type=int, default=8065, help="Port to listen on (default: 8065)")
    args = parser.parse_args()

    print(f"Starting Mattermost Ingress Gateway on http://{args.host}:{args.port}/webhook/mattermost")
    run_server(host=args.host, port=args.port, blocking=True)


if __name__ == "__main__":
    main()
