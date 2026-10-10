"""Characteristic-sorted portfolios: build your own SMB/HML.

Fama-French 2x3 construction: split stocks by median size, then by
30th/70th value breakpoints, form six value-weighted (here
equal-weighted) portfolios, and combine:

  SMB = ⅓(Small Value + Small Neutral + Small Growth)
      − ⅓(Big Value + Big Neutral + Big Growth)
  HML = ½(Small Value + Big Value) − ½(Small Growth + Big Growth)

Inputs are [t][i] panels: characteristics known at t, returns realized
over t→t+1.  Missing values (NaN) drop the stock for that period.
"""

from __future__ import annotations

import math


def _is_valid(x: float) -> bool:
    return x == x  # NaN check


def _quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    pos = q * (len(s) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def double_sort_returns(size_chars: list[list[float]],
                        value_chars: list[list[float]],
                        rets: list[list[float]]) -> dict[str, list[float]]:
    """2x3 sorts → dict with SMB and HML return series (decimals)."""
    T = len(rets)
    if not (len(size_chars) == len(value_chars) == T):
        raise ValueError("panel dimension mismatch")
    smb, hml = [], []
    for t in range(T):
        idx = [i for i in range(len(rets[t]))
               if _is_valid(size_chars[t][i]) and _is_valid(value_chars[t][i])
               and _is_valid(rets[t][i])]
        if len(idx) < 6:
            smb.append(float("nan"))
            hml.append(float("nan"))
            continue
        sz = [size_chars[t][i] for i in idx]
        vl = [value_chars[t][i] for i in idx]
        med = _quantile(sz, 0.5)
        b30, b70 = _quantile(vl, 0.3), _quantile(vl, 0.7)
        buckets: dict[tuple[str, str], list[float]] = {}
        for i in idx:
            s_grp = "S" if size_chars[t][i] <= med else "B"
            v = value_chars[t][i]
            v_grp = "V" if v >= b70 else ("G" if v <= b30 else "N")
            buckets.setdefault((s_grp, v_grp), []).append(rets[t][i])
        avg = {k: sum(v) / len(v) for k, v in buckets.items()}
        get = lambda k: avg.get(k, float("nan"))
        sv, sn, sg = get(("S", "V")), get(("S", "N")), get(("S", "G"))
        bv, bn, bg = get(("B", "V")), get(("B", "N")), get(("B", "G"))
        smb.append((sv + sn + sg) / 3 - (bv + bn + bg) / 3)
        hml.append((sv + bv) / 2 - (sg + bg) / 2)
    return {"SMB": smb, "HML": hml}


def long_short_weights(scores: list[float], n_long: int, n_short: int) -> list[float]:
    """Dollar-neutral weights: top-n long, bottom-n short, equal-weighted."""
    n = len(scores)
    order = sorted(range(n), key=lambda i: scores[i])
    w = [0.0] * n
    for i in order[-n_long:]:
        w[i] = 1.0 / n_long
    for i in order[:n_short]:
        w[i] = -1.0 / n_short
    return w
