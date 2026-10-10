"""The daily digest: what a human in the field needs, in 60 seconds on a phone.

``build_digest`` returns a plain-data dict; ``render_digest`` renders it as
monospace-friendly text.  Both are pure — no engines, no I/O.
"""

from __future__ import annotations


def build_digest(*, strategy: str, day: int, stage: str, equity: float,
                 start_equity: float, day_pnl: float, positions: list[dict],
                 conviction: float | None, drift: str,
                 pending_approvals: int, paused: bool,
                 kill_trips: list | None = None) -> dict:
    """Assemble the digest payload.  schema_version 1."""
    inception = equity - start_equity
    inception_pct = inception / start_equity if start_equity else 0.0
    return {
        "schema_version": 1,
        "strategy": strategy,
        "day": day,
        "stage": stage,
        "paused": paused,
        "equity": round(equity, 2),
        "day_pnl": round(day_pnl, 2),
        "inception_pnl": round(inception, 2),
        "inception_pct": round(inception_pct * 100, 2),
        "positions": [
            {"symbol": p.get("symbol"), "qty": p.get("qty"),
             "unrealized": round(float(p.get("unrealized", 0.0)), 2)}
            for p in positions
        ],
        "n_positions": len(positions),
        "regime_conviction": None if conviction is None else round(conviction, 1),
        "drift": drift,
        "pending_approvals": pending_approvals,
        "kill_trips": kill_trips or [],
    }


def _bar(pct: float, width: int = 20) -> str:
    filled = max(0, min(width, int(round(abs(pct) / 100 * width))))
    return ("+" if pct >= 0 else "-") + "#" * filled + "." * (width - filled)


def render_digest(d: dict) -> str:
    """Render the digest as compact text for a phone screen."""
    lines = [
        f"INCUBATION  {d['strategy']}  day {d['day']}/63  [{d['stage']}]",
        f"equity ${d['equity']:,.2f}  day {d['day_pnl']:+,.2f}  "
        f"incept {d['inception_pnl']:+,.2f} ({d['inception_pct']:+.2f}%)",
        _bar(d["inception_pct"]),
        f"positions: {d['n_positions']}  "
        f"conviction: {d['regime_conviction'] if d['regime_conviction'] is not None else '?'}  "
        f"drift: {d['drift']}",
        f"approvals pending: {d['pending_approvals']}",
    ]
    for p in d["positions"]:
        lines.append(f"  {p['symbol']}: {p['qty']}  uP&L {p['unrealized']:+.2f}")
    if d["paused"]:
        lines.append("!! PAUSED — kill condition tripped. Review required.")
        for k in d["kill_trips"]:
            lines.append(f"   day {k.get('day')}: {k.get('condition')} — {k.get('detail')}")
    elif d["drift"] == "WATCH":
        lines.append("! drift WATCH — behaving oddly vs backtest; keep an eye on it.")
    elif d["drift"] == "VIOLATION":
        lines.append("!! drift VIOLATION — program should be pausing.")
    return "\n".join(lines)
