"""Futures contract symbology: CME month codes and contract codes.

Month codes (the industry standard)::

    F G H J K M N Q U V X Z
    1 2 3 4 5 6 7 8 9 10 11 12

A contract code is ``<ROOT><MONTH><YY[YY]>``, e.g. ``ESZ25`` (E-mini S&P
500, December 2025) or ``6EZ25``. Two-digit years map to 2000-2099.

Note: roots ending in a month-code letter are ambiguous (``MZ25`` parses
as root ``M``); such roots are rare in practice.
"""

from __future__ import annotations

import re

from .exceptions import SymbolParseError

_MONTH_TO_CODE = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
                  7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
_CODE_TO_MONTH = {v: k for k, v in _MONTH_TO_CODE.items()}

_PATTERN = re.compile(r"^(.+?)([FGHJKMNQUVXZ])(\d{2}|\d{4})$")


def month_code(month: int) -> str:
    """Month number (1-12) -> futures month code letter."""
    try:
        return _MONTH_TO_CODE[month]
    except KeyError as exc:
        raise SymbolParseError(f"month must be 1-12, got {month!r}") from exc


def month_from_code(code: str) -> int:
    """Futures month code letter -> month number (1-12)."""
    try:
        return _CODE_TO_MONTH[code.strip().upper()]
    except KeyError as exc:
        raise SymbolParseError(f"unknown month code {code!r}") from exc


def build_contract_code(root: str, year: int, month: int) -> str:
    """Build a CME-style contract code, e.g. ``ESZ25``."""
    clean = root.strip().upper()
    if not clean:
        raise SymbolParseError("root must be a non-empty string")
    return f"{clean}{month_code(month)}{year % 100:02d}"


def parse_contract_code(code: str) -> tuple[str, int, int]:
    """Parse ``ESZ25`` -> ``("ES", 2025, 12)``."""
    match = _PATTERN.match(code.strip().upper())
    if not match:
        raise SymbolParseError(f"not a futures contract code: {code!r}")
    root, month_letter, year_digits = match.groups()
    year = int(year_digits)
    if len(year_digits) == 2:
        year += 2000
    return root, year, month_from_code(month_letter)
