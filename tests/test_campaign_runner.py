"""trade_campaign: REGCOND-1 paper-campaign runner (Phase 2).

Uses a stub broker with the Moomoo adapter's surface and the
deterministic demo closes — plumbing proof, not strategy evidence.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from trade_campaign import CampaignConfig, run_campaign_day
from trade_campaign.data import fetch_closes
from trade_campaign.state import CampaignState
from trade_incubate.ledger import IncubationLedger
from trade_safety import SafetyConfig, SafetyKernel, SafetyState
from trade_execution.exceptions import SafetyBlockedError


class _Status:
    def __init__(self, v): self.value = v


class _Result:
    def __init__(self, order, price):
        self.success = True
        self.status = _Status("FILLED")
        self.order_id = "stub-1"
        self.filled_qty = order.quantity
        self.avg_price = price
        self.error_message = None


class _Position:
    def __init__(self, symbol, quantity, price):
        self.symbol = symbol
        self.quantity = quantity
        self.market_price = price
        self.cost_price = price
        self.unrealized_pnl = 0.0


class _Account:
    account_id = "US87654321"
    account_type = "MARGIN"

    def __init__(self, equity): self.equity = equity


class StubBroker:
    def __init__(self, equity: float = 100_000.0, block: bool = False):
        self.cash = equity
        self.positions: dict[str, _Position] = {}
        self.prices: dict[str, float] = {}
        self.block = block
        self.submitted: list = []

    def is_connected(self): return True

    def get_account(self):
        eq = self.cash + sum(p.quantity * self.prices.get(s, p.market_price)
                             for s, p in self.positions.items())
        return _Account(eq)

    def get_positions(self):
        return [p for p in self.positions.values() if p.quantity > 0]

    def place_order(self, order):
        self.submitted.append(order)
        if self.block:
            raise SafetyBlockedError(["E-Stop latch is engaged"])
        price = order.price
        self.prices[order.symbol] = price
        pos = self.positions.setdefault(
            order.symbol, _Position(order.symbol, 0, price))
        if order.action.value == "BUY":
            self.cash -= price * order.quantity
            pos.quantity += order.quantity
        else:
            self.cash += price * order.quantity
            pos.quantity -= order.quantity
        pos.market_price = price
        return _Result(order, price)


@pytest.fixture()
def cfg(tmp_path):
    return CampaignConfig(campaign_dir=tmp_path / "camp",
                          bars_source="demo")


@pytest.fixture()
def closes():
    return fetch_closes(["SPY", "CPER", "TLT", "GLD"], 750, source="demo")


def _last_date(closes) -> date:
    return max(d for series in closes.values() for d, _ in series)


def test_config_refuses_live_env(tmp_path):
    with pytest.raises(ValueError):
        CampaignConfig(env="REAL", campaign_dir=tmp_path)


def test_first_run_establishes_positions_and_records_day(cfg, closes):
    broker = StubBroker()
    summary = run_campaign_day(cfg, broker, closes, today=_last_date(closes))
    assert summary["status"] == "ok"
    assert summary["program_day"] == 1
    assert summary["stage"] == "WARMUP"
    # Establishment: from flat, every order is a BUY; warmup size 0.5.
    assert len(summary["orders"]) >= 3
    assert all(o["action"] == "BUY" for o in summary["orders"])
    invested = sum(p.quantity * p.market_price
                   for p in broker.get_positions())
    assert 0.35 < invested / 100_000.0 < 0.65  # ~50% at warmup size
    ledger = IncubationLedger(str(cfg.ledger_path))
    assert len(ledger.days()) == 1
    assert cfg.digest_dir.exists()
    state = CampaignState.load(cfg.state_path)
    assert state.last_acted is not None
    assert state.fed_through == _last_date(closes).isoformat()


def test_rerun_same_day_is_a_noop(cfg, closes):
    broker = StubBroker()
    today = _last_date(closes)
    run_campaign_day(cfg, broker, closes, today=today)
    again = run_campaign_day(cfg, broker, closes, today=today)
    assert again["status"] == "already_current"
    assert len(IncubationLedger(str(cfg.ledger_path)).days()) == 1


def test_next_session_advances_without_rebalance(cfg, closes):
    broker = StubBroker()
    today = _last_date(closes)
    run_campaign_day(cfg, broker, closes, today=today)
    nxt = today + timedelta(days=1)
    if nxt.month != today.month:
        nxt = today + timedelta(days=32 - today.day + 1)  # stay mid-month
        nxt = date(nxt.year, nxt.month, 2)
    extended = {s: series + [(nxt, series[-1][1])]
                for s, series in closes.items()}
    summary = run_campaign_day(cfg, broker, extended, today=nxt)
    assert summary["status"] == "ok"
    assert summary["program_day"] == 2
    assert summary["orders"] == []


def test_blocked_orders_are_recorded_and_not_marked_acted(cfg, closes):
    broker = StubBroker(block=True)
    summary = run_campaign_day(cfg, broker, closes, today=_last_date(closes))
    assert summary["status"] == "ok"
    assert summary["orders"]
    assert all(o["status"] == "blocked_or_error"
               for o in summary["orders"])
    state = CampaignState.load(cfg.state_path)
    assert state.last_acted is None  # will retry next session


def test_dry_run_submits_nothing(cfg, closes):
    broker = StubBroker()
    summary = run_campaign_day(cfg, broker, closes,
                               today=_last_date(closes), dry_run=True)
    assert broker.submitted == []
    assert all(o["status"] == "would_submit" for o in summary["orders"])


def test_preflight_failure_aborts_before_recording(cfg, closes):
    safety = SafetyKernel(SafetyConfig(expected_account_last4="9999"),
                          SafetyState(cfg.safety_state_path))
    broker = StubBroker()
    summary = run_campaign_day(cfg, broker, closes,
                               today=_last_date(closes),
                               safety_kernel=safety)
    assert summary["status"] == "preflight_failed"
    assert not cfg.ledger_path.exists()


def test_cost_basis_closed_trade_accounting(tmp_path):
    state = CampaignState()
    d = date(2026, 1, 5)
    assert state.apply_fill("SPY", "BUY", 10, 100.0, d) is None
    assert state.apply_fill("SPY", "SELL", 4, 110.0, d) is None
    closed = state.apply_fill("SPY", "SELL", 6, 110.0, d)
    assert closed == {"symbol": "SPY", "pnl": 100.0,
                      "date": "2026-01-05"}
    assert len(state.closed_trades) == 1
