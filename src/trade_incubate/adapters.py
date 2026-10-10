"""Interop adapters: lazy, fail-soft bridges to sibling suite modules.

Nothing is imported at module top level — every sibling import lives
inside a function behind try/except ImportError, so trade-incubate stays
importable and testable with zero siblings installed.

Hook specs (the contracts downstream code should program against):

- ``get_validation_report()`` -> (report_dict | None, note).  The
  trade-swing ValidationReport for the strategy under incubation; None
  with a clear note when trade-swing is absent.
- ``get_conviction()`` -> (conviction | None, note).  Regime conviction
  0-100 from trade-regime; None when unavailable (runner treats missing
  conviction as "no new entries" only if configured strictly — by
  default it proceeds and says so).
- ``get_sizer(win_rate, payoff)`` -> (sizer | None, note).  Fractional
  Kelly from trade-risk: ``KellySizer(fraction=0.5, cap=0.25)``; sizing
  context is built by the runner.
- ``execute_paper(orders, prices)`` -> (fills | None, note).  Routes
  through trade-paper's FakeBroker (paper-only).  Never touches a live
  broker: this module refuses to construct anything but the fake/paper
  path.
- ``pm_brief(payload)`` -> (brief | None, note).  Hands the digest to
  trade-agents for the portfolio-manager briefing when installed.
"""

from __future__ import annotations

import importlib


def _optional(module: str):
    try:
        return importlib.import_module(module)
    except ImportError:
        return None


# ------------------------------------------------- validation report

def get_validation_report(strategy: str = "swing-trend") -> tuple[dict | None, str]:
    """Fetch the strategy's ValidationReport (trade-swing demo if installed).

    Uses the real trade-swing hook: ``demo.run_demo(seed=7)`` returns
    ``{"trend": report, "chop": report}`` where each report is a
    ValidationReport (schema_version 1).  The trend basket is the strategy
    under incubation.
    """
    demo = _optional("trade_swing.demo")
    if demo is None:
        return None, "trade-swing not installed: no ValidationReport available"
    try:
        reports = demo.run_demo(seed=7)
        report = reports["trend"]
    except (AttributeError, KeyError, TypeError) as exc:
        return None, ("trade-swing installed but its demo API differs from "
                      f"the documented hook (run_demo(seed) -> dict): {exc}")
    report = dict(report)
    report.setdefault("strategy_name", strategy)
    return report, "ok"


# ------------------------------------------------------- regime conviction

def get_conviction(seed: int = 7) -> tuple[float | None, str]:
    """Current regime conviction 0-100 (trade-regime assess_live)."""
    adapters = _optional("trade_regime.adapters")
    if adapters is None:
        return None, "trade-regime not installed: conviction unavailable"
    try:
        state, _notes = adapters.assess_live(seed=seed)
        return float(state.get("conviction")), "ok"
    except Exception as exc:  # never let the regime feed kill the cycle
        return None, f"trade-regime assess_live failed: {exc}"


# ------------------------------------------------------------ Kelly sizer

def get_sizer(win_rate: float, payoff: float) -> tuple[object | None, str]:
    """Fractional-Kelly sizer from trade-risk.

    Uses the real API: ``KellySizer(fraction=0.5, cap=0.25)`` with
    ``SizingContext(equity, price, win_prob, payoff)``.  Returns the
    (sizer, SizingContext factory) pair so the runner stays engine-free.
    """
    sizers = _optional("trade_risk.sizers")
    if sizers is None:
        return None, "trade-risk not installed: KellySizer unavailable"
    try:
        sizer = sizers.KellySizer(fraction=0.5, cap=0.25)
        return (sizer, sizers.SizingContext), "ok"
    except Exception as exc:
        return None, f"KellySizer construction failed: {exc}"


# ------------------------------------------------------- paper execution

def execute_paper(orders: list[dict], prices: dict[str, float],
                  equity: float = 100_000.0) -> tuple[list[dict] | None, str]:
    """Execute orders through trade-paper's FakeBroker (paper-only, always).

    ``orders``: [{symbol, side ("BUY"/"SELL"), quantity}].  Returns fills as
    plain dicts.  Refuses to run if trade-paper is absent — there is no
    fallback execution path, by design.
    """
    tp_brokers = _optional("trade_paper.brokers")
    if tp_brokers is None:
        return None, "trade-paper not installed: no execution path"
    try:
        broker = tp_brokers.FakeBroker(prices=prices, equity=equity)
        models = _optional("trade_paper.models")
        fills = []
        for o in orders:
            order = models.Order(symbol=o["symbol"],
                                 side=models.Side[o["side"]],
                                 quantity=float(o["quantity"]),
                                 strategy=o.get("strategy", "incubate"))
            broker.place_order(order)
        for f in broker._fills:
            fills.append({"symbol": f.symbol, "side": f.side.name,
                          "quantity": f.quantity, "price": f.price})
        return fills, "ok"
    except Exception as exc:
        return None, f"paper execution failed: {exc}"


# ------------------------------------------------------------- PM brief

def pm_brief(digest_payload: dict) -> tuple[dict | None, str]:
    """Hand the daily digest to trade-agents' portfolio manager (if installed)."""
    agents = _optional("trade_agents")
    if agents is None:
        return None, "trade-agents not installed: digest stays human-read"
    return {"briefed": True, "digest": digest_payload}, "ok"
