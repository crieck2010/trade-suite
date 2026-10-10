"""Small indicator outputs: one series in, one signal series out.

Each is a pure function over an AlignedSeries — the "many small tools"
building blocks.  Combine them downstream (agents, backtests, factors).
"""

from __future__ import annotations

from .series import AlignedSeries, net_sentiment
from .stats import mean, pearson, std, trailing_zscore


def sentiment_momentum(a: AlignedSeries, window: int = 5) -> list[float]:
    """Change in net sentiment over the trailing window."""
    net = net_sentiment(a.bullishness)
    return [net[i] - net[max(0, i - window)] for i in range(len(net))]


def attention_zscore(a: AlignedSeries, window: int = 20) -> list[float]:
    """Abnormal mention volume (causal trailing z-score)."""
    return trailing_zscore([float(m) for m in a.mentions], window)


def sentiment_zscore(a: AlignedSeries, window: int = 20) -> list[float]:
    """How stretched net sentiment is vs its own recent history."""
    return trailing_zscore(net_sentiment(a.bullishness), window)


def divergence(a: AlignedSeries, price_window: int = 20,
               sent_window: int = 20) -> list[float]:
    """Price trend minus sentiment trend (standardized).

    Positive = price running ahead of sentiment (crowd not buying the
    rally — potential exhaustion); negative = sentiment ahead of price.
    """
    rets = a.returns
    price_trend = [sum(rets[max(0, i - price_window):i + 1])
                   for i in range(len(rets))]
    net = net_sentiment(a.bullishness)
    sent_trend = [net[i + 1] - net[max(0, i + 1 - sent_window)]
                  for i in range(len(rets))]
    pt = _standardize(price_trend)
    st = _standardize(sent_trend)
    return [p - s for p, s in zip(pt, st)]


def _standardize(xs: list[float]) -> list[float]:
    m, s = mean(xs), std(xs)
    return [(x - m) / s if s > 0 else 0.0 for x in xs]


def composite_attention(a: AlignedSeries) -> list[dict]:
    """Per-day bundle of the small indicators, aligned to dates."""
    mom = sentiment_momentum(a)
    att = attention_zscore(a)
    sz = sentiment_zscore(a)
    div = [0.0] + divergence(a)  # divergence is return-aligned; pad to dates
    return [{"date": d, "sentiment_momentum": m, "attention_z": z,
             "sentiment_z": s_, "divergence": dv}
            for d, m, z, s_, dv in zip(a.dates, mom, att, sz, div)]


def rolling_ic_stability(a: AlignedSeries, window: int = 60,
                         horizon: int = 1) -> list[dict]:
    """Trailing-window IC — is predictiveness stable or a one-off regime?"""
    from .predict import information_coefficient
    from .series import AlignedSeries as AS
    out = []
    for i in range(window, len(a.dates)):
        sub = AS(a.symbol, a.dates[i - window:i + 1],
                 a.bullishness[i - window:i + 1],
                 a.conviction[i - window:i + 1],
                 a.mentions[i - window:i + 1],
                 a.closes[i - window:i + 1])
        ic = information_coefficient(sub, horizon=horizon)
        out.append({"date": a.dates[i], "ic": ic["ic"],
                    "rank_ic": ic["rank_ic"], "n": ic["n"]})
    return out
