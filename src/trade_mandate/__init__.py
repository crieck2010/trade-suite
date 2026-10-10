"""trade_mandate: the machine-readable investment policy.

The PM agent's written constitution — a versioned, checksummed mandate
constraining every allocation decision, amendable only with explicit
human sign-off.  Resolves and enforces what trade-lifecycle's policy
hooks reference (``<policy_id>.md`` + SHA-256).
"""

from __future__ import annotations

from .mandate import (
    SCHEMA_VERSION, new_mandate, validate_mandate, mandate_checksum,
    render_markdown,
)
from .validate import check
from .amend import MandateStore
from .templates import get_preset, preset_names, PHILOSOPHY

__version__ = "0.1.0"
__all__ = [
    "SCHEMA_VERSION",
    "new_mandate",
    "validate_mandate",
    "mandate_checksum",
    "render_markdown",
    "check",
    "MandateStore",
    "get_preset",
    "preset_names",
    "PHILOSOPHY",
    "__version__",
]
