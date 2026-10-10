"""trade_lifecycle: the investment committee in code.

Promotion gates as law, not advice.  Strategies move RESEARCH -> VALIDATED
-> PAPER -> LIVE -> RETIRED strictly in order; every transition carries
machine-enforced guards, and refused attempts are logged as first-class
audit events.  PAUSED is an overlay any post-RESEARCH state can enter
(kill conditions) and exit (human re-approval only).

This module governs *permission*.  It contains no execution code paths:
nothing here can place, route, or size a trade.
"""

from __future__ import annotations

from . import adapters, evidence_translate, gates, lifecycle, policy, presets
from .demo import run_demo
from .gates import config_hash
from .lifecycle import STATES, classify
from .policy import policy_checksum, resolve_policy, write_policy
from .registry import StrategyRegistry

__version__ = "0.2.0"
__all__ = [
    "StrategyRegistry",
    "STATES",
    "classify",
    "evidence_translate",
    "gates",
    "lifecycle",
    "policy",
    "presets",
    "adapters",
    "config_hash",
    "policy_checksum",
    "resolve_policy",
    "write_policy",
    "run_demo",
    "__version__",
]
