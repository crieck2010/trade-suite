"""OCC option symbol handling.

The Options Clearing Corporation symbol packs a contract into 21
characters::

    <root><YY><MM><DD><C|P><strike>

* ``root``: underlying ticker, space-padded to 6 characters
  (e.g. ``"AAPL  "``)
* ``YYMMDD``: expiry date
* ``C``/``P``: call or put
* ``strike``: strike * 1000, zero-padded to 8 digits
  (e.g. 250.00 -> ``"00250000"``)

Example: ``AAPL  260116C00250000`` is the AAPL 2026-01-16 250 call.
"""

from __future__ import annotations

from datetime import date

from .exceptions import SymbolParseError
from .models import OptionContract, OptionRight, OptionStyle

_OCC_LENGTH = 21


def to_occ(underlying: str, expiry: date, right: OptionRight, strike: float) -> str:
    """Build the 21-character OCC symbol for a contract."""
    root = underlying.strip().upper()
    if not root:
        raise SymbolParseError("underlying must be non-empty")
    if not isinstance(right, OptionRight):
        raise SymbolParseError(f"right must be an OptionRight, got {right!r}")
    if strike <= 0:
        raise SymbolParseError(f"strike must be positive, got {strike!r}")
    strike_int = int(round(strike * 1000))
    if strike_int <= 0 or strike_int > 99_999_999:
        raise SymbolParseError(f"strike {strike!r} is not representable in OCC format")
    return f"{root:<6s}{expiry:%y%m%d}{right.value}{strike_int:08d}"


def parse_occ(symbol: str) -> OptionContract:
    """Parse a 21-character OCC symbol into an :class:`OptionContract`.

    The style defaults to American (the US equity-option convention); weekly
    vs monthly expiry is not encoded in the symbol.
    """
    text = symbol.strip().upper()
    if len(text) != _OCC_LENGTH:
        raise SymbolParseError(
            f"OCC symbols are {_OCC_LENGTH} characters, got {len(text)}: {symbol!r}"
        )
    root = text[:6].strip()
    try:
        expiry = date(2000 + int(text[6:8]), int(text[8:10]), int(text[10:12]))
    except ValueError as exc:
        raise SymbolParseError(f"bad expiry in {symbol!r}: {exc}") from exc
    try:
        right = OptionRight(text[12])
    except ValueError as exc:
        raise SymbolParseError(f"bad right flag in {symbol!r}") from exc
    try:
        strike = int(text[13:21]) / 1000.0
    except ValueError as exc:
        raise SymbolParseError(f"bad strike in {symbol!r}: {exc}") from exc
    if strike <= 0:
        raise SymbolParseError(f"bad strike in {symbol!r}")
    return OptionContract(
        underlying=root,
        expiry=expiry,
        strike=strike,
        right=right,
        style=OptionStyle.AMERICAN,
    )
