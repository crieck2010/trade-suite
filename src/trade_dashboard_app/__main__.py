"""CLI entry point for trade_dashboard_app: ``python -m trade_dashboard_app``.

Launches the Streamlit Command Center with proper path resolution.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="trade-dashboard-app: Streamlit Agentic Trading Command Center")
    parser.add_argument("--port", type=int, default=None, help="Port to run Streamlit on (default: auto or 8501)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    parser.add_argument("--headless", action="store_true", help="Run Streamlit in headless mode")
    parser.add_argument("--desktop", action="store_true", help="Launch in native Windows Edge WebView2 window")
    args = parser.parse_args()

    if args.desktop:
        from .desktop import launch_desktop
        launch_desktop(host=args.host, port=args.port)
        return

    actual_port = args.port or 8501
    app_path = Path(__file__).resolve().parent / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(actual_port),
        "--server.address",
        args.host,
    ]
    if args.headless:
        cmd.extend(["--server.headless", "true"])

    print(f"Starting Agentic Trading Command Center on http://{args.host}:{actual_port}")
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nCommand Center shutdown cleanly.")


if __name__ == "__main__":
    main()
