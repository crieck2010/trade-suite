"""Tests for trade_macro.weather — hand-computed rule cases."""

from __future__ import annotations

from datetime import date

import pytest

from trade_macro.flow_context import BuybackContext, ForcedSellingContext
from trade_macro.weather import (
    SCORE_COMPONENTS,
    WEATHER_RULES,
    WeatherReport,
    trading_weather,
)
from trade_macro.adapters import weather_input

D = "2026-10-11"


def bb(severity=0, as_of=D, **kw):
    kw.setdefault("in_blackout_window", severity > 0)
    kw.setdefault("score", severity / 2)
    kw.setdefault("quarter", "2026-Q3")
    kw.setdefault("source", "calendar-heuristic")
    kw.setdefault("reason", "test")
    return BuybackContext(as_of=as_of, severity=severity, **kw)


def fs(elevated=False, risk_score=0.0, as_of=D, **kw):
    kw.setdefault("realized_vol_21d", 0.55 if elevated else 0.18)
    kw.setdefault("vol_ratio", 2.9 if elevated else 1.0 + risk_score)
    kw.setdefault("below_trend", elevated or risk_score > 0)
    kw.setdefault("reason", "test")
    return ForcedSellingContext(
        as_of=as_of, risk_score=risk_score, elevated=elevated, **kw
    )


def wx(as_of=D, regime="NEUTRAL", b=None, f=None, **kw):
    return trading_weather(
        as_of,
        regime=regime,
        buyback=b if b is not None else bb(),
        forced_selling=f if f is not None else fs(),
        **kw,
    )


# --- storm rules -----------------------------------------------------------

def test_storm_on_elevated_alone():
    r = wx(f=fs(elevated=True, risk_score=0.8))
    assert r.category == "storm"
    assert r.score == SCORE_COMPONENTS["forced_selling_elevated"]  # 50
    assert any("deleveraging" in x for x in r.reasons)


def test_storm_on_contraction_plus_deep_blackout():
    r = wx(regime="CONTRACTION", b=bb(severity=2))
    assert r.category == "storm"
    # 20 (contraction) + 20 (deep blackout), no fitted weights
    assert r.score == 40
    assert len(r.reasons) == 2


def test_storm_max_documented_score():
    r = wx(regime="CONTRACTION", b=bb(severity=2),
           f=fs(elevated=True, risk_score=0.9))
    assert r.category == "storm"
    assert r.score == 90  # 50 + 20 + 20; clamp bound never binds here


# --- caution rules ----------------------------------------------------------

def test_caution_deep_blackout_alone():
    r = wx(b=bb(severity=2))
    assert r.category == "caution"
    assert r.score == 20


def test_caution_contraction_alone():
    r = wx(regime="CONTRACTION")
    assert r.category == "caution"
    assert r.score == 20


def test_caution_shoulder_blackout():
    r = wx(b=bb(severity=1))
    assert r.category == "caution"
    assert r.score == 10


def test_caution_vol_present_below_elevated_bar():
    r = wx(f=fs(risk_score=0.30))
    assert r.category == "caution"
    assert r.score == 10
    assert any("below the elevated bar" in x for x in r.reasons)


def test_vol_score_exactly_zero_is_calm():
    # boundary: vol_present requires 0.0 < risk_score
    r = wx(f=fs(risk_score=0.0))
    assert r.category == "calm"
    assert r.score == 0


def test_caution_combined_flags_no_storm():
    r = wx(regime="CONTRACTION", b=bb(severity=1), f=fs(risk_score=0.2))
    assert r.category == "caution"
    assert r.score == 40  # 20 + 10 + 10


# --- calm -------------------------------------------------------------------

def test_calm_when_nothing_fired():
    r = wx()
    assert r.category == "calm"
    assert r.score == 0
    assert r.reasons == []
    assert r.as_of == D


# --- em_state slot -----------------------------------------------------------

def test_em_state_ignored():
    base = wx().to_dict()
    other = wx(em_state={"em_percentile": 0.95, "source": "future"}).to_dict()
    assert base == other


# --- input discipline ---------------------------------------------------------

def test_as_of_accepts_iso_string_and_date():
    r1 = trading_weather(D, regime="NEUTRAL", buyback=bb(), forced_selling=fs())
    r2 = trading_weather(date(2026, 10, 11), regime="NEUTRAL",
                         buyback=bb(), forced_selling=fs())
    assert r1.as_of == r2.as_of == D


def test_as_of_mismatch_raises():
    with pytest.raises(ValueError, match="same date"):
        wx(as_of="2026-10-11", b=bb(as_of="2026-10-10"))
    with pytest.raises(ValueError, match="same date"):
        wx(as_of="2026-10-11", f=fs(as_of="2026-10-12"))


def test_invalid_regime_raises():
    with pytest.raises(ValueError, match="regime"):
        wx(regime="BULL")


def test_wrong_input_types_raise():
    with pytest.raises(TypeError):
        trading_weather(D, regime="NEUTRAL", buyback={"severity": 2},
                        forced_selling=fs())
    with pytest.raises(TypeError):
        trading_weather(D, regime="NEUTRAL", buyback=bb(),
                        forced_selling=[1, 2])


def test_bad_as_of_raises():
    with pytest.raises(ValueError):
        wx(as_of="not-a-date")


# --- report validation ---------------------------------------------------------

def test_report_rejects_bad_category_and_score():
    with pytest.raises(ValueError, match="category"):
        WeatherReport(as_of=D, category="hurricane", score=10)
    with pytest.raises(ValueError, match="score"):
        WeatherReport(as_of=D, category="calm", score=101)
    with pytest.raises(ValueError, match="score"):
        WeatherReport(as_of=D, category="calm", score=-1)


def test_to_dict_keys_and_traceability():
    r = wx(regime="CONTRACTION", b=bb(severity=2))
    d = r.to_dict()
    assert set(d) == {"as_of", "category", "score", "reasons", "inputs"}
    assert d["inputs"]["regime"] == "CONTRACTION"
    assert d["inputs"]["buyback_severity"] == 2
    assert d["inputs"]["forced_selling_elevated"] is False


def test_weather_rules_documented():
    assert len(WEATHER_RULES) == 4
    assert WEATHER_RULES[0].startswith("storm if forced_selling.elevated")


# --- adapter ---------------------------------------------------------------------

def test_weather_input_shape():
    out = weather_input(wx())
    assert set(out) == {"weather"}
    w = out["weather"]
    assert w["category"] == "calm"
    assert w["score"] == 0
    assert w["as_of"] == D


def test_weather_input_rejects_wrong_type():
    with pytest.raises(TypeError):
        weather_input({"category": "calm"})
