"""Event study: sentiment bursts → abnormal returns around events.

Events = days where mention volume or |sentiment change| spikes beyond a
trailing z-score threshold (causal: window ends the day before).  For each
event, abnormal return = realized − mean(estimation window); CAR is the
cross-event average with a t-stat.  The classic question: does the market
move *after* the crowd gets loud?
"""

from __future__ import annotations

from .series import AlignedSeries, net_sentiment
from .stats import mean, std, t_cdf


def detect_bursts(a: AlignedSeries, z_thresh: float = 2.0,
                  window: int = 20, on: str = "mentions") -> list[dict]:
    """Return event dicts for burst days (causal trailing z-scores)."""
    if on == "mentions":
        xs = [float(m) for m in a.mentions]
    elif on == "sentiment_change":
        net = net_sentiment(a.bullishness)
        xs = [0.0] + [abs(net[i] - net[i - 1]) for i in range(1, len(net))]
    else:
        raise ValueError(f"unknown burst signal: {on}")
    events = []
    for i in range(len(xs)):
        hist = xs[max(0, i - window):i]
        if len(hist) < 5:
            continue
        m, s = mean(hist), std(hist)
        z = (xs[i] - m) / s if s > 0 else 0.0
        if z >= z_thresh:
            events.append({"date": a.dates[i], "index": i, "z": z,
                           "value": xs[i]})
    return events


def event_study(a: AlignedSeries, events: list[dict],
                pre: int = 5, post: int = 10, est: int = 60) -> dict:
    """CAR around events; abnormal = return − estimation-window mean."""
    rets = a.returns  # rets[i] aligns with dates[i+1]
    cars, per_event = [], []
    for ev in events:
        # event date d → return index i where dates[i+1] == d → i = idx-1
        c = ev["index"] - 1
        if c - est - pre < 0 or c + post >= len(rets):
            continue
        est_mean = mean(rets[c - est - pre:c - pre])
        window_rets = rets[c - pre:c + post + 1]
        abnormal = [r - est_mean for r in window_rets]
        car = sum(abnormal)
        cars.append(car)
        per_event.append({"date": ev["date"], "car": car,
                          "abnormal": abnormal})
    n = len(cars)
    out = {"n_events": n, "pre": pre, "post": post,
           "mean_car": mean(cars) if n else 0.0, "events": per_event}
    if n >= 2:
        s = std(cars)
        t = out["mean_car"] / (s / (n ** 0.5)) if s > 0 else 0.0
        out["tstat"] = t
        out["pvalue"] = 2.0 * (1.0 - t_cdf(abs(t), n - 1))
    else:
        out["tstat"], out["pvalue"] = 0.0, 1.0
    return out
