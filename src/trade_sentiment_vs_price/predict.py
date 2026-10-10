"""Predictive tests: does sentiment forecast returns?

Three small tools, the quant-standard trio:
- Information Coefficient: rank corr(sentiment_t, return_{t+1}), with t-stat
- Forward regression: r_{t+1} = a + b·sentiment_t (+ optional controls)
- Sign accuracy: how often the sentiment sign matches next return's sign
"""

from __future__ import annotations

from .series import AlignedSeries, net_sentiment
from .stats import mean, pearson, spearman, std, t_cdf


def information_coefficient(a: AlignedSeries, horizon: int = 1,
                            score: str = "net") -> dict:
    """IC = corr(score_t, return_{t+horizon}); also rank IC."""
    s = _score(a, score)
    rets = a.returns
    xs = s[:len(s) - horizon]
    ys = _fwd(rets, s, horizon)  # fwd[t]: return over t+1..t+horizon
    ic = pearson(xs, ys)
    ric = spearman(xs, ys)
    n = len(xs)
    t = ic * ((n - 2) / max(1 - ic * ic, 1e-12)) ** 0.5 if n > 2 else 0.0
    return {"ic": ic, "rank_ic": ric, "n": n, "tstat": t,
            "pvalue": 2.0 * (1.0 - t_cdf(abs(t), n - 2)) if n > 2 else 1.0,
            "horizon": horizon, "score": score}


def _fwd(rets: list[float], s: list[float], horizon: int) -> list[float]:
    """Forward returns aligned to score dates: fwd[t] = return over t+1..t+h."""
    out = []
    for t in range(len(s) - horizon):
        # rets[t] ends at dates[t+1]; score s[t] is known at dates[t]
        cum = 1.0
        for h in range(horizon):
            cum *= 1.0 + rets[t + h]
        out.append(cum - 1.0)
    return out


def forward_regression(a: AlignedSeries, horizon: int = 1,
                       score: str = "net",
                       control_past_return: bool = True) -> dict:
    """OLS of forward returns on sentiment (+ lagged return control)."""
    s = _score(a, score)
    rets = a.returns
    n = len(s) - horizon
    fwd = _fwd(rets, s, horizon)
    # with a lagged-return control the first row has no past return → start at 1
    t0 = 1 if control_past_return else 0
    y = fwd[t0:]
    X = [[s[t]] + ([rets[t - 1]] if control_past_return else [])
         for t in range(t0, n)]
    from .ols_lite import ols
    names = ["sentiment"] + (["past_return"] if control_past_return else [])
    return ols(y, X, var_names=names).summary_dict()


def sign_accuracy(a: AlignedSeries, horizon: int = 1,
                  score: str = "net") -> dict:
    """P(sign(score_t) == sign(forward return)).  0.5 = coin flip."""
    s = _score(a, score)
    fwd = _fwd(a.returns, s, horizon)
    s = s[:len(fwd)]
    hits = sum(1 for x, y in zip(s, fwd)
               if (x > 0 and y > 0) or (x < 0 and y < 0))
    n = len(fwd)
    return {"accuracy": hits / n if n else 0.0, "hits": hits, "n": n,
            "horizon": horizon}


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
