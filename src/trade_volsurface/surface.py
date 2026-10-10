"""VolSurface: model-free implied-volatility surface.

Built from (T, K, iv) quotes — or (T, K, price) quotes, whose IVs are
backed out.  Queries interpolate *total variance* w = σ²T, not vol:
linear in w across expiries keeps the surface free of calendar arbitrage
between the quoted slices.  Moneyness is log-forward: k = ln(K/F).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .black_scholes import implied_vol


@dataclass
class Quote:
    T: float  # expiry in years
    K: float  # strike
    iv: float | None = None  # implied vol ...
    price: float | None = None  # ... or a price to back IV out of
    kind: str = "call"


def _interp_sorted(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation, flat beyond the grid edges."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


class VolSurface:
    def __init__(self, s0: float, r: float, quotes: list[Quote]) -> None:
        if s0 <= 0:
            raise ValueError("s0 must be positive")
        self.s0, self.r = s0, r
        by_T: dict[float, list[tuple[float, float]]] = {}
        for q in quotes:
            if q.T <= 0 or q.K <= 0:
                raise ValueError("need T > 0 and K > 0")
            iv = q.iv
            if iv is None:
                if q.price is None:
                    raise ValueError("quote needs iv or price")
                iv = implied_vol(q.price, s0, q.K, q.T, r, q.kind)
            F = s0 * math.exp(r * q.T)
            by_T.setdefault(q.T, []).append((math.log(q.K / F), iv * iv * q.T))
        if not by_T:
            raise ValueError("no quotes")
        self.expiries = sorted(by_T)
        self._grid: dict[float, tuple[list[float], list[float]]] = {}
        for T, pts in by_T.items():
            pts.sort()
            ks = [p[0] for p in pts]
            ws = [p[1] for p in pts]
            self._grid[T] = (ks, ws)

    # ------------------------------------------------------------------
    @classmethod
    def from_rows(cls, s0: float, r: float, rows: list[dict]) -> "VolSurface":
        """Duck-typed constructor: each row has T, K, and iv or price (+kind)."""
        return cls(s0, r, [Quote(T=row["T"], K=row["K"],
                                 iv=row.get("iv"), price=row.get("price"),
                                 kind=row.get("kind", "call")) for row in rows])

    def bumped(self, div_bump: float) -> "VolSurface":
        """Copy with every IV shifted by ``div_bump`` (vol points, not %).

        The scenario-analysis primitive for trade-risk: shock the surface,
        reprice, compare.
        """
        quotes = []
        for T in self.expiries:
            ks, ws = self._grid[T]
            F = self.s0 * math.exp(self.r * T)
            for k, w in zip(ks, ws):
                iv = math.sqrt(w / T) + div_bump
                quotes.append(Quote(T=T, K=F * math.exp(k), iv=max(iv, 1e-6)))
        return VolSurface(self.s0, self.r, quotes)

    # ------------------------------------------------------------------
    def _slice_w(self, T: float, k: float) -> float:
        ks, ws = self._grid[T]
        return _interp_sorted(ks, ws, k)

    def total_variance(self, K: float, T: float) -> float:
        """w(K, T) = σ²T, interpolated linearly in T between slices."""
        if K <= 0 or T <= 0:
            raise ValueError("need K > 0 and T > 0")
        k = math.log(K / (self.s0 * math.exp(self.r * T)))
        Ts = self.expiries
        if T <= Ts[0]:
            return self._slice_w(Ts[0], k)
        if T >= Ts[-1]:
            return self._slice_w(Ts[-1], k)
        for i in range(1, len(Ts)):
            if T <= Ts[i]:
                t = (T - Ts[i - 1]) / (Ts[i] - Ts[i - 1])
                w1 = self._slice_w(Ts[i - 1], k)
                w2 = self._slice_w(Ts[i], k)
                return w1 + t * (w2 - w1)
        return self._slice_w(Ts[-1], k)

    def iv(self, K: float, T: float) -> float:
        return math.sqrt(self.total_variance(K, T) / T)

    def atm_iv(self, T: float) -> float:
        return self.iv(self.s0 * math.exp(self.r * T), T)

    def atm_term_structure(self) -> list[tuple[float, float]]:
        return [(T, self.atm_iv(T)) for T in self.expiries]

    def forward_variance(self, T1: float, T2: float) -> float:
        """Annualized forward variance between T1 and T2 at the forward."""
        if not T2 > T1 > 0:
            raise ValueError("need 0 < T1 < T2")
        F1 = self.s0 * math.exp(self.r * T1)
        F2 = self.s0 * math.exp(self.r * T2)
        w1 = self.total_variance(F1, T1)
        w2 = self.total_variance(F2, T2)
        return (w2 - w1) / (T2 - T1)

    def smile(self, T: float, n: int = 21, k_width: float = 0.5) -> list[dict]:
        """IV smile across strikes for one expiry (or interpolated T)."""
        F = self.s0 * math.exp(self.r * T)
        out = []
        for i in range(n):
            k = -k_width + 2 * k_width * i / (n - 1)
            K = F * math.exp(k)
            out.append({"K": K, "k": k, "iv": self.iv(K, T)})
        return out
