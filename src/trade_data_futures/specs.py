"""Reference contract specifications for common futures roots.

These are widely-published exchange specs, kept here so calendars,
P&L math, and tick values work out of the box. **Verify against the
exchange before live use** -- specs change (e.g. micros, tick pilots).
Register your own via :func:`register_spec`; look up with
:func:`get_spec`.
"""

from __future__ import annotations

from .exceptions import UnknownRootError
from .models import ContractSpec, Settlement

CASH, PHYS = Settlement.CASH, Settlement.PHYSICAL


def _spec(root, description, exchange, currency, multiplier, tick_size, settlement, cycle):
    return ContractSpec(
        root=root, description=description, exchange=exchange, currency=currency,
        multiplier=multiplier, tick_size=tick_size, settlement=settlement,
        cycle_months=tuple(cycle),
    )


Q = (3, 6, 9, 12)          # quarterly
M = tuple(range(1, 13))     # monthly

_SPEC_TABLE: dict[str, ContractSpec] = {}

for _s in [
    # -- CME equity index --
    _spec("ES", "E-mini S&P 500", "CME", "USD", 50, 0.25, CASH, Q),
    _spec("MES", "Micro E-mini S&P 500", "CME", "USD", 5, 0.25, CASH, Q),
    _spec("NQ", "E-mini Nasdaq-100", "CME", "USD", 20, 0.25, CASH, Q),
    _spec("MNQ", "Micro E-mini Nasdaq-100", "CME", "USD", 2, 0.25, CASH, Q),
    _spec("YM", "E-mini Dow", "CBOT", "USD", 5, 1.0, CASH, Q),
    _spec("RTY", "E-mini Russell 2000", "CME", "USD", 50, 0.10, CASH, Q),
    # -- NYMEX energy --
    _spec("CL", "WTI Crude Oil", "NYMEX", "USD", 1000, 0.01, PHYS, M),
    _spec("NG", "Henry Hub Natural Gas", "NYMEX", "USD", 10000, 0.001, PHYS, M),
    _spec("HO", "NY Harbor ULSD", "NYMEX", "USD", 42000, 0.0001, PHYS, M),
    _spec("RB", "RBOB Gasoline", "NYMEX", "USD", 42000, 0.0001, PHYS, M),
    # -- COMEX metals --
    _spec("GC", "Gold", "COMEX", "USD", 100, 0.10, PHYS, M),
    _spec("SI", "Silver", "COMEX", "USD", 5000, 0.005, PHYS, M),
    _spec("HG", "Copper", "COMEX", "USD", 25000, 0.0005, PHYS, M),
    # -- CBOT grains --
    _spec("ZC", "Corn", "CBOT", "USD", 50, 0.25, PHYS, (3, 5, 7, 9, 12)),
    _spec("ZS", "Soybeans", "CBOT", "USD", 50, 0.25, PHYS, (1, 3, 5, 7, 8, 9, 11)),
    _spec("ZW", "Wheat", "CBOT", "USD", 50, 0.25, PHYS, (3, 5, 7, 9, 12)),
    # -- CME FX --
    _spec("6E", "Euro FX", "CME", "USD", 125000, 0.00005, PHYS, Q),
    _spec("6J", "Japanese Yen", "CME", "USD", 12500000, 0.0000005, PHYS, Q),
    _spec("6B", "British Pound", "CME", "USD", 62500, 0.0001, PHYS, Q),
    # -- CBOT rates --
    _spec("ZB", "30-Year T-Bond", "CBOT", "USD", 1000, 1 / 32, PHYS, Q),
    _spec("ZN", "10-Year T-Note", "CBOT", "USD", 1000, 1 / 64, PHYS, Q),
]:
    _SPEC_TABLE[_s.root] = _s

del _s, Q, M, CASH, PHYS


def get_spec(root: str) -> ContractSpec:
    """Look up the reference spec for a root; raises :class:`UnknownRootError`."""
    try:
        return _SPEC_TABLE[root.strip().upper()]
    except KeyError as exc:
        raise UnknownRootError(
            f"no reference spec for root {root!r}; register one with register_spec()"
        ) from exc


def register_spec(spec: ContractSpec) -> None:
    """Add or override a contract specification."""
    _SPEC_TABLE[spec.root] = spec


def known_roots() -> list[str]:
    """Sorted list of roots with reference specs."""
    return sorted(_SPEC_TABLE)
