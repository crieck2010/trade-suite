"""Correlation toolkit: contemporaneous, lead/lag, and rolling.

Convention: lag L means corr(sentiment[t+1], returns[t+L]).
L = 0  → sentiment and return cover the same period (contemporaneous).
L > 0  → sentiment *leads* returns (predictive — the tradeable question).
L < 0  → sentiment lags returns (price moves first, chatter follows).
"""

from __future__ import annotations

from .series import AlignedSeries, net_sentiment
from .stats import corr_pvalue, mean, pearson, spearman


def contemporaneous(a: AlignedSeries, score: str = "net",
                    method: str = "pearson") -> dict:
    """Sentiment vs same-day returns."""
    _, rets = a.paired_returns()
    s = _score(a, score)[1:]  # align to returns' end dates
    fn = pearson if method == "pearson" else spearman
    r = fn(s, rets)
    return {"r": r, "pvalue": corr_pvalue(r, len(s)), "n": len(s),
            "method": method, "score": score}


def lead_lag(a: AlignedSeries, max_lag: int = 5, score: str = "net",
             method: str = "pearson") -> dict:
    """Cross-correlation for lags −max_lag..+max_lag."""
    fn = pearson if method == "pearson" else spearman
    s = _score(a, score)   # length n, s[t] <-> dates[t]
    rets = a.returns        # length n-1, rets[t] <-> (dates[t], dates[t+1])
    n = len(s)
    rows = []
    for lag in range(-max_lag, max_lag + 1):
        # base pairing is contemporaneous: s[t+1] <-> rets[t]
        if lag >= 0:
            xs, ys = s[1:n - lag], rets[lag:n - 1]
        else:
            m = -lag
            xs, ys = s[m + 1:n], rets[0:n - 1 - m]
        r = fn(xs, ys)
        rows.append({"lag": lag, "r": r, "pvalue": corr_pvalue(r, len(xs)),
                     "n": len(xs)})
    best = max(rows, key=lambda d: abs(d["r"]))
    return {"lags": rows, "best_lag": best["lag"], "best_r": best["r"],
            "best_pvalue": best["pvalue"],
            "verdict": ("sentiment leads" if best["lag"] > 0
                        else "sentiment lags" if best["lag"] < 0
                        else "contemporaneous")}


def rolling_correlation(a: AlignedSeries, window: int = 30,
                        score: str = "net") -> list[dict]:
    """Trailing-window sentiment/return correlation — regime stability."""
    s = _score(a, score)[1:]
    _, rets = a.paired_returns()
    out = []
    for i in range(window, len(s) + 1):
        r = pearson(s[i - window:i], rets[i - window:i])
        out.append({"date": a.dates[i], "r": r,
                    "pvalue": corr_pvalue(r, window)})
    return out


def _score(a: AlignedSeries, score: str) -> list[float]:
    if score == "net":
        return net_sentiment(a.bullishness)
    if score == "bullishness":
        return list(a.bullishness)
    if score == "conviction":
        return list(a.conviction)
    if score == "mentions":
        return [float(m) for m in a.mentions]
    raise ValueError(f"unknown score: {score}")
