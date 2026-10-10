"""The scheduled daily cycle: regime -> signals -> size -> approve -> execute.

``run_day`` wires the suite together, every step lazy and fail-soft:

1. regime conviction (trade-regime; missing -> proceeds loudly, or blocks
   new entries when ``require_conviction`` is set)
2. strategy signals (trade-swing on the day's bars; missing -> no trading)
3. Kelly sizing (trade-risk ``KellySizer``; win_rate/payoff from the
   strategy's ValidationReport)
4. approval queue (dry-run default: records what *would* happen)
5. execution via trade-paper's FakeBroker — paper-only, never live
6. drift check vs backtest expectations, program evaluation, ledger, digest

Dry-run is the default: nothing touches any broker, real or paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import adapters
from .digest import build_digest
from .drift import compare
from .ledger import IncubationLedger
from .program import IncubationProgram


@dataclass
class DayConfig:
    strategy: str = "swing-trend"
    dry_run: bool = True
    start_equity: float = 100_000.0
    seed: int = 7
    require_conviction: bool = False   # True: missing conviction blocks entries
    kelly_fraction: float = 0.5
    kelly_cap: float = 0.25
    symbols: list = field(default_factory=lambda: ["TREND_A", "TREND_B"])


def _demo_bars(symbols: list[str], seed: int) -> tuple[dict | None, str]:
    try:
        import importlib
        demo = importlib.import_module("trade_swing.demo")
        return demo.demo_bars(seed=seed, n_days=400), "ok"
    except ImportError:
        return None, "trade-swing not installed: no bars for signals"
    except Exception as exc:
        return None, f"demo bars failed: {exc}"


def _latest_entries(bars_by_symbol: dict, conviction: float | None,
                    min_conviction: float) -> tuple[list[dict], str]:
    """Latest entry signals per symbol, regime-gated.  Lazy trade-swing."""
    try:
        import importlib
        strat = importlib.import_module("trade_swing.strategy")
    except ImportError:
        return [], "trade-swing not installed: signals unavailable"
    entries = []
    for symbol, bars in bars_by_symbol.items():
        try:
            sigs = strat.generate_signals(bars)
        except Exception:
            continue
        if not sigs:
            continue
        last = sigs[-1]
        gated = (conviction is not None and conviction < min_conviction)
        if last.get("signal") == "enter_long" and not gated:
            entries.append({"symbol": symbol, "price": bars[-1]["close"],
                            "atr": last.get("atr")})
    note = (f"{len(entries)} entries"
            + (" (regime-gated)" if conviction is not None
               and conviction < min_conviction else ""))
    return entries, note


def run_day(program: IncubationProgram, ledger: IncubationLedger,
            cfg: DayConfig, *, day_override: int | None = None) -> dict:
    """Run one incubation day.  Returns a plain-data day summary."""
    notes: list[str] = []
    stage = program.advance()
    day = program.day if day_override is None else day_override

    # 1. regime conviction -------------------------------------------
    conviction, note = adapters.get_conviction(seed=cfg.seed)
    notes.append(f"conviction: {note}")
    entries_blocked_by_conviction = (
        conviction is not None and conviction < program.config.regime_min_conviction
    ) or (conviction is None and cfg.require_conviction)

    # 2. validation expectations --------------------------------------
    report, note = adapters.get_validation_report(cfg.strategy)
    notes.append(f"validation: {note}")
    metrics = (report or {}).get("backtest", {}).get("metrics", {}) if report else {}
    win_rate = float(metrics.get("win_rate") or 0.45)
    avg_win = float(metrics.get("avg_win") or 1.0)
    avg_loss = abs(float(metrics.get("avg_loss") or 1.0)) or 1.0
    payoff = avg_win / avg_loss

    # 3. signals + Kelly sizing ---------------------------------------
    bars, note = _demo_bars(cfg.symbols, cfg.seed)
    notes.append(f"bars: {note}")
    entries, note = (_latest_entries(bars, conviction,
                                     program.config.regime_min_conviction)
                     if bars else ([], "no bars"))
    notes.append(f"signals: {note}")
    if entries_blocked_by_conviction:
        entries = []
        notes.append("entries blocked: regime conviction below minimum")

    sizer_info, note = adapters.get_sizer(win_rate, payoff)
    notes.append(f"sizer: {note}")
    equity = ledger.last()["equity"] if ledger.last() else cfg.start_equity
    orders, would_be = [], []
    size_mult = program.size_multiplier()
    for e in entries:
        qty = 0.0
        if sizer_info is not None:
            sizer, ctx_factory = sizer_info
            ctx = ctx_factory(equity=equity, price=e["price"],
                              win_prob=win_rate, payoff=payoff)
            qty = sizer.quantity(ctx) * size_mult
        spec = {"symbol": e["symbol"], "side": "BUY",
                "quantity": round(qty, 4), "strategy": cfg.strategy}
        (would_be if cfg.dry_run else orders).append(spec)

    # 4-5. approval + execution ----------------------------------------
    fills: list[dict] = []
    if cfg.dry_run:
        notes.append(f"dry-run: {len(would_be)} orders recorded, none sent")
    elif orders:
        prices = {e["symbol"]: e["price"] for e in entries}
        fills, note = adapters.execute_paper(orders, prices, equity)
        notes.append(f"execution: {note}")
        fills = fills or []

    # 6. drift, evaluation, ledger, digest -----------------------------
    eq_curve = ledger.equity_curve() + [equity]
    trades = ledger.closed_trades()
    expected = {
        "sharpe": float(metrics.get("sharpe", metrics.get("sharpe_ratio", 0.0)) or 0.0),
        "win_rate": win_rate,
        "payoff": payoff,
        "max_drawdown": abs(float(metrics.get("max_drawdown", 0.05))),
        "trades_per_day": (float(metrics.get("n_trades", 50)) / 750.0
                           if metrics.get("n_trades") else 0.07),
    }
    drift = compare(expected, eq_curve, trades)
    verdict = program.evaluate(
        {"sharpe": drift["paper"]["sharpe"],
         "max_drawdown": drift["paper"]["max_drawdown"],
         "n_trades": drift["paper"]["n_trades"]},
        drift["verdict"], conviction,
        force_block_entries=entries_blocked_by_conviction)

    prev_equity = ledger.last()["equity"] if ledger.last() else cfg.start_equity
    day_record = {
        "date": f"day-{day:03d}", "day": day, "stage": stage,
        "equity": round(equity, 2),
        "positions": [],  # single-day runner: positions tracked by trade-paper
        "regime_conviction": conviction,
        "trades": [],     # closed trades appended by the caller/broker fills
        "drift": drift["verdict"],
        "orders": would_be if cfg.dry_run else orders,
        "fills": fills,
        "verdict": verdict,
        "notes": notes,
    }
    ledger.record_day(day_record)
    digest = build_digest(
        strategy=cfg.strategy, day=day, stage=verdict["stage"],
        equity=equity, start_equity=cfg.start_equity,
        day_pnl=equity - prev_equity, positions=[],
        conviction=conviction, drift=drift["verdict"],
        pending_approvals=len(would_be) + len(orders),
        paused=verdict["paused"], kill_trips=verdict["kill_trips_today"])
    return {"day": day, "stage": stage, "verdict": verdict,
            "drift": drift["verdict"], "digest": digest,
            "dry_run": cfg.dry_run, "notes": notes}
