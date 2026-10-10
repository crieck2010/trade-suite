"""Interop adapters: plain-data bridges to sibling suite modules.

Sibling imports are lazy (inside functions) so this package stays
importable and testable on its own.
"""

from __future__ import annotations

from .correlation import contemporaneous, lead_lag
from .events import detect_bursts, event_study
from .predict import information_coefficient, sign_accuracy
from .series import PriceBar, SentimentPoint, align
from .signals import summarize_trades, zscore_rule


# ------------------------------------------------------------ trade-sentiment

def from_sentiment_scan(rows: list[dict]) -> list[SentimentPoint]:
    """Parse trade-sentiment JSON rows (tolerant of key variants).

    Expected keys: date, symbol, bullishness_10 (or bullishness),
    conviction_10 (or conviction), mentions (optional).
    """
    out = []
    for r in rows:
        bull = r.get("bullishness_10", r.get("bullishness", 5.0))
        conv = r.get("conviction_10", r.get("conviction", 5.0))
        out.append(SentimentPoint(
            date=str(r["date"]), symbol=str(r.get("symbol", "")),
            bullishness=float(bull), conviction=float(conv),
            mentions=int(r.get("mentions", 0))))
    return out


# -------------------------------------------------- trade-data-equities/crypto

def prices_from_dict_bars(bars: list[dict]) -> list[PriceBar]:
    """Duck-typed bars: dicts with a date and close-ish key."""
    out = []
    for b in bars:
        date = str(b.get("date", b.get("Date", b.get("timestamp", ""))))
        close = b.get("close", b.get("Close", b.get("c")))
        if date and close is not None:
            out.append(PriceBar(date=date, close=float(close)))
    return out


# ---------------------------------------------------------------- trade-agents

def to_agent_report(symbol: str, sentiment: list[SentimentPoint],
                    prices: list[PriceBar]) -> dict:
    """One JSON bundle an agent can reason over: lead/lag, IC, events."""
    a = align(symbol, sentiment, prices)
    ll = lead_lag(a)
    ic = information_coefficient(a)
    ev = detect_bursts(a)
    es = event_study(a, ev)
    sig = summarize_trades(zscore_rule(a))
    return {
        "source": "trade-sentiment-vs-price",
        "symbol": symbol,
        "n_days": len(a.dates),
        "lead_lag": {"best_lag": ll["best_lag"], "best_r": ll["best_r"],
                     "best_pvalue": ll["best_pvalue"],
                     "verdict": ll["verdict"]},
        "ic": {"ic": ic["ic"], "rank_ic": ic["rank_ic"],
               "tstat": ic["tstat"], "pvalue": ic["pvalue"]},
        "event_study": {"n_events": es["n_events"],
                        "mean_car": es["mean_car"],
                        "tstat": es["tstat"], "pvalue": es["pvalue"]},
        "signal_eval": sig,
        "contemporaneous_r": contemporaneous(a)["r"],
    }


# --------------------------------------------------------------- trade-backtest

def to_backtest_signals(symbol: str, trades: list[dict]) -> list[dict]:
    """Trade dicts → signal rows a backtest strategy can consume."""
    return [{"date": t["date"], "symbol": symbol,
             "side": "long" if t["side"] == 1 else "short",
             "expected_return": t["return"]} for t in trades]


# --------------------------------------------------------------- trade-factors

def sentiment_mimicking_returns(score_panel: dict[str, dict[str, float]],
                                returns_panel: dict[str, dict[str, float]]) -> list[float]:
    """Realized long-short returns of a sentiment tercile portfolio.

    Each date: long top third by score, short bottom third, equal-weighted;
    earns next-date returns.  Output feeds trade-factors as a factor series.
    """
    dates = sorted(set(score_panel) & set(returns_panel))
    out = []
    for i in range(len(dates) - 1):
        d, nxt = dates[i], dates[i + 1]
        scored = [(s, score_panel[d][s]) for s in score_panel[d]
                  if s in returns_panel.get(nxt, {})]
        if len(scored) < 6:
            continue
        scored.sort(key=lambda kv: kv[1])
        k = max(1, len(scored) // 3)
        longs = [s for s, _ in scored[-k:]]
        shorts = [s for s, _ in scored[:k]]
        rl = sum(returns_panel[nxt][s] for s in longs) / len(longs)
        rs = sum(returns_panel[nxt][s] for s in shorts) / len(shorts)
        out.append(rl - rs)
    return out
