"""Stream sessions: transport + reconnect + subscribe + bus, on one thread.

A :class:`StreamSession` owns exactly one reader thread (see
``docs/ARCHITECTURE.md`` for the threading model):

- connect the transport (WebSocket, polling fallback, or demo feed)
- send the source's subscribe message
- normalize each raw message and publish it to the bus as
  ``<kind>s.<symbol>`` (e.g. ``trades.BTC-USD``, ``quotes.AAPL``)
- on any failure — or on staleness (no frame and no pong within the
  policy's ``stale_after``) — wait the policy's backoff delay and retry

``run()`` blocks until ``stop()`` is called or the reconnect policy is
exhausted. ``start()`` runs ``run()`` on a daemon thread.

The demo source needs no network: :class:`DemoTransport` replays the
seeded :func:`trade_stream.demo.demo_feed` generator behind the same
transport interface.
"""

from __future__ import annotations

import json
import threading
import time

from .bus import MessageBus
from .reconnect import ReconnectPolicy, preset
from .replay import topic_for
from .sources import require_live
from .transport import PollingTransport, StaleConnectionError, WebSocketTransport


class DemoTransport:
    """Transport shim over the seeded demo feed (no network)."""

    def __init__(self, feed_fn) -> None:
        self._feed_fn = feed_fn
        self._stop = threading.Event()

    def connect(self) -> None:
        self._stop.clear()

    def close(self) -> None:
        self._stop.set()

    def iter_messages(self, stale_after=None):
        for raw in self._feed_fn():
            if self._stop.is_set():
                return
            yield raw
        raise FeedExhausted("demo feed finished")


class FeedExhausted(Exception):
    """The (finite) feed ended cleanly — not a failure, no reconnect."""


class StreamSession:
    """One live (or simulated) stream: source + symbols -> bus."""

    def __init__(
        self,
        source: str | dict,
        symbols: list[str],
        bus: MessageBus | None = None,
        policy: ReconnectPolicy | str | None = None,
        transport=None,
        on_error=None,
    ) -> None:
        self.source = require_live(source) if isinstance(source, str) else source
        if self.source.get("stub"):
            raise RuntimeError(
                f"source {self.source.get('name')!r} is a stub: "
                f"{self.source.get('note')}"
            )
        self.symbols = list(symbols)
        self.bus = bus if bus is not None else MessageBus()
        if policy is None:
            self.policy = preset("balanced")
        elif isinstance(policy, str):
            self.policy = preset(policy)
        else:
            self.policy = policy
        self._transport_override = transport
        self.on_error = on_error
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.restarts = 0
        self.received = 0
        self.published = 0

    # -- transport construction --------------------------------------
    def _make_transport(self):
        if self._transport_override is not None:
            return self._transport_override
        if self.source["name"] == "demo":
            from .demo import demo_feed  # local import: keeps import light

            return DemoTransport(lambda: demo_feed(symbols=tuple(self.symbols)))
        return WebSocketTransport(self.source["url"])

    # -- main loop ----------------------------------------------------
    def run(self, max_restarts: int | None = None) -> dict:
        """Block: stream until stopped or policy exhausted. Returns stats."""
        attempt = 0
        while not self._stop.is_set():
            if not self.policy.should_retry(attempt):
                break
            if max_restarts is not None and self.restarts >= max_restarts:
                break
            if attempt > 0:
                delay = self.policy.delay_for(attempt - 1)
                if self._stop.wait(delay):
                    break
            transport = self._make_transport()
            try:
                transport.connect()
                if hasattr(transport, "send_text"):
                    transport.send_text(
                        json.dumps(self.source["subscribe"](self.symbols))
                    )
                normalize = self.source["normalize"]
                for raw in transport.iter_messages(
                    stale_after=self.policy.stale_after
                ):
                    if self._stop.is_set():
                        break
                    msg = normalize(raw)
                    self.received += 1
                    if msg is None:
                        continue
                    self.bus.publish(topic_for(msg), msg)
                    self.published += 1
            except StaleConnectionError as exc:
                self._note_error("stale", exc)
            except FeedExhausted:
                break  # finite feed done; not a failure
            except Exception as exc:  # transport failure -> backoff + retry
                self._note_error("transport", exc)
            finally:
                try:
                    transport.close()
                except Exception:
                    pass
            attempt += 1
            self.restarts += 1
        return self.stats()

    def _note_error(self, kind: str, exc: BaseException) -> None:
        if self.on_error is not None:
            try:
                self.on_error(kind, exc)
            except Exception:
                pass

    def start(self) -> "StreamSession":
        self._stop.clear()
        self._thread = threading.Thread(
            target=self.run, name=f"stream-{self.source['name']}", daemon=True
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        return self.stats()

    def stats(self) -> dict:
        return {
            "source": self.source["name"],
            "symbols": self.symbols,
            "restarts": self.restarts,
            "received": self.received,
            "published": self.published,
        }


def make_polling_session(source: str | dict, symbols: list[str], fetch_fn,
                         interval: float = 5.0, **kwargs) -> StreamSession:
    """Build a session that polls a REST endpoint instead of websockets.

    ``fetch_fn`` returns a list of raw provider messages per poll; the
    source's normalizer still applies, so downstream sees identical
    canonical messages.
    """
    src = require_live(source) if isinstance(source, str) else source
    transport = PollingTransport(fetch_fn, interval=interval)
    return StreamSession(src, symbols, transport=transport, **kwargs)
