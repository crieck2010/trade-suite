"""Tests for the ThetaData v3 local-terminal provider (no network).

All HTTP is stubbed: response mapping uses fixture payloads injected by
monkeypatching ``_get_json``; error paths monkeypatch ``urlopen``.
"""

import io
import urllib.error
from datetime import date

import pytest

from trade_data_options.exceptions import (
    ExpiryNotFoundError,
    ProviderError,
    RateLimitError,
)
from trade_data_options.models import OptionRight, OptionStyle
from trade_data_options.providers.thetadata import ThetaDataOptionsProvider


def _provider(**kwargs):
    kwargs.setdefault("rate_limit_per_minute", 60000.0)  # no real sleeps
    return ThetaDataOptionsProvider(**kwargs)


def _eod_row(**overrides):
    row = {
        "created": "2026-10-09T17:15:00",
        "expiration": "20261010",
        "strike": 770.0,
        "right": "CALL",
        "open": 1.0,
        "high": 1.5,
        "low": 0.8,
        "close": 1.2,
        "volume": 100,
        "bid": 1.10,
        "ask": 1.30,
        "implied_volatility": 0.18,
        "delta": 0.52,
        "gamma": 0.04,
        "theta": -3.1,
        "vega": 0.9,
        "rho": 0.12,
        "open_interest": 2500,
    }
    row.update(overrides)
    return row


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


# -- expiries ----------------------------------------------------------

def test_expiries_parsing(monkeypatch):
    p = _provider()
    monkeypatch.setattr(
        p, "_get_json", lambda path, params: ["2026-10-16", "20261023", "not-a-date"]
    )
    assert p.get_expiries("spx") == [date(2026, 10, 16), date(2026, 10, 23)]


# -- chain mapping -----------------------------------------------------

def _chain_provider(monkeypatch, rows):
    p = _provider()
    monkeypatch.setattr(p, "_get_json", lambda path, params: rows)
    return p


def test_chain_mapping(monkeypatch):
    rows = [
        _eod_row(strike=775.0, right="PUT", bid=2.00, ask=2.20, volume=50),
        _eod_row(strike=770.0, right="CALL", bid=1.10, ask=1.30, volume=100),
        _eod_row(strike=770.0, right="PUT", bid=0.90, ask=1.10, volume=70),
    ]
    chain = _chain_provider(monkeypatch, rows).get_chain("AAPL", date(2026, 10, 10))
    assert chain.underlying == "AAPL"
    assert len(chain.calls) == 1 and len(chain.puts) == 2
    call = chain.calls[0]
    assert call.contract.strike == 770.0
    assert call.contract.right is OptionRight.CALL
    assert call.contract.style is OptionStyle.AMERICAN
    assert call.mid == pytest.approx(1.20)  # (1.10 + 1.30) / 2 via the model
    assert call.volume == 100.0
    assert call.implied_volatility == pytest.approx(0.18)
    assert call.greeks is not None and call.greeks.delta == pytest.approx(0.52)
    assert [q.contract.strike for q in chain.puts] == [770.0, 775.0]  # sorted


def test_chain_skips_bad_rows(monkeypatch):
    rows = [
        _eod_row(strike=0),                      # non-positive strike
        _eod_row(strike=770.0, right="WARRANT"),  # unknown right
        _eod_row(strike=770.0, right="call"),     # lowercase right is fine
    ]
    chain = _chain_provider(monkeypatch, rows).get_chain("AAPL", date(2026, 10, 10))
    assert len(chain.calls) == 1


def test_chain_empty_raises(monkeypatch):
    p = _chain_provider(monkeypatch, [])
    with pytest.raises(ExpiryNotFoundError):
        p.get_chain("AAPL", date(2026, 10, 10))


def test_chain_uses_latest_report_day(monkeypatch):
    rows = [
        _eod_row(strike=770.0, created="2026-10-08T17:15:00", close=5.0),
        _eod_row(strike=770.0, created="2026-10-09T17:15:00", close=1.2),
    ]
    chain = _chain_provider(monkeypatch, rows).get_chain("AAPL", date(2026, 10, 10))
    assert len(chain.calls) == 1
    assert chain.calls[0].last == pytest.approx(1.2)


def test_european_style_for_index_underlyings(monkeypatch):
    rows = [_eod_row(strike=770.0)]
    chain = _chain_provider(monkeypatch, rows).get_chain("SPX", date(2026, 10, 10))
    assert chain.calls[0].contract.style is OptionStyle.EUROPEAN


# -- underlying price ---------------------------------------------------

def test_underlying_price(monkeypatch):
    p = _provider()
    rows = [
        {"created": "2026-10-08T17:15:00", "close": 770.5},
        {"created": "2026-10-09T17:15:00", "close": 774.31},
    ]
    monkeypatch.setattr(p, "_get_json", lambda path, params: rows)
    assert p.get_underlying_price("SPY") == pytest.approx(774.31)


def test_underlying_price_empty_raises(monkeypatch):
    p = _provider()
    monkeypatch.setattr(p, "_get_json", lambda path, params: [])
    with pytest.raises(ProviderError):
        p.get_underlying_price("SPY")


# -- error paths (stubbed urlopen) ---------------------------------------

def _refused(*args, **kwargs):
    raise urllib.error.URLError(ConnectionRefusedError("connection refused"))


def test_terminal_down_gives_clear_error(monkeypatch):
    p = _provider()
    monkeypatch.setattr(urllib.request, "urlopen", _refused)
    with pytest.raises(ProviderError, match="ThetaData Terminal v3 is not running"):
        p.get_expiries("SPX")


def test_http_429_becomes_rate_limit_error(monkeypatch):
    p = _provider()

    def _429(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://x", 429, "Too Many Requests", {}, io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", _429)
    with pytest.raises(RateLimitError):
        p.get_expiries("SPX")


def test_permission_denied_hints_paid_tier(monkeypatch):
    p = _provider()

    def _403(*args, **kwargs):
        raise urllib.error.HTTPError(
            "http://x", 403, "Forbidden", {}, io.BytesIO(b'{"error":"PERMISSION_DENIED"}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", _403)
    with pytest.raises(ProviderError, match="paid ThetaData tier"):
        p.get_expiries("SPX")


# -- configuration -------------------------------------------------------

def test_base_url_configurable(monkeypatch):
    seen = []
    p = _provider(base_url="http://example:9999")

    def _capture(request, timeout=None):
        seen.append(request.full_url)
        return _FakeResponse(b"[]")

    monkeypatch.setattr(urllib.request, "urlopen", _capture)
    p.get_expiries("SPX")
    assert seen and seen[0].startswith("http://example:9999/v3/option/list/expirations")


def test_throttle_interval_from_rate_limit():
    assert ThetaDataOptionsProvider(rate_limit_per_minute=30)._min_interval == pytest.approx(2.0)
    assert ThetaDataOptionsProvider(rate_limit_per_minute=25)._min_interval == pytest.approx(2.4)


def test_throttle_sleeps(monkeypatch):
    p = ThetaDataOptionsProvider(rate_limit_per_minute=30)
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    p._last_call = 1000.0  # just called: full 2s interval outstanding
    p._throttle()
    assert sleeps and sleeps[0] == pytest.approx(2.0)


def test_invalid_rate_limit_rejected():
    with pytest.raises(ValueError):
        ThetaDataOptionsProvider(rate_limit_per_minute=0)
