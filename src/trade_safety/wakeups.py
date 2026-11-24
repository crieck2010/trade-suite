"""Event-driven wakeup triggers (stolen pattern, 2026-11-24).

Pattern source: an r/ai_trading desk write-up Charlie reviewed on
2026-11-24 — its agents sleep until something happens instead of
polling on a fixed cadence. Three wakeup kinds, mirroring that desk:

- ``PRICE_LEVEL`` — price crosses a level the watcher picked.
- ``ORDER_EVENT`` — an order's status enters a watched set (a stop or
  target filled, a cancellation landed, a rejection arrived).
- ``SAFETY_CLOCK`` — a maximum sleep expires, so a watcher that hears
  nothing still wakes up and re-checks.

Why this exists here: the 0DTE runner's monitored stop (decision
D-004: software-monitored, no standing orders at the broker) does not
need a fixed 30s/60s polling loop. It can arm a price-level trigger at
the stop level and a safety clock as the backstop, and only wake when
one fires. Polling remains available to the host; this module is the
event-driven alternative, not a replacement for the heartbeat
:class:`~trade_safety.watchdog.Watchdog` (which guards liveness, a
different job).

Like the watchdog, the engine owns no thread and no clock loop: the
host feeds it observations (``on_price``, ``on_order_status``,
``tick``) and receives :class:`WakeupEvent` objects back. All state is
in-memory and deterministic given the feed; timestamps are injectable
for tests. Stdlib only, broker-agnostic — the kernel never imports
broker code.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class WakeupKind(str, Enum):
    PRICE_LEVEL = "PRICE_LEVEL"
    ORDER_EVENT = "ORDER_EVENT"
    SAFETY_CLOCK = "SAFETY_CLOCK"


class CrossDirection(str, Enum):
    ABOVE = "ABOVE"  # fire when price moves from <= level to > level
    BELOW = "BELOW"  # fire when price moves from >= level to < level
    EITHER = "EITHER"


@dataclass(frozen=True)
class WakeupEvent:
    """One fired wakeup. ``detail`` carries the observation that fired it."""

    kind: WakeupKind
    trigger_id: str
    fired_at: float
    symbol: str = ""
    order_id: str = ""
    detail: dict = field(default_factory=dict)


@dataclass
class PriceLevelTrigger:
    """Fire when ``symbol`` crosses ``level`` in ``direction``.

    Crossing semantics need a baseline: the first observation after
    arming only establishes the reference price and never fires, unless
    ``fire_if_beyond`` is set — then a first observation already beyond
    the level fires immediately (the monitored-stop case: if price is
    already through the stop when the trigger arms, the runner must
    wake now, not wait for a fresh cross).
    """

    trigger_id: str
    symbol: str
    level: float
    direction: CrossDirection = CrossDirection.EITHER
    repeat: bool = False
    fire_if_beyond: bool = False


@dataclass
class OrderEventTrigger:
    """Fire when an order's status enters ``statuses``.

    Statuses are compared case-insensitively, exactly as fed (broker
    vocabularies differ; the host feeds whatever its adapter reports).
    A first observation already inside the set fires — reaching FILLED
    before the watcher armed is still the event it exists for. Staying
    inside the set does not re-fire unless ``repeat`` is set and the
    status changes to another watched status.
    """

    trigger_id: str
    order_id: str
    statuses: frozenset[str]
    repeat: bool = False

    def __post_init__(self) -> None:
        self.statuses = frozenset(s.upper() for s in self.statuses)
        if not self.statuses:
            raise ValueError("OrderEventTrigger requires at least one status")


@dataclass
class SafetyClockTrigger:
    """Fire when ``max_sleep_s`` has elapsed since arming.

    The backstop wakeup: a watcher with a safety clock can never sleep
    forever, even if no price or order event ever arrives. With
    ``repeat`` set, the clock re-arms each time it fires.
    """

    trigger_id: str
    max_sleep_s: float
    repeat: bool = False

    def __post_init__(self) -> None:
        if self.max_sleep_s <= 0:
            raise ValueError(f"max_sleep_s must be positive, got {self.max_sleep_s}")


class WakeupEngine:
    """Registry + evaluator for wakeup triggers. Host-driven, no threads."""

    def __init__(
        self,
        on_wakeup: Callable[[WakeupEvent], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.on_wakeup = on_wakeup
        self._clock = clock
        self._price_triggers: dict[str, PriceLevelTrigger] = {}
        self._order_triggers: dict[str, OrderEventTrigger] = {}
        self._clock_triggers: dict[str, SafetyClockTrigger] = {}
        self._last_price: dict[str, float] = {}
        self._baseline_done: set[str] = set()
        self._last_status: dict[str, str] = {}
        self._clock_armed_at: dict[str, float] = {}

    # -- registration ----------------------------------------------------

    def add_price_trigger(self, trigger: PriceLevelTrigger) -> None:
        self._price_triggers[trigger.trigger_id] = trigger
        self._baseline_done.discard(trigger.trigger_id)

    def add_order_trigger(self, trigger: OrderEventTrigger) -> None:
        self._order_triggers[trigger.trigger_id] = trigger

    def add_clock_trigger(self, trigger: SafetyClockTrigger, now: float | None = None) -> None:
        self._clock_triggers[trigger.trigger_id] = trigger
        self._clock_armed_at[trigger.trigger_id] = self._now(now)

    def remove(self, trigger_id: str) -> bool:
        """Disarm a trigger by id. Returns True if one was armed."""
        removed = False
        for table in (self._price_triggers, self._order_triggers, self._clock_triggers):
            if table.pop(trigger_id, None) is not None:
                removed = True
        self._baseline_done.discard(trigger_id)
        self._clock_armed_at.pop(trigger_id, None)
        return removed

    def armed_ids(self) -> list[str]:
        return [
            *self._price_triggers,
            *self._order_triggers,
            *self._clock_triggers,
        ]

    # -- observation feeds -------------------------------------------------

    def on_price(self, symbol: str, price: float, now: float | None = None) -> list[WakeupEvent]:
        """Feed one price observation; returns the wakeups it fired."""
        ts = self._now(now)
        prev = self._last_price.get(symbol)
        self._last_price[symbol] = price
        events: list[WakeupEvent] = []
        for trigger in list(self._price_triggers.values()):
            if trigger.symbol != symbol:
                continue
            if trigger.trigger_id not in self._baseline_done:
                self._baseline_done.add(trigger.trigger_id)
                if trigger.fire_if_beyond and self._beyond(trigger, price):
                    events.append(self._fire_price(trigger, price, prev, ts))
                continue
            if prev is None:
                continue
            if self._crossed(trigger, prev, price):
                events.append(self._fire_price(trigger, price, prev, ts))
        return events

    def on_order_status(self, order_id: str, status: str, now: float | None = None) -> list[WakeupEvent]:
        """Feed one order-status observation; returns the wakeups it fired."""
        ts = self._now(now)
        status = status.upper()
        prev = self._last_status.get(order_id)
        self._last_status[order_id] = status
        events: list[WakeupEvent] = []
        for trigger in list(self._order_triggers.values()):
            if trigger.order_id != order_id or status not in trigger.statuses:
                continue
            if prev == status:
                continue  # no transition; repeat re-fires only on a new watched status
            events.append(
                self._emit(
                    WakeupEvent(
                        kind=WakeupKind.ORDER_EVENT,
                        trigger_id=trigger.trigger_id,
                        fired_at=ts,
                        order_id=order_id,
                        detail={"status": status, "previous_status": prev},
                    )
                )
            )
            if not trigger.repeat:
                self._order_triggers.pop(trigger.trigger_id, None)
        return events

    def tick(self, now: float | None = None) -> list[WakeupEvent]:
        """Evaluate safety clocks once; returns the wakeups that fired."""
        ts = self._now(now)
        events: list[WakeupEvent] = []
        for trigger in list(self._clock_triggers.values()):
            armed_at = self._clock_armed_at.get(trigger.trigger_id)
            if armed_at is None or ts - armed_at < trigger.max_sleep_s:
                continue
            events.append(
                self._emit(
                    WakeupEvent(
                        kind=WakeupKind.SAFETY_CLOCK,
                        trigger_id=trigger.trigger_id,
                        fired_at=ts,
                        detail={"slept_s": ts - armed_at, "max_sleep_s": trigger.max_sleep_s},
                    )
                )
            )
            if trigger.repeat:
                self._clock_armed_at[trigger.trigger_id] = ts
            else:
                self._clock_triggers.pop(trigger.trigger_id, None)
                self._clock_armed_at.pop(trigger.trigger_id, None)
        return events

    # -- internals ---------------------------------------------------------

    def _now(self, now: float | None) -> float:
        return self._clock() if now is None else now

    @staticmethod
    def _beyond(trigger: PriceLevelTrigger, price: float) -> bool:
        if trigger.direction is CrossDirection.ABOVE:
            return price > trigger.level
        if trigger.direction is CrossDirection.BELOW:
            return price < trigger.level
        return price != trigger.level

    @staticmethod
    def _crossed(trigger: PriceLevelTrigger, prev: float, price: float) -> bool:
        above = prev <= trigger.level < price
        below = prev >= trigger.level > price
        if trigger.direction is CrossDirection.ABOVE:
            return above
        if trigger.direction is CrossDirection.BELOW:
            return below
        return above or below

    def _fire_price(
        self, trigger: PriceLevelTrigger, price: float, prev: float | None, ts: float
    ) -> WakeupEvent:
        event = self._emit(
            WakeupEvent(
                kind=WakeupKind.PRICE_LEVEL,
                trigger_id=trigger.trigger_id,
                fired_at=ts,
                symbol=trigger.symbol,
                detail={"level": trigger.level, "price": price, "previous_price": prev},
            )
        )
        if not trigger.repeat:
            self._price_triggers.pop(trigger.trigger_id, None)
        return event

    def _emit(self, event: WakeupEvent) -> WakeupEvent:
        logger.info(
            "Wakeup fired: %s (%s) %s",
            event.trigger_id,
            event.kind.value,
            event.detail,
        )
        if self.on_wakeup is not None:
            try:
                self.on_wakeup(event)
            except Exception as exc:  # a bad callback must not mask the wakeup
                logger.error("Wakeup on_wakeup callback failed for %s: %s", event.trigger_id, exc)
        return event
