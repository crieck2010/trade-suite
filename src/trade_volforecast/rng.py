"""Seeded random streams (stdlib-only).

``RandomStream`` wraps ``random.Random`` with Box-Muller normals so
every simulation in this package is reproducible: same seed, same
paths, every run.
"""

from __future__ import annotations

import math
import random


class RandomStream:
    def __init__(self, seed: int = 7) -> None:
        self.seed = seed
        self._rng = random.Random(seed)
        self._spare: float | None = None

    def uniform(self) -> float:
        return self._rng.random()

    def normal(self) -> float:
        """Standard normal via Box-Muller (caches the spare draw)."""
        if self._spare is not None:
            z, self._spare = self._spare, None
            return z
        u1 = max(self._rng.random(), 1e-300)
        u2 = self._rng.random()
        r = math.sqrt(-2.0 * math.log(u1))
        theta = 2.0 * math.pi * u2
        self._spare = r * math.sin(theta)
        return r * math.cos(theta)
