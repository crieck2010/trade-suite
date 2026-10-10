"""trade-multitest: multiple-testing correction for research validation.

Canonical multiplicity engine for the trade-suite research lane: Deflated
Sharpe Ratio, White's Reality Check, Hansen's SPA test and Holm step-down,
with a CLI that turns a research round's trial results into
multiplicity-adjusted ``validated`` / ``invalidated`` verdicts.
"""

from .dsr import dsr, dsr_from_returns, expected_sharpe_null, moments
from .holm import holm, t_test_pvalues
from .reality_check import reality_check
from .spa import spa_test

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "dsr",
    "dsr_from_returns",
    "expected_sharpe_null",
    "holm",
    "moments",
    "reality_check",
    "spa_test",
    "t_test_pvalues",
]
