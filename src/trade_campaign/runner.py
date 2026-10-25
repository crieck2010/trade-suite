"""The campaign day: replay -> (maybe) rebalance -> record -> digest.

One call = one live session.  The strategy is rebuilt from the close
history every run (it is deterministic), the incubation program advances
by exactly one day per run that sees a new trading session, and any
rebalance goes through the broker adapter — which means through the
trade-safety kernel configured on that adapter.  The runner itself never
touches a broker API beyond the adapter's ``get_account`` /
``get_positions`` / ``place_order`` surface.

Paper-only: the campaign config refuses any env but SIMULATE, and the
broker handed in must be a SIMULATE adapter (or a test double).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from trade_incubate.digest import build_digest, render_digest
from trade_incubate.drift import compare
from trade_incubate.ledger import IncubationLedger
from trade_incubate.presets import get_preset
from trade_incubate.program import IncubationProgram
from trade_strategies.regcond_1 import RegCond1

from .config import CampaignConfig
from .state import CampaignState

_START_EQUITY_FALLBACK = 100_000.0


def _program_from_state(cfg: CampaignConfig, state: CampaignState
                        ) -> IncubationProgram:
    prog = IncubationProgram(
        strategy_name=cfg.strategy_id,
        backtest=dict(cfg.backtest),
        config=get_preset(cfg.incubation_preset),
    )
    prog.day = state.program_day
    prog.state = state.program_state
    prog.kill_trips = list(state.kill_trips)
    prog.drift_worst = state.drift_worst
    return prog


def _sync_state(cfg: CampaignConfig, state: CampaignState,
                prog: IncubationProgram) -> None:
    state.program_day = prog.day
    state.program_state = prog.state
    state.kill_trips = prog.kill_trips
    state.drift_worst = prog.drift_worst


def _signal_targets(signals) -> dict[str, float]:
    """REGCOND-1's documented extension: LONG strength = target weight,
    EXIT = target weight 0."""
    targets: dict[str, float] = {}
    for sig in signals:
        action = getattr(sig.action, "name", str(sig.action))
        targets[sig.symbol] = float(sig.strength or 0.0) \
            if action == "LONG" else 0.0
    return targets


def _replay(cfg: CampaignConfig, closes: dict, through: date):
    """Feed the strategy every close up to ``through``.

    Returns (strategy, [(date, signals), ...] for signal days,
    [all fed dates ascending])."""
    strat = RegCond1(list(cfg.symbols))
    by_symbol = {s: dict(series) for s, series in closes.items()}
    all_dates = sorted({d for series in closes.values()
                        for d, _ in series if d <= through})
    signal_days: list[tuple[date, list]] = []
    for d in all_dates:
        bars = {s: {"close": by_symbol[s][d]}
                for s in cfg.symbols if d in by_symbol[s]}
        signals = strat.on_bar(datetime(d.year, d.month, d.day), bars)
        if signals:
            signal_days.append((d, signals))
    return strat, signal_days, all_dates


def _append_fills(cfg: CampaignConfig, fills: list[dict]) -> None:
    if not fills:
        return
    with open(cfg.fills_path, "a", encoding="utf-8") as fh:
        for f in fills:
            fh.write(json.dumps(f, default=str) + "\n")


def run_campaign_day(cfg: CampaignConfig, broker, closes: dict, *,
                     today: date | None = None,
                     safety_kernel=None,
                     dry_run: bool = False) -> dict:
    """Run one campaign session.  Returns a plain-data summary.

    ``broker`` is anything with the adapter's get_account / get_positions
    / place_order surface.  ``closes`` is ``{symbol: [(date, close)]}``
    (see trade_campaign.data.fetch_closes).  ``safety_kernel``, when
    given (the real adapter exposes it as ``adapter.safety``), is used
    for the session pre-flight.  ``dry_run`` computes and records the
    rebalance as *would-be* orders without submitting anything.
    """
    cfg.ensure_dirs()
    today = today or date.today()
    state = CampaignState.load(cfg.state_path)
    if state.started_on is None:
        state.started_on = today.isoformat()
    ledger = IncubationLedger(str(cfg.ledger_path))
    prog = _program_from_state(cfg, state)
    notes: list[str] = []

    strat, signal_days, all_dates = _replay(cfg, closes, today)
    fed = date.fromisoformat(state.fed_through) if state.fed_through \
        else None
    new_dates = [d for d in all_dates if fed is None or d > fed]
    if not new_dates:
        return {"status": "already_current", "strategy": cfg.strategy_id,
                "program_day": prog.day, "notes": ["no new sessions"]}

    # ---- pre-flight ----------------------------------------------------
    if safety_kernel is not None:
        from trade_safety import AccountSnapshot, run_preflight
        account = broker.get_account()
        snapshot = AccountSnapshot(
            account_id=str(getattr(account, "account_id", "") or ""),
            equity=float(account.equity),
            buying_power=float(getattr(account, "buying_power", 0.0)
                               or 0.0),
            maintenance_margin=float(
                getattr(account, "margin_used", 0.0) or 0.0))
        report = run_preflight(
            env=cfg.env, connected=broker.is_connected(),
            account=snapshot, kernel=safety_kernel,
            config=safety_kernel.config)
        if not report.passed:
            failures = [f"{name}: {detail}" for name, ok, detail
                        in report.checks if not ok]
            return {"status": "preflight_failed",
                    "strategy": cfg.strategy_id,
                    "program_day": prog.day,
                    "failures": failures, "notes": notes}
        notes.append("preflight: ok")

    # ---- incubation day --------------------------------------------------
    stage = prog.advance()
    if len(new_dates) > 1:
        notes.append(
            f"catch-up: {len(new_dates)} sessions fed, counted as one "
            "live campaign day")

    account = broker.get_account()
    equity = float(account.equity)
    positions = {p.symbol: p for p in broker.get_positions()
                 if float(p.quantity) > 0}
    label = strat.label_history.get(all_dates[-1], "?")
    notes.append(f"regime label as of {all_dates[-1]}: {label}")

    # ---- rebalance? ------------------------------------------------------
    last_acted = date.fromisoformat(state.last_acted) \
        if state.last_acted else None
    candidate = None
    for d, signals in signal_days:
        if last_acted is None or d > last_acted:
            candidate = (d, signals)  # keep the newest unacted set
    orders: list[dict] = []
    fills: list[dict] = []
    closed_today: list[dict] = []
    acted = False
    if candidate is not None and prog.state != "PAUSED":
        sig_date, signals = candidate
        prior = [d for d in strat.label_history if d < sig_date]
        decision_label = strat.label_history[max(prior)] if prior else "?"
        notes.append(
            f"rebalance decision label (as of prior month-end): "
            f"{decision_label}")
        targets = _signal_targets(signals)
        mult = prog.size_multiplier()
        band = cfg.limit_band_bps / 10_000.0
        latest_close = {s: series[-1][1] for s, series in closes.items()
                        if series}
        specs: list[dict] = []
        for sym in cfg.symbols:
            weight = targets.get(sym)
            if weight is None:
                continue
            ref = latest_close[sym]
            target_qty = int(equity * (weight * mult) / ref)
            current = int(float(positions[sym].quantity)) \
                if sym in positions else 0
            delta = target_qty - current
            if delta == 0:
                continue
            if target_qty == 0:
                delta = -current  # full exit always executes
            elif abs(delta) * ref < cfg.min_order_notional and current > 0:
                notes.append(f"{sym}: delta ${abs(delta) * ref:,.0f} "
                             "below dust threshold, skipped")
                continue
            specs.append({"symbol": sym, "delta": delta, "ref": ref})
        # Sells first: they free the cash the buys need.
        specs.sort(key=lambda s: 0 if s["delta"] < 0 else 1)
        from trade_execution.models import OrderAction, OrderPayload, \
            OrderType
        for spec in specs:
            delta, sym, ref = spec["delta"], spec["symbol"], spec["ref"]
            action = OrderAction.BUY if delta > 0 else OrderAction.SELL
            limit = round(ref * (1 + band), 2) if delta > 0 \
                else round(ref * (1 - band), 2)
            order = OrderPayload(
                symbol=sym, action=action, quantity=abs(delta),
                price=limit, order_type=OrderType.LIMIT,
                strategy=cfg.strategy_name,
                client_tag=f"campaign-{sig_date.isoformat()}")
            record = {"date": today.isoformat(), "signal_date":
                      sig_date.isoformat(), "symbol": sym,
                      "action": action.value, "quantity": abs(delta),
                      "ref_price": ref, "limit_price": limit}
            if dry_run:
                record["status"] = "would_submit"
                orders.append(record)
                continue
            try:
                result = broker.place_order(order)
            except Exception as exc:  # kernel blocks land here
                record["status"] = "blocked_or_error"
                record["error"] = f"{type(exc).__name__}: {exc}"
                orders.append(record)
                fills.append(record)
                continue
            record["status"] = result.status.value
            record["order_id"] = result.order_id
            record["filled_qty"] = result.filled_qty
            record["avg_fill_price"] = result.avg_price
            orders.append(record)
            fills.append(record)
            if result.success and result.filled_qty > 0:
                closed = state.apply_fill(
                    sym, action.value, float(result.filled_qty),
                    float(result.avg_price or ref), today)
                if closed:
                    closed_today.append(closed)
        acted = bool(orders) and all(
            o["status"] not in ("blocked_or_error",) for o in orders)
        if not dry_run and acted:
            state.last_acted = sig_date.isoformat()
        notes.append(
            f"rebalance (signal {sig_date}, size x{mult}): "
            f"{len(orders)} orders")
    elif candidate is not None:
        notes.append("rebalance due but program is PAUSED — no orders")

    # ---- mark, drift, verdict ---------------------------------------------
    account = broker.get_account()
    equity = float(account.equity)
    positions_list = [
        {"symbol": p.symbol, "qty": float(p.quantity),
         "unrealized": float(p.unrealized_pnl)}
        for p in broker.get_positions() if float(p.quantity) > 0
    ]
    eq_curve = ledger.equity_curve() + [equity]
    drift = compare(cfg.expected, eq_curve, state.closed_trades)
    paper = drift["paper"]
    sharpe = paper.get("sharpe")
    verdict = prog.evaluate(
        {"sharpe": sharpe if isinstance(sharpe, (int, float)) else 0.0,
         "max_drawdown": paper.get("max_drawdown", 0.0),
         "n_trades": paper.get("n_trades", 0)},
        drift["verdict"], None)

    prev_equity = ledger.last()["equity"] if ledger.last() else equity
    day_record = {
        "date": today.isoformat(), "day": prog.day, "stage": stage,
        "strategy": cfg.strategy_id, "equity": round(equity, 2),
        "positions": positions_list, "regime_conviction": None,
        "regime_label": label, "trades": closed_today,
        "drift": drift["verdict"], "orders": orders, "fills": fills,
        "verdict": verdict, "notes": notes,
        "dry_run": dry_run,
    }
    ledger.record_day(day_record)
    _append_fills(cfg, fills)
    state.fed_through = all_dates[-1].isoformat()
    _sync_state(cfg, state, prog)
    state.save(cfg.state_path)

    # ---- digest -------------------------------------------------------------
    start_equity = (ledger.days()[0]["equity"] if ledger.days()
                    else _START_EQUITY_FALLBACK)
    digest = build_digest(
        strategy=cfg.strategy_id, day=prog.day,
        stage=verdict["stage"], equity=equity,
        start_equity=start_equity, day_pnl=equity - prev_equity,
        positions=positions_list, conviction=None,
        drift=drift["verdict"], pending_approvals=0,
        paused=verdict.get("paused", False),
        kill_trips=verdict.get("kill_trips_today", []))
    text = render_digest(digest)
    text += (f"\nregime label: {label}   closed trades: "
             f"{len(state.closed_trades)}/20   "
             f"orders today: {len(orders)}")
    if dry_run:
        text += "\nDRY RUN — orders computed, none submitted."
    digest_path = cfg.digest_dir / f"{today.isoformat()}.md"
    digest_path.write_text(text + "\n", encoding="utf-8")

    return {"status": "ok", "strategy": cfg.strategy_id,
            "program_day": prog.day, "stage": verdict["stage"],
            "equity": equity, "orders": orders, "fills": fills,
            "drift": drift["verdict"], "paused": verdict.get("paused"),
            "digest": text, "digest_path": str(digest_path),
            "notes": notes}
