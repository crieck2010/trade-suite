"""Paper-trading tab backend: thin wrapper over the ``trade-paper`` engine.

Everything is lazy: the dashboard works without trade-paper installed, and
the Paper tab reports a clear install hint instead.
"""

from __future__ import annotations


def paper_available() -> tuple[bool, str]:
    try:
        import trade_paper  # noqa: F401
        return True, ""
    except ImportError:
        return False, ("trade-paper is not installed; "
                       "pip install git+https://github.com/crieck2010/trade-paper.git")


def _require():
    ok, hint = paper_available()
    if not ok:
        raise RuntimeError(hint)
    from trade_paper.brokers import make_broker
    from trade_paper.config import PaperConfig
    from trade_paper.ledger import Ledger
    return make_broker, PaperConfig, Ledger


def _load(config_path: str):
    make_broker, PaperConfig, Ledger = _require()
    cfg = PaperConfig.load(config_path or "paper-config.json")
    return cfg, make_broker(cfg), Ledger(cfg.db_path)


def paper_status(config_path: str = "") -> dict:
    cfg, broker, ledger = _load(config_path)
    try:
        acct = broker.get_account()
        positions = broker.get_positions()
        return {
            "available": True, "broker": broker.name,
            "paper_only": True,
            "equity": round(acct.equity, 2), "cash": round(acct.cash, 2),
            "buying_power": round(acct.buying_power, 2),
            "market_open": broker.is_market_open(),
            "positions": [{"symbol": p.symbol, "qty": p.quantity,
                           "avg_entry": round(p.avg_entry_price, 4),
                           "market": round(p.market_price, 4),
                           "unrealized": round(p.unrealized_pnl, 2),
                           "asset_class": p.asset_class.value}
                          for p in positions],
            "pending_approvals": len(ledger.list_approvals(status="pending")),
            "active_strategies": len(ledger.active_strategies()),
            "recent_orders": [
                {"id": o["client_order_id"], "symbol": o["symbol"],
                 "side": o["side"], "qty": o["quantity"],
                 "strategy": o["strategy"], "state": o["state"]}
                for o in ledger.list_orders(limit=25)
            ],
        }
    finally:
        ledger.close()


def paper_approvals(config_path: str = "", status: str = "pending") -> dict:
    _, _, ledger = _load(config_path)
    try:
        rows = ledger.list_approvals(status=status or None)
        return {"available": True, "approvals": [
            {"id": r["id"], "strategy": r["strategy"], "symbols": r["symbols"],
             "status": r["status"], "decided_by": r["decided_by"],
             "reason": r["reason"], "created_at": r["created_at"],
             "score": (r["metrics"].get("score")),
             "metrics": r["metrics"].get("metrics", {})}
            for r in rows]}
    finally:
        ledger.close()


def paper_approve(config_path: str, approval_id: int, reason: str = "") -> dict:
    _, _, ledger = _load(config_path)
    try:
        ledger.decide_approval(approval_id, True, decided_by="user", reason=reason)
        return {"available": True, "approved": approval_id}
    finally:
        ledger.close()


def paper_fidelity(config_path: str = "") -> dict:
    _require()
    from trade_paper import fidelity as fmod
    from trade_paper.config import PaperConfig
    from trade_paper.ledger import Ledger
    cfg = PaperConfig.load(config_path or "paper-config.json")
    ledger = Ledger(cfg.db_path)
    try:
        out = fmod.report(ledger, cfg.assumed_slippage_bps)
        out["available"] = True
        return out
    finally:
        ledger.close()
