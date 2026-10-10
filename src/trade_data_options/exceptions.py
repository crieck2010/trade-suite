"""Exception hierarchy for the options market-data engine."""


class OptionsDataError(Exception):
    """Base class for all engine errors."""


class ExpiryNotFoundError(OptionsDataError):
    """No chain is listed for the requested expiry."""


class ProviderError(OptionsDataError):
    """The provider failed after retries (network, parsing, API errors)."""


class RateLimitError(ProviderError):
    """The provider rate-limited the request; back off and retry later."""


class ConvergenceError(OptionsDataError):
    """A numerical solver (e.g. implied volatility) failed to converge."""


class SymbolParseError(OptionsDataError):
    """An OCC option symbol could not be parsed."""


class NoUsableQuoteError(OptionsDataError):
    """No strike had usable call+put quotes for the requested computation."""
