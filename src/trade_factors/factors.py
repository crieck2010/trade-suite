"""Factor datasets: container, Ken French library parser, synthetic demo.

The canonical free source is Kenneth French's data library
(https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html):
download e.g. "F-F_Research_Data_5_Factors_2x3" (monthly CSV) and point
``load_french_csv`` at it.  Values arrive in percent and are converted
to decimals.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

FACTOR_SETS = {
    "ff3": ["Mkt-RF", "SMB", "HML"],
    "ff5": ["Mkt-RF", "SMB", "HML", "RMW", "CMA"],
    "carhart": ["Mkt-RF", "SMB", "HML", "Mom"],
}

FRENCH_NAMES = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF", "ST_Rev",
                "LT_Rev"]


@dataclass
class FactorData:
    dates: list[str]  # "YYYYMM"
    factors: dict[str, list[float]]  # decimals, aligned with dates
    freq: str = "monthly"

    def __post_init__(self) -> None:
        n = len(self.dates)
        for name, col in self.factors.items():
            if len(col) != n:
                raise ValueError(f"factor {name} length mismatch")

    def names(self, model: str = "ff5") -> list[str]:
        want = FACTOR_SETS[model]
        missing = [w for w in want if w not in self.factors]
        if missing:
            raise ValueError(f"factors missing for {model}: {missing}")
        return want

    def matrix(self, names: list[str]) -> list[list[float]]:
        """n×k rows for the named factors."""
        cols = [self.factors[nm] for nm in names]
        return [list(r) for r in zip(*cols)]

    def excess(self, asset_returns: list[float]) -> list[float]:
        """Asset returns minus the risk-free rate."""
        rf = self.factors.get("RF", [0.0] * len(self.dates))
        return [r - f for r, f in zip(asset_returns, rf)]

    def summary(self) -> dict:
        from .stats import mean, std
        return {nm: {"mean": mean(col), "std": std(col),
                     "annualized_mean": mean(col) * 12,
                     "annualized_vol": std(col) * (12 ** 0.5)}
                for nm, col in self.factors.items()}


def parse_french_csv(text: str) -> FactorData:
    """Parse a Ken French monthly factor CSV (percent → decimals)."""
    lines = text.replace("\r\n", "\n").splitlines()
    header_idx, names = -1, []
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.split(",")]
        if any(c in FRENCH_NAMES for c in cells) and cells[0] == "":
            header_idx, names = i, cells[1:]
            break
        if any(c in FRENCH_NAMES for c in cells):
            header_idx, names = i, cells
            if names[0] == "":
                names = names[1:]
            break
    if header_idx < 0:
        raise ValueError("no French factor header found")
    dates, cols = [], [[] for _ in names]
    for line in lines[header_idx + 1:]:
        if not re.match(r"\s*\d{6}\s*,", line):
            break
        cells = [c.strip() for c in line.split(",")]
        dates.append(cells[0].strip())
        for j, nm in enumerate(names):
            val = cells[j + 1] if j + 1 < len(cells) else ""
            cols[j].append(float(val) / 100.0 if val not in ("", "-99.99") else float("nan"))
    if not dates:
        raise ValueError("no data rows parsed")
    return FactorData(dates, dict(zip(names, cols)))


def load_french_csv(path: str) -> FactorData:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_french_csv(fh.read())


def demo_factors(n: int = 120, seed: int = 7) -> FactorData:
    """Synthetic monthly factors with realistic means/vols/correlations."""
    rng = random.Random(seed)
    dates = [f"{1990 + (i // 12):d}{i % 12 + 1:02d}" for i in range(n)]
    # (mean, vol, mkt_beta) per factor — vols monthly decimals
    spec = {"Mkt-RF": (0.006, 0.045, 1.0), "SMB": (0.002, 0.030, 0.2),
            "HML": (0.003, 0.030, -0.3), "RMW": (0.002, 0.025, -0.1),
            "CMA": (0.002, 0.025, -0.2), "Mom": (0.006, 0.040, -0.1)}
    mkt = [rng.gauss(spec["Mkt-RF"][0], spec["Mkt-RF"][1]) for _ in range(n)]
    factors = {"Mkt-RF": mkt, "RF": [0.002 + 0.0005 * rng.gauss(0, 1) for _ in range(n)]}
    for name, (mu, vol, beta) in spec.items():
        if name == "Mkt-RF":
            continue
        idio = [rng.gauss(0, vol) for _ in range(n)]
        factors[name] = [mu + beta * (m - spec["Mkt-RF"][0]) + e
                         for m, e in zip(mkt, idio)]
    return FactorData(dates, factors)
