"""trade-data-futures: futures market-data engine.

Contract specs, CME symbology, expiry calendars, continuous-contract
construction, cost-of-carry pricing, and term-structure analytics.
See README.md.
"""

from .cache import DiskCache
from .calendar import ContractCalendar, approximate_expiry
from .carry import basis, fair_value, implied_carry
from .client import FuturesDataClient
from .continuous import ContractSeries, build_continuous
from .curve import CurvePoint, CurveSegment, build_curve, curve_state
from .exceptions import (
    ContractNotFoundError,
    FuturesDataError,
    ProviderError,
    RateLimitError,
    SymbolParseError,
    UnknownRootError,
)
from .models import (
    ContractSpec,
    FuturesBar,
    FuturesContract,
    Settlement,
    Timeframe,
    ensure_utc,
)
from .providers import FuturesDataProvider, YFinanceFuturesProvider
from .specs import get_spec, known_roots, register_spec
from .symbols import build_contract_code, month_code, month_from_code, parse_contract_code

__version__ = "0.1.0"

__all__ = [
    "ContractCalendar",
    "ContractNotFoundError",
    "ContractSeries",
    "ContractSpec",
    "CurvePoint",
    "CurveSegment",
    "DiskCache",
    "FuturesBar",
    "FuturesContract",
    "FuturesDataClient",
    "FuturesDataError",
    "ProviderError",
    "RateLimitError",
    "Settlement",
    "SymbolParseError",
    "Timeframe",
    "UnknownRootError",
    "YFinanceFuturesProvider",
    "FuturesDataProvider",
    "__version__",
    "approximate_expiry",
    "basis",
    "build_continuous",
    "build_contract_code",
    "build_curve",
    "curve_state",
    "ensure_utc",
    "fair_value",
    "get_spec",
    "implied_carry",
    "known_roots",
    "month_code",
    "month_from_code",
    "parse_contract_code",
    "register_spec",
]
