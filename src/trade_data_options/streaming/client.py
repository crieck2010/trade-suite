"""WebSocket Client for ThetaData v3 Local Terminal.

Connects to the local Java terminal WebSocket interface (default ``ws://127.0.0.1:25503/v3/ws``).
Never transmits or handles user credentials — the local terminal manages auth.

Features:
- Background event loop in a dedicated daemon thread.
- Thread-safe pub/sub callback dispatcher.
- Automatic reconnect with exponential backoff and subscription re-registration.
- High-fidelity offline simulation mode for local testing without Java terminal.
- Conforms to Zero-Overhead and Fail-Soft principles.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import websockets.asyncio.client

from ..models import OptionRight, ensure_utc
from .models import ConnectionState, LiveQuote

logger = logging.getLogger(__name__)


def _parse_right(val: Any) -> OptionRight:
    s = str(val).upper().strip()
    if s in ("C", "CALL"):
        return OptionRight.CALL
    return OptionRight.PUT


def _parse_date(val: Any) -> date:
    s = str(val).replace("-", "").strip()
    return datetime.strptime(s, "%Y%m%d").date()


class ThetaDataWebSocketClient:
    """Thread-safe WebSocket client for ThetaData v3 Terminal streaming."""

    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:25503/v3/ws",
        auto_reconnect: bool = True,
        initial_backoff_sec: float = 1.0,
        max_backoff_sec: float = 30.0,
        simulation_mode: bool = False,
    ) -> None:
        self.ws_url = ws_url
        self.auto_reconnect = auto_reconnect
        self.initial_backoff_sec = initial_backoff_sec
        self.max_backoff_sec = max_backoff_sec
        self.simulation_mode = simulation_mode

        self._state = ConnectionState.DISCONNECTED
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[Any] = None
        self._stop_event = threading.Event()

        # Subscriptions: (symbol, exp_str, strike, right_str)
        self._subscriptions: Set[Tuple[str, str, float, str]] = set()

        # Listeners
        self._quote_listeners: List[Callable[[LiveQuote], None]] = []
        self._state_listeners: List[Callable[[ConnectionState, str], None]] = []
        self._error_listeners: List[Callable[[Exception], None]] = []

    @property
    def state(self) -> ConnectionState:
        with self._lock:
            return self._state

    def add_quote_listener(self, cb: Callable[[LiveQuote], None]) -> None:
        with self._lock:
            if cb not in self._quote_listeners:
                self._quote_listeners.append(cb)

    def remove_quote_listener(self, cb: Callable[[LiveQuote], None]) -> None:
        with self._lock:
            if cb in self._quote_listeners:
                self._quote_listeners.remove(cb)

    def add_state_listener(self, cb: Callable[[ConnectionState, str], None]) -> None:
        with self._lock:
            if cb not in self._state_listeners:
                self._state_listeners.append(cb)

    def add_error_listener(self, cb: Callable[[Exception], None]) -> None:
        with self._lock:
            if cb not in self._error_listeners:
                self._error_listeners.append(cb)

    def _set_state(self, new_state: ConnectionState, reason: str = "") -> None:
        with self._lock:
            self._state = new_state
            listeners = list(self._state_listeners)
        for cb in listeners:
            try:
                cb(new_state, reason)
            except Exception as e:
                logger.warning("Error in state change callback: %s", e)

    def _dispatch_quote(self, quote: LiveQuote) -> None:
        with self._lock:
            listeners = list(self._quote_listeners)
        for cb in listeners:
            try:
                cb(quote)
            except Exception as e:
                logger.warning("Error in quote callback: %s", e)

    def start(self) -> None:
        """Starts the WebSocket client thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="ThetaData-WS-Worker", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Stops the WebSocket client and closes active connections."""
        self._stop_event.set()
        with self._lock:
            loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_close(), loop)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._set_state(ConnectionState.DISCONNECTED, "Client stopped by user")

    def subscribe(
        self, symbol: str, expiration: date, strike: float, right: OptionRight
    ) -> None:
        """Subscribes to live NBBO quotes for a contract."""
        sub_key = (
            symbol.upper(),
            expiration.strftime("%Y%m%d"),
            float(strike),
            right.value,
        )
        with self._lock:
            self._subscriptions.add(sub_key)
            loop = self._loop
            ws = self._ws

        if loop is not None and loop.is_running() and ws is not None:
            asyncio.run_coroutine_threadsafe(self._send_subscription(sub_key), loop)

    def unsubscribe(
        self, symbol: str, expiration: date, strike: float, right: OptionRight
    ) -> None:
        """Unsubscribes from live NBBO quotes."""
        sub_key = (
            symbol.upper(),
            expiration.strftime("%Y%m%d"),
            float(strike),
            right.value,
        )
        with self._lock:
            self._subscriptions.discard(sub_key)
            loop = self._loop
            ws = self._ws

        if loop is not None and loop.is_running() and ws is not None:
            asyncio.run_coroutine_threadsafe(self._send_unsubscription(sub_key), loop)

    def inject_simulated_quote(self, quote: LiveQuote) -> None:
        """Injects a simulated quote directly into listeners (used for testing/simulation)."""
        self._dispatch_quote(quote)

    async def _send_subscription(self, sub: Tuple[str, str, float, str]) -> None:
        if self._ws is None or self.simulation_mode:
            return
        payload = {
            "msg_type": "mkt_data",
            "sec_type": "option",
            "req_type": "quote",
            "symbol": sub[0],
            "expiration": sub[1],
            "strike": int(sub[2] * 1000),  # ThetaData integer strike format
            "right": sub[3],
        }
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.warning("Failed to send subscription: %s", e)

    async def _send_unsubscription(self, sub: Tuple[str, str, float, str]) -> None:
        if self._ws is None or self.simulation_mode:
            return
        payload = {
            "msg_type": "cancel",
            "sec_type": "option",
            "req_type": "quote",
            "symbol": sub[0],
            "expiration": sub[1],
            "strike": int(sub[2] * 1000),
            "right": sub[3],
        }
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as e:
            logger.warning("Failed to send cancel: %s", e)

    async def _async_close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    def _run_loop(self) -> None:
        """Background thread target."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop

        try:
            loop.run_until_complete(self._worker_coro())
        finally:
            loop.close()
            with self._lock:
                self._loop = None

    async def _worker_coro(self) -> None:
        backoff = self.initial_backoff_sec

        while not self._stop_event.is_set():
            if self.simulation_mode:
                self._set_state(ConnectionState.CONNECTED, "Simulation mode active")
                while not self._stop_event.is_set() and self.simulation_mode:
                    await asyncio.sleep(0.5)
                continue

            self._set_state(
                ConnectionState.CONNECTING if backoff == self.initial_backoff_sec else ConnectionState.RECONNECTING,
                f"Connecting to {self.ws_url}...",
            )

            try:
                async with websockets.asyncio.client.connect(
                    self.ws_url,
                    open_timeout=4.0,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    with self._lock:
                        self._ws = ws
                    backoff = self.initial_backoff_sec
                    self._set_state(ConnectionState.CONNECTED, "Connected to local ThetaData Terminal")

                    # Re-subscribe existing subscriptions
                    with self._lock:
                        subs = list(self._subscriptions)
                    for sub in subs:
                        await self._send_subscription(sub)

                    # Message loop
                    async for raw in ws:
                        if self._stop_event.is_set():
                            break
                        self._handle_raw_message(raw)

            except (websockets.exceptions.ConnectionClosed, OSError, Exception) as exc:
                with self._lock:
                    self._ws = None
                if self._stop_event.is_set():
                    break
                self._set_state(ConnectionState.FAILED, f"Connection error: {exc}")
                with self._lock:
                    listeners = list(self._error_listeners)
                for cb in listeners:
                    try:
                        cb(exc)
                    except Exception:
                        pass

                if not self.auto_reconnect:
                    break

                # Sleep with backoff
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, self.max_backoff_sec)

        self._set_state(ConnectionState.DISCONNECTED, "Connection closed")

    def _handle_raw_message(self, raw: str | bytes) -> None:
        try:
            if isinstance(raw, bytes):
                text = raw.decode("utf-8")
            else:
                text = raw
            data = json.loads(text)
        except Exception:
            return

        quote = self._parse_quote_payload(data)
        if quote is not None:
            self._dispatch_quote(quote)

    def _parse_quote_payload(self, data: Dict[str, Any]) -> Optional[LiveQuote]:
        """Parses ThetaData v3 quote responses."""
        # Handles standard dict or nested payload formats
        if not isinstance(data, dict):
            return None

        # Verify quote type
        msg_type = str(data.get("type") or data.get("msg_type") or "").lower()
        if msg_type and msg_type not in ("quote", "nbbo", "mkt_data"):
            return None

        try:
            sym = str(data.get("symbol") or "SPX").upper()
            exp_raw = data.get("expiration") or data.get("exp")
            if not exp_raw:
                return None
            exp = _parse_date(exp_raw)

            strike_raw = data.get("strike")
            if strike_raw is None:
                return None
            strike = float(strike_raw)
            if strike > 50000:  # ThetaData integer format (e.g. 5800000 -> 5800.0)
                strike /= 1000.0

            right = _parse_right(data.get("right") or data.get("option_right") or "C")
            bid = float(data.get("bid", 0.0))
            ask = float(data.get("ask", 0.0))
            bid_size = int(data.get("bid_size", data.get("bid_sz", 0)))
            ask_size = int(data.get("ask_size", data.get("ask_sz", 0)))
            volume = int(data.get("volume", data.get("vol", 0)))

            ts_raw = data.get("timestamp") or data.get("created")
            if ts_raw:
                if isinstance(ts_raw, (int, float)):
                    ts = datetime.fromtimestamp(ts_raw / 1000.0 if ts_raw > 1e11 else ts_raw, tz=timezone.utc)
                else:
                    ts = ensure_utc(datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")))
            else:
                ts = datetime.now(timezone.utc)

            return LiveQuote(
                symbol=sym,
                expiration=exp,
                strike=strike,
                right=right,
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
                volume=volume,
                timestamp=ts,
            )
        except Exception as e:
            logger.debug("Failed to parse quote payload %s: %s", data, e)
            return None
