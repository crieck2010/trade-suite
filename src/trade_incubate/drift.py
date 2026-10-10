"""Model-drift detection: is the paper track record behaving like the backtest?

Compares live paper stats against the expectations recorded in the
strategy's ValidationReport (trade-swing's report schema).  Pure functions
on plain data — no engines, no I/O.

Verdicts: OK / WATCH / VIOLATION.

Statistical rationale (documented honestly): each metric is compared with
an approximate sampling band around the backtest value.  With few trades
the bands are wide — the detector says "I can't tell yet" (OK or WATCH)
rather than crying wolf.  That weakness is stated, not hidden.
"""

from __future__ import annotations

import math


# ------------------------------------------------------------ paper stats

def paper_stats(daily_equity: list[float], trades: list[dict],
                periods_per_year: int = 252) -> dict:
    """Summarize a paper track record into the same metrics as the backtest.

    ``daily_equity``: end-of-day equity curve (one value per trading day).
    ``trades``: closed trades, each {pnl} at minimum (pnl in currency units).
    """
    stats: dict = {"n_days": len(daily_equity), "n_trades": len(trades)}
    if len(daily_equity) >= 2:
        rets = [(daily_equity[i] / daily_equity[i - 1] - 1.0)
                for i in range(1, len(daily_equity))
                if daily_equity[i - 1] > 0]
    else:
        rets = []
    stats["n_returns"] = len(rets)
    if rets:
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / max(len(rets) - 1, 1)
        sd = math.sqrt(var)
        stats["sharpe"] = (mu / sd * math.sqrt(periods_per_year)) if sd > 0 else 0.0
        # Standard error of the Sharpe (Lo 2002): sqrt((1 + S^2/2) / N).
        s = stats["sharpe"] / math.sqrt(periods_per_year)  # per-period Sharpe
        stats["sharpe_se"] = math.sqrt((1.0 + 0.5 * s * s) / len(rets)) \
            * math.sqrt(periods_per_year)
    else:
        stats["sharpe"] = 0.0
        stats["sharpe_se"] = float("inf")
    # Drawdown from the equity curve.
    peak = float("-inf")
    max_dd = 0.0
    for e in daily_equity:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    stats["max_drawdown"] = max_dd
    # Trade-level stats.
    wins = [t["pnl"] for t in trades if t.get("pnl", 0) > 0]
    losses = [-t["pnl"] for t in trades if t.get("pnl", 0) < 0]
    n = len(trades)
    stats["win_rate"] = len(wins) / n if n else 0.0
    stats["avg_win"] = sum(wins) / len(wins) if wins else 0.0
    stats["avg_loss"] = sum(losses) / len(losses) if losses else 0.0
    stats["payoff"] = (stats["avg_win"] / stats["avg_loss"]
                       if stats["avg_loss"] > 0 else 0.0)
    stats["trades_per_day"] = n / len(daily_equity) if daily_equity else 0.0
    return stats


# ---------------------------------------------------------------- verdicts

def _band_verdict(paper: float, expected: float, se: float,
                  name: str, details: list) -> str:
    """Grade one metric: OK within 2 SE, WATCH within 3 SE, else VIOLATION.

    Infinite SE (no data) -> OK with a note: absence of evidence is not
    evidence of drift.
    """
    if not math.isfinite(se) or se <= 0:
        details.append(f"{name}: no data yet — cannot judge (OK by default)")
        return "OK"
    dev = abs(paper - expected) / se
    details.append(f"{name}: paper {paper:.3f} vs expected {expected:.3f} "
                   f"({dev:.1f} SE)")
    if dev <= 2.0:
        return "OK"
    if dev <= 3.0:
        return "WATCH"
    return "VIOLATION"


def drift_verdict(expected: dict, paper: dict) -> dict:
    """Compare paper stats to backtest expectations.

    ``expected``: {"sharpe", "win_rate", "payoff", "max_drawdown",
    "trades_per_day", "n_trades"} — the backtest side of a ValidationReport.
    ``paper``: output of :func:`paper_stats`.
    """
    details: list[str] = []
    grades = {}
    n_trades = paper.get("n_trades", 0)

    # Sharpe with its sampling band.
    grades["sharpe"] = _band_verdict(
        paper.get("sharpe", 0.0), float(expected.get("sharpe", 0.0)),
        paper.get("sharpe_se", float("inf")), "sharpe", details)

    # Win rate: binomial SE around the backtest rate.
    p_bt = float(expected.get("win_rate", 0.5))
    se_wr = math.sqrt(p_bt * (1 - p_bt) / n_trades) if n_trades > 0 else float("inf")
    grades["win_rate"] = _band_verdict(
        paper.get("win_rate", 0.0), p_bt, se_wr, "win_rate", details)

    # Payoff ratio: rough band, ±50% of expected (payoff is noisy; be humble).
    # Needs both wins and losses to mean anything — with <5 trades the
    # ratio is dominated by luck (e.g. zero losses reads as payoff 0).
    payoff_bt = float(expected.get("payoff", 1.0)) or 1.0
    if n_trades < 5:
        grades["payoff"] = "OK"
        details.append(f"payoff: only {n_trades} trades — too few to judge "
                       f"(OK by default)")
    elif paper.get("avg_loss", 0.0) <= 0:
        # No losing trades yet: the payoff ratio is undefined, not zero.
        grades["payoff"] = "OK"
        details.append("payoff: no losing trades yet — ratio undefined "
                       "(OK by default)")
    else:
        se_pay = 0.5 * payoff_bt / math.sqrt(n_trades)
        grades["payoff"] = _band_verdict(
            paper.get("payoff", 0.0), payoff_bt, se_pay, "payoff", details)

    # Drawdown: one-sided — paper DD much worse than backtest DD is the
    # signal; paper DD *better* is never drift.
    dd_bt = abs(float(expected.get("max_drawdown", 0.0))) or 1e-9
    dd_paper = abs(float(paper.get("max_drawdown", 0.0)))
    ratio = dd_paper / dd_bt
    details.append(f"max_drawdown: paper {dd_paper:.2%} vs backtest {dd_bt:.2%} "
                   f"(ratio {ratio:.2f}x)")
    grades["max_drawdown"] = ("OK" if ratio <= 1.25 else
                              "WATCH" if ratio <= 1.5 else "VIOLATION")

    # Trade frequency: halved pace is WATCH, quarter pace is VIOLATION.
    # Needs a few days of record first — day 1 with zero trades is not
    # "the strategy stopped trading", it's "the quarter just started".
    tpd_bt = float(expected.get("trades_per_day", 0.0)) or 1e-9
    if paper.get("n_days", 0) < 5:
        grades["trade_frequency"] = "OK"
        details.append("trades_per_day: <5 days of record — too early to judge "
                       "(OK by default)")
    else:
        tpd_ratio = paper.get("trades_per_day", 0.0) / tpd_bt
        details.append(f"trades_per_day: ratio {tpd_ratio:.2f}x of backtest pace")
        grades["trade_frequency"] = ("OK" if tpd_ratio >= 0.5 else
                                     "WATCH" if tpd_ratio >= 0.25 else "VIOLATION")

    order = {"OK": 0, "WATCH": 1, "VIOLATION": 2}
    overall = max(grades.values(), key=lambda g: order[g])
    return {"verdict": overall, "grades": grades, "details": details,
            "n_trades": n_trades,
            "note": ("Bands are wide with few trades: early WATCH verdicts "
                     "usually mean 'not enough data', not 'strategy broken'.")}


def compare(expected: dict, daily_equity: list[float],
            trades: list[dict]) -> dict:
    """One-call drift check: stats + verdict.  schema_version 1."""
    paper = paper_stats(daily_equity, trades)
    result = drift_verdict(expected, paper)
    result["schema_version"] = 1
    result["paper"] = paper
    return result
