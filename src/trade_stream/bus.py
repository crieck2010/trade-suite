"""Thread-safe in-process pub/sub message bus.

Topics look like ``trades.BTC-USD`` or ``quotes.AAPL``; subscriptions may
use ``*`` wildcards (``fnmatch`` semantics), e.g. ``quotes.*`` or ``*``.

Backpressure policy (documented, deliberate): each subscription owns a
bounded queue and its own dispatch thread. ``publish()`` never blocks —
not even briefly — so a slow subscriber can never stall the reader
thread that feeds the bus. When a subscriber's queue is full, the
*oldest* message is dropped and a per-subscription ``dropped`` counter
increments. Dropping oldest (not newest) keeps the subscriber's view
*current*: for live prices, the latest tick matters more than a stale one.
The counter makes the loss observable instead of silent.

Subscriber callbacks receive ``(topic, msg)`` and run on the
subscription's dispatch thread. Exceptions in callbacks are swallowed and
counted (``errors``) — one bad subscriber must not kill the bus.

Unsubscribe via the returned :class:`Subscription` handle's ``close()``
(or the bus ``unsubscribe(handle)``).
"""

from __future__ import annotations

import collections
import fnmatch
import threading


class Subscription:
    """Handle for one subscription: stats, queue, and dispatch thread."""

    def __init__(self, pattern: str, callback, max_queue: int = 1000) -> None:
        if max_queue <= 0:
            raise ValueError("max_queue must be positive")
        self.pattern = pattern
        self.callback = callback
        self.max_queue = max_queue
        self._queue: collections.deque = collections.deque()
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._stop = threading.Event()
        self.dropped = 0
        self.received = 0
        self.errors = 0
        self._thread = threading.Thread(
            target=self._dispatch, name=f"bus-sub-{pattern}", daemon=True
        )
        self._thread.start()

    # -- producer side (called by MessageBus.publish) ------------------
    def _offer(self, topic: str, msg) -> None:
        with self._lock:
            if len(self._queue) >= self.max_queue:
                self._queue.popleft()
                self.dropped += 1
            self._queue.append((topic, msg))
            self._wake.notify()

    # -- consumer side --------------------------------------------------
    def _dispatch(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                while not self._queue and not self._stop.is_set():
                    self._wake.wait(timeout=0.05)
                if not self._queue:
                    continue
                topic, msg = self._queue.popleft()
            self.received += 1
            try:
                self.callback(topic, msg)
            except Exception:
                self.errors += 1

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._wake.notify_all()
        self._thread.join(timeout=2.0)

    def stats(self) -> dict:
        with self._lock:
            queued = len(self._queue)
        return {
            "pattern": self.pattern,
            "queued": queued,
            "dropped": self.dropped,
            "received": self.received,
            "errors": self.errors,
        }


class MessageBus:
    """In-process pub/sub. Thread-safe; ``publish`` never blocks."""

    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        self._lock = threading.Lock()
        self.published = 0

    def subscribe(self, pattern: str, callback, max_queue: int = 1000) -> Subscription:
        """Subscribe to a topic pattern (``*`` wildcards allowed)."""
        sub = Subscription(pattern, callback, max_queue=max_queue)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)
        sub.close()

    def publish(self, topic: str, msg) -> int:
        """Deliver ``msg`` to every matching subscription. Returns count."""
        with self._lock:
            subs = list(self._subs)
        n = 0
        for sub in subs:
            if fnmatch.fnmatchcase(topic, sub.pattern):
                sub._offer(topic, msg)
                n += 1
        self.published += 1
        return n

    def close(self) -> None:
        with self._lock:
            subs = list(self._subs)
            self._subs.clear()
        for sub in subs:
            sub.close()
