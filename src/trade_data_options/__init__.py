"""trade-data-options: listed options market-data engine.

Chains, expiries, OCC symbology, Black-Scholes pricing, implied volatility,
binomial American pricing, and chain analytics. See README.md.
"""

from .analysis import (
    atm_iv,
    breakevens,
    max_pain,
    parity_report,
    put_call_parity_deviation,
    volatility_smile,
)
from .binomial import crr_price, early_exercise_premium
from .cache import DiskCache
from .client import OptionsDataClient
from .exceptions import (
    ConvergenceError,
    ExpiryNotFoundError,
    NoUsableQuoteError,
    OptionsDataError,
    ProviderError,
    RateLimitError,
    SymbolParseError,
)
from .expected_move import ExpectedMove, expected_move, expected_move_for_expiry, scale_expected_move
from .models import (
    Greeks,
    OptionChain,
    OptionContract,
    OptionQuote,
    OptionRight,
    OptionStyle,
    ensure_utc,
)
from .pricing import bs_greeks, bs_price, implied_volatility, intrinsic_value
from .providers import OptionsDataProvider, RawChain, YFinanceOptionsProvider
from .symbols import parse_occ, to_occ
from .times import ZERO_DTE_YEARS, time_to_expiry

__version__ = "0.2.0"

__all__ = [
    "ConvergenceError",
    "DiskCache",
    "ExpectedMove",
    "ExpiryNotFoundError",
    "Greeks",
    "OptionChain",
    "OptionContract",
    "OptionQuote",
    "OptionRight",
    "OptionStyle",
    "NoUsableQuoteError",
    "OptionsDataError",
    "OptionsDataClient",
    "OptionsDataProvider",
    "ProviderError",
    "RateLimitError",
    "RawChain",
    "SymbolParseError",
    "YFinanceOptionsProvider",
    "ZERO_DTE_YEARS",
    "__version__",
    "atm_iv",
    "breakevens",
    "bs_greeks",
    "bs_price",
    "crr_price",
    "early_exercise_premium",
    "ensure_utc",
    "expected_move",
    "expected_move_for_expiry",
    "implied_volatility",
    "intrinsic_value",
    "max_pain",
    "parity_report",
    "parse_occ",
    "put_call_parity_deviation",
    "scale_expected_move",
    "time_to_expiry",
    "to_occ",
    "volatility_smile",
]
