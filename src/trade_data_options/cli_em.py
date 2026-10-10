"""CLI: print the expected move for a symbol and expiry.

``trade-data-options-em SYMBOL [--expiry YYYY-MM-DD] [--json]``

Reads the chain through any configured provider (yfinance by default) and
prints the ATM straddle price with ±1 and ±2 bands. The data-delay label
is always shown: free vendor data is delayed, and a delayed quote is not
a trading signal. No scheduling, no posting, no orders -- this command
only reads and prints.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime, timezone

from .exceptions import NoUsableQuoteError, OptionsDataError
from .expected_move import ExpectedMove, expected_move_for_expiry


def _default_expiry(provider, underlying: str) -> date:
    today = datetime.now(timezone.utc).date()
    expiries = provider.get_expiries(underlying)
    future = [e for e in expiries if e >= today]
    if not future:
        raise OptionsDataError(f"no listed expiries at or after {today} for {underlying}")
    return future[0]


def _provider():
    from .providers.yfinance import YFinanceOptionsProvider

    return YFinanceOptionsProvider()


def _fmt_money(value: float) -> str:
    return f"{value:,.2f}"


def _render_text(em: ExpectedMove, spot: float, delay_label: str) -> str:
    lines = [
        f"{em.underlying} — Expected Move to {em.expiry.isoformat()}",
        f"Current price: {_fmt_money(spot)} (data: {delay_label})",
        f"EM: {_fmt_money(em.em_points)} ({em.em_pct * 100:.2f}%)",
        f"  1x Low  {_fmt_money(em.band_1_low):>12} | 1x High  {_fmt_money(em.band_1_high)}",
        f"  2x Low  {_fmt_money(em.band_2_low):>12} | 2x High  {_fmt_money(em.band_2_high)}",
        f"ATM strike: {_fmt_money(em.atm_strike)} | "
        f"call {_fmt_money(em.call_price)} + put {_fmt_money(em.put_price)} "
        f"({em.price_source}) | as of {em.as_of.isoformat()}",
    ]
    return "\n".join(lines)


def _render_json(em: ExpectedMove, spot: float) -> str:
    payload = asdict(em)
    payload["expiry"] = em.expiry.isoformat()
    payload["as_of"] = em.as_of.isoformat()
    payload["underlying_price"] = spot
    return json.dumps(payload, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trade-data-options-em",
        description="Print the market-implied expected move (ATM straddle) for a symbol.",
    )
    parser.add_argument("symbol", help="Underlying ticker, e.g. SPY")
    parser.add_argument("--expiry", help="Expiry YYYY-MM-DD (default: nearest listed)")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    try:
        provider = _provider()
    except OptionsDataError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    symbol = args.symbol.strip().upper()
    try:
        expiry = date.fromisoformat(args.expiry) if args.expiry else _default_expiry(provider, symbol)
        em = expected_move_for_expiry(provider, symbol, expiry)
        spot = provider.get_underlying_price(symbol)
    except (OptionsDataError, NoUsableQuoteError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    delay = provider.delay_minutes
    delay_label = f"delayed ~{delay} min" if delay else "real-time"
    if args.json:
        print(_render_json(em, spot))
    else:
        print(_render_text(em, spot, delay_label))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
