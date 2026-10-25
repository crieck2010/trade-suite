"""Tests for ThetaData v3 Live WebSocket streaming and 0DTE EM-decay pipeline."""

from datetime import date, datetime, timezone
import pytest

# The streaming client needs the optional 'websockets' package
# (pyproject 'streaming' extra); skip this module cleanly without it.
pytest.importorskip(
    "websockets",
    reason="websockets not installed (optional 'streaming' extra)",
)

from trade_data_options.models import OptionRight
from trade_data_options.streaming import (
    ConnectionState,
    LiveEMDecayStreamEvent,
    LiveQuote,
    LiveStraddleQuote,
    ThetaData0DTEStreamingPipeline,
    ThetaDataWebSocketClient,
)


def test_streaming_models():
    d = date(2026, 10, 11)
    call = LiveQuote(
        symbol="SPX",
        expiration=d,
        strike=5800.0,
        right=OptionRight.CALL,
        bid=22.50,
        ask=23.50,
        bid_size=10,
        ask_size=15,
        volume=1200,
    )
    assert call.mid == 23.00
    assert call.spread == 1.00

    put = LiveQuote(
        symbol="SPX",
        expiration=d,
        strike=5800.0,
        right=OptionRight.PUT,
        bid=20.00,
        ask=21.00,
        bid_size=8,
        ask_size=12,
        volume=1400,
    )
    assert put.mid == 20.50
    assert put.spread == 1.00

    straddle = LiveStraddleQuote(
        symbol="SPX",
        expiration=d,
        strike=5800.0,
        call_quote=call,
        put_quote=put,
    )
    assert straddle.straddle_bid == 42.50
    assert straddle.straddle_ask == 44.50
    assert straddle.straddle_mid == 43.50
    assert straddle.total_spread == 2.00

    event = LiveEMDecayStreamEvent(
        symbol="SPX",
        expiration=d,
        strike=5800.0,
        opening_em=50.00,
        current_straddle_mid=40.00,
        decay_ratio=0.80,
        threshold=0.83,
        is_triggered=True,
    )
    assert event.decay_pct_remains == 80.0
    assert event.decay_consumed_pct == 20.0
    assert event.is_triggered is True


def test_websocket_client_parser():
    client = ThetaDataWebSocketClient(simulation_mode=True)

    # 1. Standard dictionary quote with integer strike
    payload = {
        "type": "quote",
        "symbol": "SPX",
        "expiration": "20261011",
        "strike": 5800000,
        "right": "C",
        "bid": 25.10,
        "ask": 25.90,
        "bid_sz": 15,
        "ask_sz": 20,
        "vol": 500,
        "timestamp": 1791720000000,
    }
    q = client._parse_quote_payload(payload)
    assert q is not None
    assert q.symbol == "SPX"
    assert q.strike == 5800.0
    assert q.right is OptionRight.CALL
    assert q.bid == 25.10
    assert q.ask == 25.90
    assert q.mid == pytest.approx(25.50)

    # 2. Put quote with float strike
    put_payload = {
        "msg_type": "mkt_data",
        "symbol": "SPY",
        "expiration": "2026-10-11",
        "strike": 580.0,
        "right": "P",
        "bid": 2.10,
        "ask": 2.20,
    }
    pq = client._parse_quote_payload(put_payload)
    assert pq is not None
    assert pq.symbol == "SPY"
    assert pq.strike == 580.0
    assert pq.right is OptionRight.PUT
    assert pq.mid == pytest.approx(2.15)

    # 3. Invalid payload returns None
    assert client._parse_quote_payload({"type": "heartbeat"}) is None
    assert client._parse_quote_payload("not a dict") is None


def test_websocket_client_simulation_lifecycle():
    client = ThetaDataWebSocketClient(simulation_mode=True)
    states = []
    quotes = []

    client.add_state_listener(lambda s, r: states.append(s))
    client.add_quote_listener(lambda q: quotes.append(q))

    client.start()
    assert client.state in (ConnectionState.CONNECTED, ConnectionState.DISCONNECTED, ConnectionState.CONNECTING)

    # Inject simulated quote
    test_q = LiveQuote(
        symbol="SPX",
        expiration=date(2026, 10, 11),
        strike=5800.0,
        right=OptionRight.CALL,
        bid=20.0,
        ask=21.0,
    )
    client.inject_simulated_quote(test_q)
    assert len(quotes) == 1
    assert quotes[0].mid == 20.5

    client.stop()
    assert client.state is ConnectionState.DISCONNECTED


def test_streaming_pipeline_decay_and_trigger():
    d = date(2026, 10, 11)
    client = ThetaDataWebSocketClient(simulation_mode=True)
    pipeline = ThetaData0DTEStreamingPipeline(
        symbol="SPX",
        strike=5800.0,
        opening_em=50.00,
        expiration=d,
        threshold=0.83,
        client=client,
    )

    decay_events = []
    trigger_events = []
    pipeline.add_decay_listener(lambda ev: decay_events.append(ev))
    pipeline.add_trigger_listener(lambda ev: trigger_events.append(ev))

    pipeline.start()

    # Step 1: Pre-decay tick at 88% premium (Call 22.0, Put 22.0 -> Straddle 44.0 / 50.0 = 0.88)
    ev1 = pipeline.simulate_tick(
        call_bid=21.80,
        call_ask=22.20,
        put_bid=21.80,
        put_ask=22.20,
    )
    assert ev1.current_straddle_mid == pytest.approx(44.0)
    assert ev1.decay_ratio == pytest.approx(0.88)
    assert ev1.is_triggered is False
    assert len(trigger_events) == 0

    # Step 2: Trigger tick at 80% premium (Call 20.0, Put 20.0 -> Straddle 40.0 / 50.0 = 0.80 <= 0.83)
    ev2 = pipeline.simulate_tick(
        call_bid=19.80,
        call_ask=20.20,
        put_bid=19.80,
        put_ask=20.20,
    )
    assert ev2.current_straddle_mid == pytest.approx(40.0)
    assert ev2.decay_ratio == pytest.approx(0.80)
    assert ev2.is_triggered is True
    assert pipeline.has_fired is True
    assert len(trigger_events) == 1
    assert trigger_events[0].decay_ratio == pytest.approx(0.80)

    # Step 3: Subsequent tick further decayed (Call 18.0, Put 18.0 -> 36.0 / 50.0 = 0.72)
    # Trigger callback should not fire again (latched)
    ev3 = pipeline.simulate_tick(
        call_bid=17.80,
        call_ask=18.20,
        put_bid=17.80,
        put_ask=18.20,
    )
    assert ev3.decay_ratio == pytest.approx(0.72)
    assert len(trigger_events) == 1  # Still 1, not duplicate fired

    history = pipeline.get_history()
    assert len(history) == 3
    assert history[-1].decay_ratio == pytest.approx(0.72)

    # Update parameters dynamically
    pipeline.update_parameters(strike=5850.0, opening_em=55.0)
    assert pipeline.strike == 5850.0
    assert pipeline.opening_em == 55.0

    pipeline.stop()
