"""Native Windows Desktop Launcher for trade_dashboard_app.

Wraps the Streamlit Command Center into a native Windows desktop window using
Microsoft Edge Chromium WebView2 via ``pywebview``.

Architecture:
1. Allocates an ephemeral or designated localhost port (default 8501+).
2. Spawns the Streamlit web engine in an isolated daemon thread using
   ``streamlit.web.bootstrap.run`` with headless configuration.
3. Polls the internal Streamlit healthcheck endpoint (``/_stcore/health``)
   until the HTTP server is responsive.
4. Mounts the native Edge WebView2 window with hardware-accelerated rendering.
5. On window close, cleanly terminates background threads and exits.
6. Fail-soft: if pywebview or WebView2 is unavailable, falls back to the system browser.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

logger = logging.getLogger("trade_dashboard_app.desktop")


def find_free_port(start_port: int = 8501, max_tries: int = 100) -> int:
    """Finds an available TCP port on localhost."""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


def wait_for_server(url: str, timeout_sec: float = 20.0) -> bool:
    """Polls the Streamlit health endpoint until the server is ready."""
    health_url = f"{url}/_stcore/health"
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout_sec:
        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "TradeDashboardDesktop/1.0"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def get_app_script_path() -> Path:
    """Resolves the absolute path to app.py in both development and PyInstaller bundles."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # Running inside PyInstaller onefile/onedir bundle
        base_dir = Path(sys._MEIPASS)
        candidate1 = base_dir / "trade_dashboard_app" / "app.py"
        if candidate1.exists():
            return candidate1
        candidate2 = base_dir / "app.py"
        if candidate2.exists():
            return candidate2
        return candidate1
    return Path(__file__).resolve().parent / "app.py"


def run_streamlit_thread(script_path: Path, host: str, port: int) -> None:
    """Launches the Streamlit runtime programmatically on a background thread."""
    from streamlit.web import bootstrap

    flag_options = {
        "server.port": port,
        "server.address": host,
        "server.headless": True,
        "browser.gatherUsageStats": False,
        "global.developmentMode": False,
    }

    try:
        bootstrap.run(
            main_script_path=str(script_path),
            is_hello=False,
            args=[],
            flag_options=flag_options,
        )
    except Exception as e:
        logger.error("Streamlit server error: %s", e)


def launch_desktop(
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    width: int = 1440,
    height: int = 900,
    use_browser: bool = False,
    title: str = "Agentic AI Algorithmic Trading System — Command Center",
) -> None:
    """Main desktop lifecycle runner."""
    script_path = get_app_script_path()
    if not script_path.exists():
        raise FileNotFoundError(f"Dashboard entry script not found: {script_path}")

    actual_port = port or find_free_port()
    base_url = f"http://{host}:{actual_port}"

    print(f"============================================================")
    print(f"🦅 Agentic AI Algorithmic Trading System — Desktop Launcher")
    print(f"Target Script: {script_path}")
    print(f"Binding Server: {base_url}")
    print(f"============================================================")

    # 1. Start Streamlit in daemon background thread
    server_thread = threading.Thread(
        target=run_streamlit_thread,
        args=(script_path, host, actual_port),
        name="Streamlit-Background-Engine",
        daemon=True,
    )
    server_thread.start()

    # 2. Wait for server to be healthy
    print("Initializing embedded Streamlit engine...")
    if not wait_for_server(base_url, timeout_sec=25.0):
        print("Warning: Streamlit healthcheck timed out, attempting connection anyway...")

    # 3. Mount UI: Native Edge WebView2 or Browser Fallback
    if use_browser:
        print(f"Opening in default system browser: {base_url}")
        webbrowser.open(base_url)
        print("Press Ctrl+C to shutdown.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down.")
            return

    # Attempt pywebview with Edge Chromium WebView2
    try:
        import webview

        print("Mounting Microsoft Edge Chromium WebView2 desktop window...")
        window = webview.create_window(
            title=title,
            url=base_url,
            width=width,
            height=height,
            min_size=(1024, 700),
            text_select=True,
        )
        # Blocks until window is closed
        webview.start(debug=False)
        print("Desktop window closed by user. Terminating background engine...")
    except ImportError:
        print("pywebview not installed. Falling back to default system browser...")
        webbrowser.open(base_url)
        print("Press Ctrl+C to terminate.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    except Exception as exc:
        print(f"WebView2 initialization failed ({exc}). Falling back to system browser...")
        webbrowser.open(base_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic Trading Desktop App Launcher")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (auto-selected if omitted)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind")
    parser.add_argument("--width", type=int, default=1440, help="Initial desktop window width")
    parser.add_argument("--height", type=int, default=900, help="Initial desktop window height")
    parser.add_argument("--browser", action="store_true", help="Launch in default system browser instead of WebView2")
    args = parser.parse_args()

    launch_desktop(
        host=args.host,
        port=args.port,
        width=args.width,
        height=args.height,
        use_browser=args.browser,
    )


if __name__ == "__main__":
    main()
