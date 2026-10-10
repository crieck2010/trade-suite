"""Exception hierarchy for the futures market-data engine."""


class FuturesDataError(Exception):
    """Base class for all engine errors."""


class ContractNotFoundError(FuturesDataError):
    """No contract is listed for the requested code or expiry."""


class ProviderError(FuturesDataError):
    """The provider failed after retries (network, parsing, API errors)."""


class RateLimitError(ProviderError):
    """The provider rate-limited the request; back off and retry later."""


class SymbolParseError(FuturesDataError):
    """A futures contract code could not be parsed."""


class UnknownRootError(FuturesDataError):
    """No contract specification is known for this root symbol."""
