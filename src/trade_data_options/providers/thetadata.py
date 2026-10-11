"""Options provider backed by a local ThetaData Terminal (v3).

The provider talks to the terminal's **local** REST API
(default ``http://127.0.0.1:25503``) — never to ThetaData's cloud, and it
handles **no credentials at all**: the terminal authenticates itself
(API key / creds file live with the terminal, not in this code).

v3 endpoints used (verified against the official v3 API reference,
https://docs.thetadata.us — v3 scheme only; the deprecated v2 API on
port 25510 is NOT used):

- ``GET /v3/option/list/expirations?symbol=SYM&format=json``
  (operations/option_list_expirations)
- ``GET /v3/option/history/eod?symbol=SYM&expiration=YYYYMMDD
  &start_date=YYYYMMDD&end_date=YYYYMMDD&format=json``
  (operations/option_history_eod; ``expiration=*`` selects all expirations)
- ``GET /v3/stock/history/eod?symbol=SYM&start_date=...&end_date=...
  &format=json`` (operations/stock_history_eod) for the underlying price

Free-tier honesty (per ThetaData's Subscriptions doc, v3):

- FREE provides **EOD** (end-of-day) option chains — bid/ask, volume,
  Greeks — from **2023-06-01**, with a **~30 req/min** rate limit and a
  **1-day delay**. That is real spread data: good enough to validate the
  EM calculator on real chains and to run EOD backtests with honest costs.
- Intraday / minute-bar / tick quote endpoints are NOT on the free tier;
  they need VALUE or higher. Anything requiring intraday straddle decay
  (e.g. the 0DTE EM-decay trigger) therefore still waits on a paid tier.

The provider guards the free-tier rate limit client-side
(``rate_limit_per_minute``, default 25 — conservative under the 30 cap).

Setup (done once, by the human — never by this code):

1. Install Java 21+: ``apt install openjdk-21-jre`` (Ubuntu).
2. Download ``ThetaTerminalv3.jar`` from ThetaData and generate an API
   key (``td1_...``) at thetadata.net.
3. Launch: ``java -jar ThetaTerminalv3.jar --api-key td1_...``
   (or ``THETADATA_API_KEY`` env var / ``.env`` file — see the official
   Getting Started guide). Wait for ``Starting server at:
   http://0.0.0.0:25503/``.
4. Verify: ``curl
   "http://127.0.0.1:25503/v3/option/list/expirations?symbol=SPX&format=json"``

Zero new dependencies: HTTP is stdlib ``urllib``.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from ..exceptions import ExpiryNotFoundError, ProviderError, RateLimitError
from ..models import (
    Greeks,
    OptionContract,
    OptionQuote,
    OptionRight,
    OptionStyle,
    ensure_utc,
)
from .base import OptionsDataProvider, RawChain


def _num(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _parse_date(value) -> date | None:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value, default: datetime) -> datetime:
    if not value:
        return default
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return ensure_utc(datetime.fromisoformat(text))
    except ValueError:
        return default


class ThetaDataOptionsProvider(OptionsDataProvider):
    """EOD options chains via a local ThetaData Terminal (v3)."""

    name = "thetadata"
    delay_minutes = 1440  # EOD reports carry a 1-day delay

    #: Underlyings whose listed options are European-style.
    EUROPEAN_UNDERLYINGS = frozenset({"SPX", "SPXW", "NDX", "RUT", "XSP"})

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:25503",
        rate_limit_per_minute: float = 25.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        european_underlyings: frozenset[str] | None = None,
    ) -> None:
        if rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be positive")
        self.base_url = base_url.rstrip("/")
        self._min_interval = 60.0 / rate_limit_per_minute
        self.timeout = timeout
        self.max_retries = max_retries
        self.european_underlyings = (
            self.EUROPEAN_UNDERLYINGS
            if european_underlyings is None
            else frozenset(u.strip().upper() for u in european_underlyings)
        )
        self._last_call = 0.0

    # -- internals ----------------------------------------------------
    def _throttle(self) -> None:
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _terminal_down_error(self) -> ProviderError:
        return ProviderError(
            f"ThetaData Terminal v3 is not running at {self.base_url}. "
            "Start it with `java -jar ThetaTerminalv3.jar` (Java 21+) and "
            "wait for `Starting server at: http://0.0.0.0:25503/` — see the "
            "module docstring for setup."
        )

    def _get_json(self, path: str, params: dict) -> list | dict:
        """GET a v3 endpoint and return the parsed JSON payload."""
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}?{query}"
        last: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                request = urllib.request.Request(url, headers={"Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:500]
                except Exception:  # noqa: BLE001 - best effort
                    pass
                if exc.code == 429:
                    raise RateLimitError(
                        f"ThetaData rate limit hit (HTTP 429); back off and retry later."
                    ) from exc
                if 500 <= exc.code < 600:
                    last = exc
                    time.sleep(2**attempt)
                    continue
                hint = ""
                if "PERMISSION_DENIED" in body.upper():
                    hint = (
                        " The terminal reports PERMISSION_DENIED — this endpoint "
                        "or history range needs a paid ThetaData tier."
                    )
                raise ProviderError(
                    f"ThetaData request failed (HTTP {exc.code}): {body}.{hint}"
                ) from exc
            except urllib.error.URLError as exc:
                # Includes ConnectionRefusedError when the terminal is down.
                if isinstance(exc.reason, ConnectionRefusedError) or "refused" in str(
                    exc.reason
                ).lower():
                    raise self._terminal_down_error() from exc
                last = exc
                time.sleep(2**attempt)
            except (TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                time.sleep(2**attempt)
        raise ProviderError(
            f"ThetaData request failed after {self.max_retries} attempts: {last}"
        ) from last

    @staticmethod
    def _window(days: int) -> tuple[str, str]:
        end = date.today()
        start = end - timedelta(days=days)
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    def _style_for(self, underlying: str) -> OptionStyle:
        if underlying.strip().upper() in self.european_underlyings:
            return OptionStyle.EUROPEAN
        return OptionStyle.AMERICAN

    def _row_to_quote(
        self, row: dict, underlying: str, expiry: date, fallback_ts: datetime
    ) -> OptionQuote | None:
        strike = _num(row.get("strike"))
        if strike is None or strike <= 0:
            return None
        right_raw = str(row.get("right", "")).strip().upper()
        right = {"CALL": OptionRight.CALL, "PUT": OptionRight.PUT}.get(right_raw)
        if right is None:
            return None
        contract = OptionContract(
            underlying=underlying,
            expiry=expiry,
            strike=strike,
            right=right,
            style=self._style_for(underlying),
        )
        greeks = None
        parts = {k: _num(row.get(k)) for k in ("delta", "gamma", "theta", "vega", "rho")}
        if all(v is not None for v in parts.values()):
            greeks = Greeks(**parts)  # type: ignore[arg-type]
        return OptionQuote(
            contract=contract,
            timestamp=_parse_datetime(row.get("created"), fallback_ts),
            bid=_num(row.get("bid")),
            ask=_num(row.get("ask")),
            last=_num(row.get("close")),
            volume=_num(row.get("volume"), 0.0) or 0.0,
            open_interest=_num(row.get("open_interest"), 0.0) or 0.0,
            implied_volatility=_num(row.get("implied_volatility")),
            greeks=greeks,
        )

    def _latest_eod_rows(
        self, underlying: str, expiry: date | None
    ) -> tuple[list[dict], datetime]:
        """Most recent EOD option report rows for one expiry (or all)."""
        under = underlying.strip().upper()
        start, end = self._window(7)
        params = {
            "symbol": under,
            "expiration": expiry.strftime("%Y%m%d") if expiry else "*",
            "start_date": start,
            "end_date": end,
            "format": "json",
        }
        payload = self._get_json("/v3/option/history/eod", params)
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        by_day: dict[str, list[dict]] = {}
        for row in rows:
            if isinstance(row, dict):
                day = str(row.get("created", ""))[:10]
                by_day.setdefault(day, []).append(row)
        if not by_day:
            return [], datetime.now(timezone.utc)
        latest_day = max(by_day)
        asof = _parse_datetime(
            by_day[latest_day][0].get("created"), datetime.now(timezone.utc)
        )
        return by_day[latest_day], asof

    # -- OptionsDataProvider -------------------------------------------
    def get_expiries(self, underlying: str) -> list[date]:
        under = underlying.strip().upper()
        payload = self._get_json(
            "/v3/option/list/expirations", {"symbol": under, "format": "json"}
        )
        entries = payload if isinstance(payload, list) else payload.get("data", [])
        expiries: list[date] = []
        for entry in entries:
            value = entry.get("expiration", entry) if isinstance(entry, dict) else entry
            parsed = _parse_date(value)
            if parsed is not None:
                expiries.append(parsed)
        return sorted(expiries)

    def get_chain(self, underlying: str, expiry: date) -> RawChain:
        under = underlying.strip().upper()
        rows, asof = self._latest_eod_rows(under, expiry)
        calls: list[OptionQuote] = []
        puts: list[OptionQuote] = []
        for row in rows:
            quote = self._row_to_quote(row, under, expiry, asof)
            if quote is None:
                continue
            (calls if quote.contract.is_call else puts).append(quote)
        if not calls and not puts:
            raise ExpiryNotFoundError(
                f"no {under} EOD chain for expiry {expiry} "
                f"(free tier covers EOD from 2023-06-01; the terminal may also be mid-sync)"
            )
        calls.sort(key=lambda q: q.contract.strike)
        puts.sort(key=lambda q: q.contract.strike)
        return RawChain(
            underlying=under, expiry=expiry, asof=asof, calls=tuple(calls), puts=tuple(puts)
        )

    def get_underlying_price(self, underlying: str) -> float:
        under = underlying.strip().upper()
        start, end = self._window(5)
        payload = self._get_json(
            "/v3/stock/history/eod",
            {"symbol": under, "start_date": start, "end_date": end, "format": "json"},
        )
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        closes = [_num(r.get("close")) for r in rows if isinstance(r, dict)]
        closes = [c for c in closes if c is not None]
        if not closes:
            raise ProviderError(f"ThetaData has no EOD price for {under}")
        return closes[-1]
