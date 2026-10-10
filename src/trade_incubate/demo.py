"""Seeded 63-day paper run: the full incubation arc, deterministic.

Days 1-40 the strategy tracks its backtest expectations.  From day 41 a
planted degradation (win rate collapses, returns turn negative) pushes the
drift detector WATCH -> VIOLATION, and the kill condition pauses the
program.  The digest shows the whole arc.

This is the quarter, compressed: it exercises program stages, drift
detection, kill conditions, the ledger, and the digest end to end.
"""

from __future__ import annotations

import random

from .digest import build_digest, render_digest
from .drift import compare
from .ledger import IncubationLedger
from .program import IncubationProgram, ProgramConfig

EXPECTATIONS = {
    "sharpe": 1.2,
    "win_rate": 0.45,
    "payoff": 1.6,
    "max_drawdown": 0.06,
    "trades_per_day": 0.9,
    "n_trades": 680,  # backtest sample size (for reference, not the bands)
}


def _phase1_day(rng: random.Random, equity: float, trades: list) -> tuple[float, list]:
    """Healthy day: tracks expectations."""
    ret = rng.gauss(0.0008, 0.011)
    new_trades = []
    if rng.random() < 0.9:
        win = rng.random() < 0.45
        pnl = 240.0 if win else -150.0
        new_trades.append({"pnl": pnl})
        equity += pnl
    return equity * (1.0 + ret), new_trades


def _phase2_day(rng: random.Random, equity: float, trades: list) -> tuple[float, list]:
    """Degraded day: edge gone — win rate collapses, drift turns negative."""
    ret = rng.gauss(-0.0012, 0.014)
    new_trades = []
    if rng.random() < 0.9:
        win = rng.random() < 0.25
        pnl = 180.0 if win else -210.0
        new_trades.append({"pnl": pnl})
        equity += pnl
    return equity * (1.0 + ret), new_trades


def run_demo(seed: int = 7, start_equity: float = 100_000.0,
             config: ProgramConfig | None = None) -> dict:
    """Run the seeded 63-day incubation.  Returns the full arc."""
    rng = random.Random(seed)
    program = IncubationProgram(strategy_name="swing-trend",
                                backtest={"sharpe": EXPECTATIONS["sharpe"],
                                          "max_drawdown": EXPECTATIONS["max_drawdown"],
                                          "n_trades": 500},
                                config=config or ProgramConfig())
    ledger = IncubationLedger()
    equity = start_equity
    drift_history: list[str] = []
    paused_day: int | None = None
    equity_curve = [start_equity]
    all_trades: list[dict] = []

    for day in range(1, 64):
        program.advance()
        if program.state == "PAUSED":
            break
        phase = _phase1_day if day <= 40 else _phase2_day
        equity, new_trades = phase(rng, equity, all_trades)
        all_trades.extend(new_trades)
        equity_curve.append(equity)

        drift = compare(EXPECTATIONS, equity_curve, all_trades)
        drift_history.append(drift["verdict"])
        paper = drift["paper"]
        verdict = program.evaluate(
            {"sharpe": paper["sharpe"], "max_drawdown": paper["max_drawdown"],
             "n_trades": paper["n_trades"]},
            drift["verdict"], conviction=55.0)

        prev = ledger.last()["equity"] if ledger.last() else start_equity
        ledger.record_day({
            "date": f"day-{day:03d}", "day": day, "stage": program.state,
            "equity": round(equity, 2), "positions": [],
            "regime_conviction": 55.0, "trades": new_trades,
            "drift": drift["verdict"], "verdict": verdict,
        })
        if verdict["paused"] and paused_day is None:
            paused_day = day

    last = ledger.last()
    digest = build_digest(
        strategy="swing-trend", day=program.day, stage=program.state,
        equity=equity, start_equity=start_equity,
        day_pnl=equity - (ledger.days()[-2]["equity"] if len(ledger.days()) > 1
                          else start_equity),
        positions=[], conviction=55.0, drift=last["drift"] if last else "OK",
        pending_approvals=0, paused=program.state == "PAUSED",
        kill_trips=program.kill_trips)
    return {
        "seed": seed,
        "days_run": program.day,
        "paused": program.state == "PAUSED",
        "paused_day": paused_day,
        "final_stage": program.state,
        "final_equity": round(equity, 2),
        "drift_history": drift_history,
        "kill_trips": program.kill_trips,
        "n_trades": len(all_trades),
        "digest_text": render_digest(digest),
        "expectations": EXPECTATIONS,
    }


if __name__ == "__main__":  # pragma: no cover
    arc = run_demo()
    print(f"days run: {arc['days_run']}, paused: {arc['paused']} "
          f"(day {arc['paused_day']})")
    print(f"drift arc: {' -> '.join(arc['drift_history'][39:])}")
    print()
    print(arc["digest_text"])
