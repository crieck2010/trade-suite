"""Signal evaluation: simple sentiment rules → forward-return stats.

Not a backtester (trade-backtest owns that) — this answers "is there
anything here?" with per-trade stats: hit rate, mean return, and a t-stat
on the mean trade.  Feed the signals to trade-backtest for full portfolio
simulation via adapters.to_backtest_signals.
"""

from __future__ import annotations

from .indicators import attention_zscore, sentiment_zscore
from .series import AlignedSeries, net_sentiment
from .stats import mean, std, t_cdf


def zscore_rule(a: AlignedSeries, thresh: float = 2.0,
                horizon: int = 5) -> list[dict]:
    """Long when sentiment z > thresh, short when < −thresh; hold `horizon` days.

    Signals are causal: the z-score at date t uses history before t, and
    the position earns returns from t+1 over `horizon` days.
    """
    zs = sentiment_zscore(a, window=20)
    rets = a.returns
    trades = []
    for t in range(len(a.dates) - horizon - 1):
        side = 1 if zs[t] > thresh else (-1 if zs[t] < -thresh else 0)
        if side == 0:
            continue
        cum = 1.0
        for h in range(horizon):
            cum *= 1.0 + rets[t + h]  # rets[t] ends at dates[t+1]
        trades.append({"date": a.dates[t], "side": side,
                       "z": zs[t], "return": side * (cum - 1.0)})
    return trades


def attention_rule(a: AlignedSeries, z_thresh: float = 2.0,
                   horizon: int = 5) -> list[dict]:
    """Trade in the direction of net sentiment on attention bursts."""
    att = attention_zscore(a)
    net = net_sentiment(a.bullishness)
    rets = a.returns
    trades = []
    for t in range(len(a.dates) - horizon - 1):
        if att[t] < z_thresh or net[t] == 0:
            continue
        side = 1 if net[t] > 0 else -1
        cum = 1.0
        for h in range(horizon):
            cum *= 1.0 + rets[t + h]
        trades.append({"date": a.dates[t], "side": side,
                       "attention_z": att[t], "return": side * (cum - 1.0)})
    return trades


def summarize_trades(trades: list[dict]) -> dict:
    """Hit rate, mean/std of trade returns, t-stat vs zero."""
    n = len(trades)
    out = {"n_trades": n}
    if n == 0:
        return out
    rs = [t["return"] for t in trades]
    longs = [t for t in trades if t["side"] == 1]
    shorts = [t for t in trades if t["side"] == -1]
    m, s = mean(rs), std(rs) if n > 1 else 0.0
    t = m / (s / (n ** 0.5)) if s > 0 and n > 1 else 0.0
    out.update({
        "hit_rate": sum(1 for r in rs if r > 0) / n,
        "mean_return": m,
        "std_return": s,
        "tstat": t,
        "pvalue": 2.0 * (1.0 - t_cdf(abs(t), n - 1)) if n > 1 else 1.0,
        "n_long": len(longs), "n_short": len(shorts),
        "total_return": sum(rs),
    })
    return out
