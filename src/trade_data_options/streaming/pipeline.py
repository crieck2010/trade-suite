"""Intraday 0DTE Streaming Pipeline for ThetaData v3.

Coordinates:
1. Real-time ATM Call and Put quotes via ThetaDataWebSocketClient.
2. Pair synthesis into LiveStraddleQuote.
3. Live EM-decay ratio tracking against the pre-registered 0.83 threshold.
4. Thread-safe trigger dispatches to trading desks, risk gates, and UI dashboards.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import date, datetime, timezone
from typing import Callable, Deque, List, Optional

from ..em_decay import HYPOTHESIS_THRESHOLD, em_decay
from ..models import OptionRight, ensure_utc
from .client import ThetaDataWebSocketClient
from .models import ConnectionState, LiveEMDecayStreamEvent, LiveQuote, LiveStraddleQuote

logger = logging.getLogger(__name__)


class ThetaData0DTEStreamingPipeline:
    """Pipelines real-time NBBO quotes into live 0DTE straddle decay telemetry."""

    def __init__(
        self,
        symbol: str = "SPX",
        strike: float = 5800.0,
        opening_em: float = 52.50,
        expiration: Optional[date] = None,
        threshold: float = HYPOTHESIS_THRESHOLD,
        client: Optional[ThetaDataWebSocketClient] = None,
        max_history: int = 500,
    ) -> None:
        self.symbol = symbol.upper()
        self.strike = float(strike)
        self.opening_em = float(opening_em)
        self.expiration = expiration or datetime.now(timezone.utc).date()
        self.threshold = float(threshold)
        self.max_history = max_history

        self.client = client or ThetaDataWebSocketClient(simulation_mode=False)

        self._lock = threading.Lock()
        self._last_call: Optional[LiveQuote] = None
        self._last_put: Optional[LiveQuote] = None
        self._last_straddle: Optional[LiveStraddleQuote] = None
        self._last_event: Optional[LiveEMDecayStreamEvent] = None
        self._history: Deque[LiveEMDecayStreamEvent] = deque(maxlen=max_history)
        self._has_fired_trigger = False

        self._decay_listeners: List[Callable[[LiveEMDecayStreamEvent], None]] = []
        self._trigger_listeners: List[Callable[[LiveEMDecayStreamEvent], None]] = []

        # Wire client quote listener
        self.client.add_quote_listener(self._on_incoming_quote)

    @property
    def connection_state(self) -> ConnectionState:
        return self.client.state

    @property
    def last_straddle(self) -> Optional[LiveStraddleQuote]:
        with self._lock:
            return self._last_straddle

    @property
    def last_event(self) -> Optional[LiveEMDecayStreamEvent]:
        with self._lock:
            return self._last_event

    @property
    def has_fired(self) -> bool:
        with self._lock:
            return self._has_fired_trigger

    def get_history(self) -> List[LiveEMDecayStreamEvent]:
        with self._lock:
            return list(self._history)

    def add_decay_listener(self, cb: Callable[[LiveEMDecayStreamEvent], None]) -> None:
        with self._lock:
            if cb not in self._decay_listeners:
                self._decay_listeners.append(cb)

    def add_trigger_listener(self, cb: Callable[[LiveEMDecayStreamEvent], None]) -> None:
        with self._lock:
            if cb not in self._trigger_listeners:
                self._trigger_listeners.append(cb)

    def start(self) -> None:
        """Starts client and subscribes to ATM Call and Put."""
        self.client.start()
        self.client.subscribe(self.symbol, self.expiration, self.strike, OptionRight.CALL)
        self.client.subscribe(self.symbol, self.expiration, self.strike, OptionRight.PUT)

    def stop(self) -> None:
        """Unsubscribes and stops client."""
        self.client.unsubscribe(self.symbol, self.expiration, self.strike, OptionRight.CALL)
        self.client.unsubscribe(self.symbol, self.expiration, self.strike, OptionRight.PUT)
        self.client.stop()

    def update_parameters(
        self,
        symbol: Optional[str] = None,
        strike: Optional[float] = None,
        opening_em: Optional[float] = None,
        expiration: Optional[date] = None,
        threshold: Optional[float] = None,
    ) -> None:
        """Updates pipeline target strike, symbol, or opening EM dynamically."""
        with self._lock:
            old_sym = self.symbol
            old_strike = self.strike
            old_exp = self.expiration

            if symbol:
                self.symbol = symbol.upper()
            if strike is not None:
                self.strike = float(strike)
            if opening_em is not None:
                self.opening_em = float(opening_em)
            if expiration is not None:
                self.expiration = expiration
            if threshold is not None:
                self.threshold = float(threshold)

            needs_resub = (
                self.symbol != old_sym or self.strike != old_strike or self.expiration != old_exp
            )

        if needs_resub:
            self.client.unsubscribe(old_sym, old_exp, old_strike, OptionRight.CALL)
            self.client.unsubscribe(old_sym, old_exp, old_strike, OptionRight.PUT)
            self.client.subscribe(self.symbol, self.expiration, self.strike, OptionRight.CALL)
            self.client.subscribe(self.symbol, self.expiration, self.strike, OptionRight.PUT)

    def simulate_tick(
        self,
        call_bid: float,
        call_ask: float,
        put_bid: float,
        put_ask: float,
        timestamp: Optional[datetime] = None,
    ) -> LiveEMDecayStreamEvent:
        """Directly evaluates a simulated tick across both legs (useful for tests and demos)."""
        ts = timestamp or datetime.now(timezone.utc)
        call = LiveQuote(
            symbol=self.symbol,
            expiration=self.expiration,
            strike=self.strike,
            right=OptionRight.CALL,
            bid=call_bid,
            ask=call_ask,
            timestamp=ts,
        )
        put = LiveQuote(
            symbol=self.symbol,
            expiration=self.expiration,
            strike=self.strike,
            right=OptionRight.PUT,
            bid=put_bid,
            ask=put_ask,
            timestamp=ts,
        )
        return self._evaluate_legs(call, put)

    def _on_incoming_quote(self, quote: LiveQuote) -> None:
        """Processes incoming quote and evaluates straddle decay when legs are matched."""
        if quote.symbol != self.symbol or quote.strike != self.strike or quote.expiration != self.expiration:
            return

        with self._lock:
            if quote.right == OptionRight.CALL:
                self._last_call = quote
            else:
                self._last_put = quote
            call = self._last_call
            put = self._last_put

        if call is not None and put is not None:
            self._evaluate_legs(call, put)

    def _evaluate_legs(self, call: LiveQuote, put: LiveQuote) -> LiveEMDecayStreamEvent:
        """Calculates straddle mid and decay event from call and put quotes."""
        with self._lock:
            self._last_call = call
            self._last_put = put

            straddle = LiveStraddleQuote(
                symbol=self.symbol,
                expiration=self.expiration,
                strike=self.strike,
                call_quote=call,
                put_quote=put,
                timestamp=datetime.now(timezone.utc),
            )
            self._last_straddle = straddle

            # Calculate EM decay using core library function
            decay_ratio = em_decay(self.opening_em, call.mid, put.mid)
            is_triggered = decay_ratio <= self.threshold

            event = LiveEMDecayStreamEvent(
                symbol=self.symbol,
                expiration=self.expiration,
                strike=self.strike,
                opening_em=self.opening_em,
                current_straddle_mid=straddle.straddle_mid,
                decay_ratio=decay_ratio,
                threshold=self.threshold,
                is_triggered=is_triggered,
                timestamp=straddle.timestamp,
            )
            self._last_event = event
            self._history.append(event)

            fire_trigger = is_triggered and not self._has_fired_trigger
            if fire_trigger:
                self._has_fired_trigger = True

            decay_listeners = list(self._decay_listeners)
            trigger_listeners = list(self._trigger_listeners) if fire_trigger else []

        # Dispatch listeners outside lock
        for cb in decay_listeners:
            try:
                cb(event)
            except Exception as e:
                logger.warning("Error in decay listener callback: %s", e)

        for cb in trigger_listeners:
            try:
                cb(event)
            except Exception as e:
                logger.warning("Error in trigger listener callback: %s", e)

        return event
