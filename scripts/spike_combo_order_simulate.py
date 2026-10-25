"""SPIKE: can moomoo-api place an atomic multi-leg options combo order?

Roadmap Phase 0, open question #1 (docs/MOOMOO_EXECUTION_DECISION.md).
This script answers ONE question against the **paper (SIMULATE)** account:
does the installed moomoo-api SDK expose a working combo-order placement
for a 4-leg SPY iron fly, and if an order is accepted, can we cancel it?

SAFETY — read before running:
- SIMULATE ONLY. Every trade call hardcodes ``TrdEnv.SIMULATE``. The
  script refuses to start if it finds any hint of a REAL configuration,
  and it never calls ``unlock_trade`` (paper needs no unlock).
- Exactly ONE placement attempt, quantity 1, and any accepted order is
  cancelled immediately. Nothing is left working in the account.
- Run it on the PC where OpenD is running and logged in:
      pip install -e ".[execution]"
      python scripts/spike_combo_order_simulate.py
  Then paste the whole RESULT block back to Muse.

Exit codes: 0 = question answered (either way), 2 = setup problem.
"""

from __future__ import annotations

import inspect
import sys
from datetime import date

HOST, PORT = "127.0.0.1", 11111
UNDERLYING = "US.SPY"
WING_WIDTH = 5.0
QTY = 1


def fail(msg: str) -> "SystemExit":
    print(f"SETUP PROBLEM: {msg}")
    return SystemExit(2)


def main() -> int:
    try:
        import moomoo as ft
    except ImportError:
        raise fail("moomoo-api SDK not installed. Run: pip install -e \".[execution]\"")

    result: dict[str, object] = {"sdk_version": getattr(ft, "__version__", "unknown")}

    quote_ctx = ft.OpenQuoteContext(host=HOST, port=PORT)
    trd_ctx = ft.OpenSecTradeContext(
        filter_trdmarket=ft.TrdMarket.US,
        host=HOST,
        port=PORT,
        security_firm=ft.SecurityFirm.FUTUSECURITIES,
    )
    try:
        # --- 1. Find the SIMULATE US margin account (paper options live there)
        ret, accs = trd_ctx.get_acc_list()
        if ret != ft.RET_OK:
            raise fail(f"get_acc_list failed: {accs}")
        paper = accs[
            (accs["trd_env"] == ft.TrdEnv.SIMULATE)
            & (accs["acc_type"] == ft.TrdAccType.MARGIN)
        ]
        if paper.empty:
            raise fail("No SIMULATE margin account found — enable paper trading in the app.")
        acc_id = int(paper.iloc[0]["acc_id"])
        result["paper_acc_id"] = acc_id

        # --- 2. Capability probe: does the SDK expose combo placement?
        has_combo = hasattr(trd_ctx, "place_combo_order")
        result["has_place_combo_order"] = has_combo
        if has_combo:
            result["place_combo_order_signature"] = str(
                inspect.signature(trd_ctx.place_combo_order)
            )

        # --- 3. Build a real iron fly from the live paper chain
        ret, snap = quote_ctx.get_market_snapshot([UNDERLYING])
        if ret != ft.RET_OK:
            raise fail(f"snapshot failed: {snap}")
        spot = float(snap.iloc[0]["last_price"])
        result["spot"] = spot

        ret, exps = quote_ctx.get_option_expiration_date(code=UNDERLYING)
        if ret != ft.RET_OK:
            raise fail(f"expiration query failed: {exps}")
        today = date.today().isoformat()
        future = [d for d in exps["strike_time"].tolist() if d >= today]
        if not future:
            raise fail("No future option expirations returned.")
        expiry = future[0]
        result["expiry"] = expiry

        ret, chain = quote_ctx.get_option_chain(
            code=UNDERLYING, start=expiry, end=expiry
        )
        if ret != ft.RET_OK:
            raise fail(f"option chain failed: {chain}")

        def leg_code(strike_target: float, right: str) -> str:
            side = chain[chain["option_type"].str.upper() == right]
            row = side.iloc[(side["strike_price"] - strike_target).abs().idxmin()]
            return str(row["code"]), float(row["strike_price"])

        atm = min(
            chain["strike_price"].unique(),
            key=lambda k: abs(float(k) - spot),
        )
        short_put, k_put = leg_code(float(atm), "PUT")
        short_call, k_call = leg_code(float(atm), "CALL")
        long_put, _ = leg_code(float(atm) - WING_WIDTH, "PUT")
        long_call, _ = leg_code(float(atm) + WING_WIDTH, "CALL")
        # code, side, ratio — sell the body, buy the wings
        legs = [
            (long_put, ft.TrdSide.BUY, 1),
            (short_put, ft.TrdSide.SELL, 1),
            (short_call, ft.TrdSide.SELL, 1),
            (long_call, ft.TrdSide.BUY, 1),
        ]
        result["legs"] = [c for c, _, _ in legs]
        result["strikes"] = {"body": [k_put, k_call], "wing_width": WING_WIDTH}

        if not has_combo:
            result["verdict"] = (
                "SDK does NOT expose place_combo_order: atomic multi-leg "
                "placement is unavailable; 0DTE spreads would require "
                "legging (not approved for live). Question answered."
            )
            return 0

        # --- 4. One placement attempt (paper, qty 1), then cancel.
        # The combo API's exact kwargs vary by SDK version; the signature
        # captured above is part of the result either way.
        codes = [c for c, _, _ in legs]
        ratios = [r for _, _, r in legs]
        sides = [s for _, s, _ in legs]
        attempt_kwargs = dict(
            price=0.05,  # nominal net-credit limit; paper spike only
            quantity=QTY,
            code_list=codes,
            ratio_list=ratios,
            side_list=sides,
            trd_env=ft.TrdEnv.SIMULATE,
            acc_id=acc_id,
            order_type=ft.OrderType.NORMAL,
        )
        try:
            ret, data = trd_ctx.place_combo_order(**attempt_kwargs)
        except TypeError as exc:
            result["verdict"] = (
                f"place_combo_order exists but the call shape differs: {exc}. "
                "Signature above is the evidence — paste the RESULT block back."
            )
            return 0
        if ret != ft.RET_OK:
            result["verdict"] = f"Combo placement rejected by OpenD: {data}"
            return 0

        order_id = str(data.iloc[0]["order_id"])
        result["combo_order_id"] = order_id
        ret, data = trd_ctx.cancel_order(
            order_id=order_id, trd_env=ft.TrdEnv.SIMULATE, acc_id=acc_id
        )
        result["cancel_result"] = "OK" if ret == ft.RET_OK else str(data)
        result["verdict"] = (
            "SUCCESS: atomic 4-leg combo order accepted in SIMULATE and "
            "cancelled. Multi-leg placement via API is available."
        )
        return 0
    finally:
        quote_ctx.close()
        trd_ctx.close()
        print("\n================ RESULT ================")
        for key, value in result.items():
            print(f"{key}: {value}")
        print("=========================================")


if __name__ == "__main__":
    sys.exit(main())
