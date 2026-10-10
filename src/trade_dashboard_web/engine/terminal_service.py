"""Terminal-wave jobs: the flagship monitoring/analysis layer.

Five canonical jobs (v0.5.0), each ``run_*_job(...) -> dict`` with plain
data in and JSON-serializable plain data out, following the research-lab
pattern from ``research_service.py``:

- ``run_trades_job``        paper-ledger trade blotter + CSV export
- ``run_performance_job``   equity / drawdown / monthly / rolling analytics
- ``run_agent_activity_job`` agent track-record leaderboards, Elo curves,
                            Brier calibration, debate timeline, approval queue
- ``run_network_job``       correlation MST network with seeded SVG layout
- ``run_risk_monitor_job``  exposures, vol-regime timeline, kill-switch,
                            regime-conviction gauge

Everything is lazy and read-only with respect to the outside world:

- The paper ledger is opened with SQLite ``mode=ro`` (URI) — the dashboard
  never writes to a ledger.  (The ``trade-paper`` ``Ledger`` class itself
  runs ``CREATE TABLE IF NOT EXISTS`` on connect, which is a write, so it
  is deliberately *not* used here.)
- Sibling engines (trade-agents, trade-data-equities) are imported lazily;
  a missing engine raises ``RuntimeError`` with a ``pip install`` hint.
- When a ledger / track-record file is absent, jobs return a deterministic,
  clearly-labelled in-memory DEMO dataset (``demo: True`` on the payload
  and every row) instead of failing — demo data is never presented as real.

Research / paper-trading scope only: nothing here places orders or writes
to any broker.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DEMO_SEED = 7


def _require(dist: str, package: str):
    """Import ``package`` or raise a helpful error naming the install."""
    try:
        return __import__(package, fromlist=["*"])
    except ImportError as exc:
        raise RuntimeError(
            f"{dist} is not installed; install it with "
            f"`pip install git+https://github.com/crieck2010/{dist}.git`"
        ) from exc


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _round(x, nd=4):
    if x is None:
        return None
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return round(float(x), nd)


def _jsonable(value):
    """Recursively coerce to JSON-safe values (NaN/Inf -> None)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Ledger / snapshot resolution
# ---------------------------------------------------------------------------

def resolve_ledger_path(ledger_path: str | None = None) -> str | None:
    """Resolve the trade-paper audit-ledger location.

    Precedence: explicit argument, ``TRADE_PAPER_LEDGER`` env var,
    ``./trade-paper.db`` (the ``trade-paper`` ``PaperConfig.db_path``
    default — a path relative to the runner's working directory), then
    ``~/trade-paper.db``.  Returns ``None`` when nothing exists.
    """
    if ledger_path:
        p = Path(ledger_path).expanduser()
        return str(p) if p.exists() else None
    env = os.environ.get("TRADE_PAPER_LEDGER")
    if env and Path(env).expanduser().exists():
        return str(Path(env).expanduser())
    for cand in (Path("trade-paper.db"), Path.home() / "trade-paper.db"):
        if cand.exists():
            return str(cand)
    return None


def _open_ro(path: str) -> sqlite3.Connection:
    """Open a SQLite file read-only (``mode=ro``): never creates, never writes."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def resolve_track_record_path(track_record_path: str | None = None) -> str | None:
    """Resolve the trade-agents JSONL track-record file.

    Precedence: explicit argument, ``TRADE_AGENTS_TRACK_RECORD`` env var,
    then ``./trade-agents-track-record.jsonl``.  (trade-agents has no
    default path of its own — its CLI requires ``--ledger``.)
    """
    if track_record_path:
        p = Path(track_record_path).expanduser()
        return str(p) if p.exists() else None
    env = os.environ.get("TRADE_AGENTS_TRACK_RECORD")
    if env and Path(env).expanduser().exists():
        return str(Path(env).expanduser())
    cand = Path("trade-agents-track-record.jsonl")
    return str(cand) if cand.exists() else None


def _read_jsonl(path: str) -> tuple[list[dict], int]:
    events, bad = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    return events, bad


def _snapshot_input(value) -> dict | None:
    """Accept a snapshot dict or a path to a JSON snapshot file."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    p = Path(str(value)).expanduser()
    if not p.exists():
        raise ValueError(f"snapshot file not found: {value}")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"snapshot file must hold a JSON object: {value}")
    return data


# ---------------------------------------------------------------------------
# 1. Trades blotter
# ---------------------------------------------------------------------------

_OPEN_STATES = {"submitted", "accepted", "pending", "working", "partial",
                "partially_filled", "open"}


def _fifo_match(fills: list[dict]) -> tuple[dict[str, float], dict[str, float]]:
    """FIFO lot matching per symbol over fills ordered oldest-first.

    Returns ``(realized_by_order, net_qty_by_symbol)``.  Buys open lots;
    sells close oldest lots first; the realized P&L of each closed portion
    is attributed to the *sell* fill's order.  Short-first ledgers are not
    specially handled (documented limitation).
    """
    lots: dict[str, list[list]] = {}          # symbol -> [[qty, price, order_id]]
    realized: dict[str, float] = {}
    net: dict[str, float] = {}
    for fl in sorted(fills, key=lambda r: str(r.get("filled_at") or "")):
        sym = str(fl.get("symbol") or "").upper()
        side = str(fl.get("side") or "").lower()
        qty = float(fl.get("quantity") or 0.0)
        px = float(fl.get("price") or 0.0)
        oid = str(fl.get("client_order_id") or "")
        if qty <= 0:
            continue
        book = lots.setdefault(sym, [])
        if side == "buy":
            book.append([qty, px, oid])
            net[sym] = net.get(sym, 0.0) + qty
        elif side == "sell":
            need = qty
            pnl = 0.0
            while need > 1e-12 and book:
                lot_qty, lot_px, _ = book[0]
                take = min(need, lot_qty)
                pnl += take * (px - lot_px)
                book[0][0] = lot_qty - take
                need -= take
                if book[0][0] <= 1e-12:
                    book.pop(0)
            realized[oid] = realized.get(oid, 0.0) + pnl
            net[sym] = net.get(sym, 0.0) - qty
    return realized, net


def _demo_trades() -> list[dict]:
    rng = random.Random(DEMO_SEED)
    syms = ["SPY", "QQQ", "AAPL", "MSFT", "TSLA", "NVDA"]
    strategies = ["sma_crossover", "mean_reversion", "breakout"]
    rows = []
    base = datetime(2026, 7, 1, 14, 30, tzinfo=timezone.utc)
    for i in range(12):
        sym = syms[i % len(syms)]
        side = "buy" if i % 2 == 0 else "sell"
        qty = 10 * (1 + i % 5)
        px = round(100 + rng.uniform(-20, 60), 2)
        pnl = round(rng.uniform(-250, 400), 2)
        outcome = "win" if pnl > 0 else ("loss" if pnl < 0 else "unknown")
        rows.append({
            "id": f"demo-order-{i + 1:03d}", "symbol": sym, "side": side,
            "qty": float(qty), "filled_qty": float(qty),
            "avg_fill_price": px, "commission": round(qty * 0.01, 2),
            "strategy": strategies[i % len(strategies)], "agent": None,
            "state": "filled",
            "created_at": (base + timedelta(days=i * 6)).isoformat(),
            "filled_at": (base + timedelta(days=i * 6, hours=1)).isoformat(),
            "realized_pnl": pnl, "outcome": outcome, "demo": True,
        })
    return rows


def run_trades_job(
    ledger_path=None,
    date_from=None,
    date_to=None,
    symbol=None,
    side=None,
    strategy=None,
    agent=None,
    outcome=None,
    limit=500,
) -> dict:
    """Trade blotter over the trade-paper audit ledger (read-only).

    Joins ``orders`` with ``fills``; realized P&L per order comes from FIFO
    lot matching of fills per symbol, attributed to the closing (sell)
    fill's order.  Outcome is ``win``/``loss`` when the attributed P&L is
    nonzero, ``open`` when fills remain part of an open net position (or
    the order is still working), else ``unknown``.

    The paper ledger has **no per-order agent column**: the ``agent``
    filter is a case-insensitive substring match over ``strategy`` and the
    client order id (documented approximation).

    With no ledger found, returns a deterministic in-memory DEMO dataset
    (``demo: True``, every row flagged) — never presented as real.
    """
    path = resolve_ledger_path(ledger_path)
    filters = {"date_from": date_from, "date_to": date_to, "symbol": symbol,
               "side": side, "strategy": strategy, "agent": agent,
               "outcome": outcome, "limit": limit}
    if path is None:
        rows = _demo_trades()
        rows = _apply_trade_filters(rows, filters)
        return {"trades": rows[: max(int(limit or 0), 0)], "count": len(rows),
                "filters": filters, "demo": True, "ledger_path": None,
                "message": ("DEMO — no paper ledger found (looked for "
                            "TRADE_PAPER_LEDGER, ./trade-paper.db, "
                            "~/trade-paper.db). Synthetic rows for plumbing "
                            "tests only; not real trades.")}
    db = _open_ro(path)
    try:
        have = _tables(db)
        for t in ("orders", "fills"):
            if t not in have:
                raise ValueError(f"ledger {path} has no {t!r} table")
        orders = [dict(r) for r in db.execute("SELECT * FROM orders")]
        fills = [dict(r) for r in db.execute("SELECT * FROM fills")]
    finally:
        db.close()
    realized, net_qty = _fifo_match(fills)
    fills_by_order: dict[str, list[dict]] = {}
    for fl in fills:
        fills_by_order.setdefault(str(fl.get("client_order_id") or ""),
                                  []).append(fl)
    rows = []
    for o in orders:
        oid = str(o.get("client_order_id") or "")
        of = fills_by_order.get(oid, [])
        fqty = sum(float(f.get("quantity") or 0.0) for f in of)
        notional = sum(float(f.get("quantity") or 0.0)
                       * float(f.get("price") or 0.0) for f in of)
        comm = sum(float(f.get("commission") or 0.0) for f in of)
        pnl = realized.get(oid, 0.0)
        sym = str(o.get("symbol") or "").upper()
        if pnl > 1e-12:
            oc = "win"
        elif pnl < -1e-12:
            oc = "loss"
        elif fqty > 0 and abs(net_qty.get(sym, 0.0)) > 1e-12:
            oc = "open"
        elif str(o.get("state") or "").lower() in _OPEN_STATES:
            oc = "open"
        else:
            oc = "unknown"
        filled_at = max((str(f.get("filled_at") or "") for f in of),
                        default=None) or None
        rows.append({
            "id": oid, "symbol": sym,
            "side": str(o.get("side") or "").lower(),
            "qty": _round(o.get("quantity"), 4),
            "filled_qty": _round(fqty, 4),
            "avg_fill_price": _round(notional / fqty, 4) if fqty > 0 else None,
            "commission": _round(comm, 2),
            "strategy": o.get("strategy"),
            "agent": None,
            "state": o.get("state"),
            "created_at": o.get("created_at"),
            "filled_at": filled_at,
            "realized_pnl": _round(pnl, 2),
            "outcome": oc,
            "demo": False,
        })
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    rows = _apply_trade_filters(rows, filters)
    return {"trades": _jsonable(rows[: max(int(limit or 0), 0)]),
            "count": len(rows), "filters": filters, "demo": False,
            "ledger_path": path,
            "message": (f"{len(orders)} orders, {len(fills)} fills read "
                        f"read-only from {path}")}


def _apply_trade_filters(rows: list[dict], filters: dict) -> list[dict]:
    def keep(r: dict) -> bool:
        df, dt = filters.get("date_from"), filters.get("date_to")
        if df and str(r.get("created_at") or "")[:10] < str(df)[:10]:
            return False
        if dt and str(r.get("created_at") or "")[:10] > str(dt)[:10]:
            return False
        sym = filters.get("symbol")
        if sym and str(r.get("symbol") or "").upper() != str(sym).upper():
            return False
        side = filters.get("side")
        if side and str(r.get("side") or "").lower() != str(side).lower():
            return False
        strat = filters.get("strategy")
        if strat and str(strat).lower() not in str(r.get("strategy") or "").lower():
            return False
        ag = filters.get("agent")
        if ag:
            hay = (str(r.get("strategy") or "") + " "
                   + str(r.get("id") or "")).lower()
            if str(ag).lower() not in hay:
                return False
        oc = filters.get("outcome")
        if oc and str(r.get("outcome") or "").lower() != str(oc).lower():
            return False
        return True
    return [r for r in rows if keep(r)]


def trades_to_csv(result: dict) -> str:
    """Render a ``run_trades_job`` result as CSV (for the export route)."""
    buf = io.StringIO()
    cols = ["id", "symbol", "side", "qty", "filled_qty", "avg_fill_price",
            "commission", "strategy", "state", "created_at", "filled_at",
            "realized_pnl", "outcome", "demo"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in result.get("trades", []):
        w.writerow([r.get(c) for c in cols])
    return buf.getvalue()

# ---------------------------------------------------------------------------
# 2. Performance analytics
# ---------------------------------------------------------------------------

_ROLL_WINDOW = 63  # ~one quarter of daily bars


def _demo_equity(n: int = 252, seed: int = DEMO_SEED) -> list[tuple[str, float]]:
    rng = random.Random(seed)
    eq, out = 100_000.0, []
    t = datetime(2025, 1, 2, tzinfo=timezone.utc)
    for i in range(n):
        eq *= 1.0 + 0.0004 + rng.gauss(0, 0.008)
        out.append(((t + timedelta(days=i)).isoformat(), eq))
    return out


def _normalize_equity(raw) -> list[tuple[str, float]]:
    """Accept the documented backtest-equity shapes -> [(ts, value)]."""
    pts: list[tuple[str, float]] = []
    for e in raw or []:
        if isinstance(e, (list, tuple)) and len(e) == 2:
            ts, val = e
        elif isinstance(e, dict):
            ts = (e.get("timestamp") or e.get("ts") or e.get("date")
                  or e.get("at"))
            val = e.get("equity", e.get("value", e.get("eq")))
        else:  # engine object with .timestamp / .equity attributes
            ts = getattr(e, "timestamp", None)
            val = getattr(e, "equity", getattr(e, "value", None))
        if ts is None or val is None:
            continue
        ts_s = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        try:
            pts.append((ts_s, float(val)))
        except (TypeError, ValueError):
            continue
    pts.sort(key=lambda p: p[0])
    return pts


def _normalize_trade_pnls(raw) -> list[float]:
    pnls = []
    for t in raw or []:
        if isinstance(t, dict):
            v = t.get("pnl", t.get("realized_pnl", t.get("profit")))
        else:
            v = getattr(t, "pnl", getattr(t, "realized_pnl", None))
        try:
            pnls.append(float(v))
        except (TypeError, ValueError):
            continue
    return pnls


def _performance_from_equity(points: list[tuple[str, float]],
                             trade_pnls: list[float],
                             risk_free: float = 0.0) -> dict:
    """Shared analytics over an equity curve.

    Drawdown is emitted two ways: the ``drawdown`` series is the underwater
    curve (negative fractions, 0 at peaks) while ``summary.max_drawdown``
    is the positive worst peak-to-trough fraction.
    """
    n = len(points)
    eq = [p[1] for p in points]
    rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, n)] if n > 1 else []
    # underwater drawdown series (<= 0)
    peak, dd = eq[0] if eq else 0.0, []
    for v in eq:
        peak = max(peak, v)
        dd.append(-(peak - v) / peak if peak > 0 else 0.0)
    max_dd = max((peak_i - v) / peak_i
                 for peak_i, v in zip(_running_peak(eq), eq)
                 ) if eq else 0.0
    # monthly: per calendar year, 12 monthly returns (None when no data)
    months: dict[tuple[int, int], list[float]] = {}
    for i, r in enumerate(rets):
        dt = _parse_ts(points[i + 1][0])
        if dt is None:
            continue
        months.setdefault((dt.year, dt.month), []).append(r)
    years = sorted({y for y, _ in months})
    monthly = []
    for y in years:
        row = []
        for m in range(1, 13):
            rs = months.get((y, m))
            row.append(_round(math.prod(1.0 + x for x in rs) - 1.0, 6)
                       if rs else None)
        monthly.append(row)
    # rolling Sharpe / vol (63-day window, annualized)
    r_sharpe: list = [None] * n
    r_vol: list = [None] * n
    for i in range(_ROLL_WINDOW, n):
        w = [r - risk_free / 252.0 for r in rets[i - _ROLL_WINDOW:i]]
        mu = sum(w) / len(w)
        var = sum((x - mu) ** 2 for x in w) / (len(w) - 1)
        sd = math.sqrt(var)
        vol = sd * math.sqrt(252.0)
        r_vol[i] = _round(vol, 6)
        r_sharpe[i] = _round(mu / sd * math.sqrt(252.0), 4) if sd > 0 else None
    # histogram of returns (25 bins)
    hist = {"bins": [], "counts": []}
    if len(rets) >= 2:
        lo, hi = min(rets), max(rets)
        span = (hi - lo) or 1e-9
        nb = 25
        edges = [lo + span * k / nb for k in range(nb + 1)]
        counts = [0] * nb
        for r in rets:
            k = min(int((r - lo) / span * nb), nb - 1)
            counts[k] += 1
        hist = {"bins": [_round(e, 6) for e in edges], "counts": counts}
    # summary from trade P&Ls
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    cagr = None
    if n > 1 and eq[0] > 0:
        d0, d1 = _parse_ts(points[0][0]), _parse_ts(points[-1][0])
        yrs = ((d1 - d0).total_seconds() / 86400.0 / 365.25
               if d0 and d1 else n / 252.0)
        if yrs > 0:
            cagr = (eq[-1] / eq[0]) ** (1.0 / yrs) - 1.0
    summary = {
        "win_rate": _round(len(wins) / len(trade_pnls), 4) if trade_pnls else None,
        "profit_factor": _round(gp / gl, 4) if gl > 0 else None,
        "expectancy": _round(sum(trade_pnls) / len(trade_pnls), 4)
        if trade_pnls else None,
        "max_drawdown": _round(max_dd, 6),
        "cagr": _round(cagr, 6),
        "n_trades": len(trade_pnls),
        "start": points[0][0] if points else None,
        "end": points[-1][0] if points else None,
    }
    return {
        "equity": [[ts, _round(v, 2)] for ts, v in points],
        "drawdown": [_round(d, 6) for d in dd],
        "monthly": monthly,
        "years": years,
        "rolling_sharpe": r_sharpe,
        "rolling_vol": r_vol,
        "histogram": hist,
        "summary": summary,
    }


def _running_peak(eq: list[float]) -> list[float]:
    out, peak = [], 0.0
    for v in eq:
        peak = max(peak, v)
        out.append(peak)
    return out


def _fills_realized_series(db: sqlite3.Connection) -> list[tuple[str, float]]:
    """Reconstruct a *relative* equity curve from fills.

    Cumulative FIFO realized P&L rebased at 0 — a shape proxy, not true
    equity (no starting capital, no unrealized marks, no cash flows are in
    the ledger).  Documented as such wherever it is used.
    """
    fills = [dict(r) for r in db.execute(
        "SELECT * FROM fills ORDER BY filled_at")]
    if not fills:
        return []
    lots: dict[str, list[list]] = {}
    cum, pts = 0.0, []
    for fl in fills:
        sym = str(fl.get("symbol") or "").upper()
        side = str(fl.get("side") or "").lower()
        qty = float(fl.get("quantity") or 0.0)
        px = float(fl.get("price") or 0.0)
        book = lots.setdefault(sym, [])
        if side == "buy":
            book.append([qty, px])
        elif side == "sell":
            need = qty
            while need > 1e-12 and book:
                take = min(need, book[0][0])
                cum += take * (px - book[0][1])
                book[0][0] -= take
                need -= take
                if book[0][0] <= 1e-12:
                    book.pop(0)
        pts.append((str(fl.get("filled_at") or ""), cum))
    return pts


def run_performance_job(
    source="paper",
    ledger_path=None,
    backtest=None,
    backtest_path=None,
    risk_free=0.0,
) -> dict:
    """Performance analytics over paper equity or a backtest result.

    ``source="paper"``: equity from the ledger's ``equity_snapshots``
    table; when the ledger has no snapshots, falls back to a
    *reconstructed* relative curve (cumulative FIFO realized P&L rebased
    at 0 — documented in the payload as ``equity_source``; it is a shape
    proxy, not true equity).

    ``source="backtest"``: accepts a trade-backtest result *dict* or a
    path to its JSON output.  Accepted schema (lenient superset)::

        {"equity": [{"timestamp": <ISO>, "equity": <float>} ...],
         "trades": [{"pnl": <float>} ...]}

    ``equity`` rows also accept ``{"ts","value"}``, ``{"date","equity"}``
    or ``[ts, value]`` pairs; trade rows accept ``realized_pnl`` /
    ``profit`` as the P&L key.  Engine objects (``BacktestResult`` with
    ``equity_curve`` of ``EquityPoint`` and ``trades`` of ``Trade``) are
    accepted too via attribute reads.
    """
    if source not in ("paper", "backtest"):
        raise ValueError("source must be 'paper' or 'backtest'")
    demo = False
    equity_source = "equity_snapshots"
    message = ""
    trade_pnls: list[float] = []
    if source == "paper":
        path = resolve_ledger_path(ledger_path)
        if path is None:
            points = _demo_equity()
            trade_pnls = [r["realized_pnl"] for r in _demo_trades()]
            demo, equity_source = True, "demo"
            message = "DEMO — no paper ledger found; seeded synthetic equity."
        else:
            db = _open_ro(path)
            try:
                have = _tables(db)
                snaps = []
                if "equity_snapshots" in have:
                    snaps = [dict(r) for r in db.execute(
                        "SELECT at, equity FROM equity_snapshots ORDER BY at")]
                if snaps:
                    points = _normalize_equity(
                        [{"timestamp": s["at"], "equity": s["equity"]}
                         for s in snaps])
                    message = (f"{len(snaps)} equity snapshots read read-only "
                               f"from {path}")
                else:
                    points = _fills_realized_series(db)
                    equity_source = "fills_reconstructed"
                    message = ("no equity_snapshots in ledger; equity is a "
                               "RECONSTRUCTED relative curve (cumulative FIFO "
                               "realized P&L rebased at 0) — shape proxy only")
                if "fills" in have:
                    fills = [dict(r) for r in db.execute("SELECT * FROM fills")]
                    realized, _ = _fifo_match(fills)
                    trade_pnls = [p for p in realized.values() if p != 0.0]
            finally:
                db.close()
            if not points:
                points = _demo_equity()
                trade_pnls = [r["realized_pnl"] for r in _demo_trades()]
                demo, equity_source = True, "demo"
                message = ("ledger has no equity_snapshots and no fills; "
                           "DEMO synthetic equity shown instead")
    else:
        data = backtest
        if data is None and backtest_path:
            with open(Path(backtest_path).expanduser(), encoding="utf-8") as f:
                data = json.load(f)
        if data is None:
            raise ValueError("source='backtest' needs backtest or backtest_path")
        if isinstance(data, dict) and "equity" not in data and "equity_curve" in data:
            data = {**data, "equity": data["equity_curve"]}
        points = _normalize_equity((data.get("equity") if isinstance(data, dict)
                                    else getattr(data, "equity_curve", [])))
        trade_pnls = _normalize_trade_pnls(
            (data.get("trades") if isinstance(data, dict)
             else getattr(data, "trades", [])))
        equity_source = "backtest"
        message = (f"backtest result: {len(points)} equity points, "
                   f"{len(trade_pnls)} trades")
    if not points:
        raise ValueError("no equity points available")
    out = _performance_from_equity(points, trade_pnls, risk_free=float(risk_free))
    out.update({"source": source, "equity_source": equity_source,
                "risk_free": float(risk_free), "demo": demo, "message": message})
    return _jsonable(out)

# ---------------------------------------------------------------------------
# 3. Agent activity
# ---------------------------------------------------------------------------

_ELO_K = 32.0
_ELO_BASE = 1500.0


def _elo_expect(rating: float, opp: float = _ELO_BASE) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opp - rating) / 400.0))


def _elo_curves(events: list[dict]) -> dict[str, list[dict]]:
    """Dashboard-side Elo ratings per agent over time.

    Each ``outcome`` / ``pm_outcome`` event is treated as a match against a
    fixed 1500-rated "market": score 1/0.5/0 by the sign of the event's mean
    return, ``E = 1/(1+10^((1500-R)/400))``, ``R += 32*(S-E)``.  This is a
    dashboard approximation for sparklines — *not* a trade-agents engine
    number (trade-agents scores agents with decayed Sharpe / Brier /
    penalized-Sharpe formulas in ``track_record.py``).
    """
    proposals = {e.get("idea_id"): e.get("agent")
                 for e in events if e.get("type") == "proposal"}
    games: list[tuple[str, str, float]] = []  # (ts, agent, score)
    for e in events:
        t = e.get("type")
        if t == "outcome":
            agent = proposals.get(e.get("idea_id"))
            rets = e.get("returns") or []
            mu = sum(rets) / len(rets) if rets else 0.0
            score = 1.0 if mu > 0 else (0.0 if mu < 0 else 0.5)
            if agent:
                games.append((str(e.get("ts") or ""), agent, score))
        elif t == "pm_outcome":
            agent = e.get("agent")
            rets = e.get("returns") or []
            mu = sum(rets) / len(rets) if rets else 0.0
            score = 1.0 if mu > 0 else (0.0 if mu < 0 else 0.5)
            if agent:
                games.append((str(e.get("ts") or ""), agent, score))
    games.sort(key=lambda g: g[0])
    ratings: dict[str, float] = {}
    curves: dict[str, list[dict]] = {}
    for ts, agent, score in games:
        r = ratings.get(agent, _ELO_BASE)
        r = r + _ELO_K * (score - _elo_expect(r))
        ratings[agent] = r
        curves.setdefault(agent, []).append(
            {"ts": ts, "rating": round(r, 1)})
    return curves


def _brier_calibration(events: list[dict], n_bins: int = 10) -> dict:
    """Brier calibration of risk-desk drawdown forecasts.

    Each ``risk_forecast`` (``p_exceed`` = P(max DD > threshold)) paired
    with the later ``outcome`` for the same idea: ``o = 1`` if the
    realized max drawdown exceeded the threshold else 0.  Binned by
    forecast probability; observed = mean ``o`` per bin.
    """
    outcomes = {e.get("idea_id"): e for e in events
                if e.get("type") == "outcome"}
    pairs = []
    for e in events:
        if e.get("type") != "risk_forecast":
            continue
        out = outcomes.get(e.get("idea_id"))
        if out is None:
            continue
        fc = e.get("forecast") or {}
        try:
            p = max(0.0, min(1.0, float(fc.get("p_exceed", 0.5))))
            thr = float(fc.get("dd_threshold", 0.10))
        except (TypeError, ValueError):
            continue
        rets = [float(r) for r in (out.get("returns") or [])]
        peak, worst, eq = 1.0, 0.0, 1.0
        for r in rets:
            eq *= 1.0 + r
            peak = max(peak, eq)
            worst = max(worst, (peak - eq) / peak if peak > 0 else 0.0)
        pairs.append((p, 1.0 if worst > thr else 0.0))
    bins = [(i + 0.5) / n_bins for i in range(n_bins)]
    sums = [0.0] * n_bins
    counts = [0] * n_bins
    for p, o in pairs:
        k = min(int(p * n_bins), n_bins - 1)
        sums[k] += o
        counts[k] += 1
    return {"bins": bins,
            "observed": [round(sums[i] / counts[i], 4) if counts[i] else None
                         for i in range(n_bins)],
            "n": counts}


def _debates_from_approvals(approvals_ledger_path: str | None,
                            limit: int) -> tuple[list[dict], str]:
    """Debate timeline from the paper ledger's approvals table.

    trade-agents' ``adapters`` stash the debate synthesis (bull/bear
    pressure, conviction, rounds) into ``approvals.metrics`` JSON under
    ``chain.debate`` when an idea is submitted for approval — that is the
    durable debate record the dashboard reads.
    """
    path = resolve_ledger_path(approvals_ledger_path)
    if path is None:
        return [], "no paper ledger found — debate timeline unavailable"
    db = _open_ro(path)
    try:
        if "approvals" not in _tables(db):
            return [], f"ledger {path} has no approvals table"
        rows = [dict(r) for r in db.execute(
            "SELECT discovery_key, strategy, symbols, metrics, status, "
            "created_at FROM approvals ORDER BY created_at DESC")]
    finally:
        db.close()
    debates = []
    for r in rows:
        try:
            metrics = json.loads(r.get("metrics") or "{}")
        except json.JSONDecodeError:
            continue
        debate = ((metrics.get("chain") or {}).get("debate")) or {}
        if not debate:
            continue
        net = debate.get("net_pressure", 0.0) or 0.0
        verdict = "bull" if net > 0 else ("bear" if net < 0 else "even")
        debates.append({
            "idea_id": r.get("discovery_key"),
            "ts": r.get("created_at"),
            "strategy": r.get("strategy"),
            "symbols": r.get("symbols"),
            "challengers": ["bull", "bear"],
            "verdict": verdict,
            "conviction": debate.get("conviction"),
            "net_pressure": debate.get("net_pressure"),
            "n_rounds": debate.get("n_rounds"),
            "approval_status": r.get("status"),
        })
    return debates[: max(int(limit or 0), 0)], (
        f"{len(debates)} debated ideas read read-only from {path}")


def _approval_queue(approvals_ledger_path: str | None,
                    limit: int) -> tuple[list[dict], str]:
    path = resolve_ledger_path(approvals_ledger_path)
    if path is None:
        return [], "no paper ledger found — approval queue unavailable"
    db = _open_ro(path)
    try:
        if "approvals" not in _tables(db):
            return [], f"ledger {path} has no approvals table"
        rows = [dict(r) for r in db.execute(
            "SELECT id, strategy, symbols, metrics, created_at FROM approvals "
            "WHERE status='pending' ORDER BY created_at DESC")]
    finally:
        db.close()
    queue = []
    for r in rows[: max(int(limit or 0), 0)]:
        try:
            metrics = json.loads(r.get("metrics") or "{}")
        except json.JSONDecodeError:
            metrics = {}
        queue.append({
            "id": r.get("id"), "strategy": r.get("strategy"),
            "symbols": r.get("symbols"),
            "score": (metrics.get("score")
                      if isinstance(metrics, dict) else None),
            "created_at": r.get("created_at"),
        })
    return queue, f"{len(rows)} pending approvals read read-only from {path}"


def run_agent_activity_job(
    track_record_path=None,
    approvals_ledger_path=None,
    limit=50,
) -> dict:
    """Agent activity: leaderboards, Elo curves, Brier calibration, debates.

    Reads the trade-agents v0.2.0 track-record JSONL
    (``proposal`` / ``verdict`` / ``outcome`` / ``risk_forecast`` /
    ``pm_outcome`` events) and scores agents with the engine's own pure
    functions from ``trade_agents.track_record``
    (``score_all``/``debate_weights`` — lazy import).  Debates come from
    the paper ledger's ``approvals`` table (debate synthesis stored under
    ``metrics.chain.debate``); the approval queue is the ledger's pending
    approvals.  Missing files yield graceful empties with an explanatory
    ``message`` — never an error.
    """
    limit = max(int(limit or 0), 0)
    notes: list[str] = []
    path = resolve_track_record_path(track_record_path)
    events: list[dict] = []
    if path is None:
        notes.append("no track-record JSONL found (TRADE_AGENTS_TRACK_RECORD "
                     "or ./trade-agents-track-record.jsonl)")
    else:
        events, bad = _read_jsonl(path)
        notes.append(f"{len(events)} track-record events from {path}"
                     + (f" ({bad} malformed lines skipped)" if bad else ""))
    leaderboards = {"researcher": [], "risk_desk": [], "pm": []}
    if events:
        try:
            tr = _require("trade-agents", "trade_agents.track_record")
        except RuntimeError as exc:
            notes.append(f"leaderboards unavailable: {exc}")
            tr = None
        if tr is not None:
            scored = tr.score_all(events)
            role_key = {"researcher": "researcher", "risk": "risk_desk",
                        "pm": "pm"}
            buckets: dict[str, list[dict]] = {"researcher": [], "risk_desk": [],
                                              "pm": []}
            for label, s in scored.items():
                key = role_key.get(s.get("role"))
                if key:
                    buckets[key].append({**s, "label": label})
            for key, rows in buckets.items():
                weights = tr.debate_weights(
                    {r["label"]: r["score"] for r in rows})
                rows.sort(key=lambda r: r["score"], reverse=True)
                for r in rows[:limit]:
                    r["debate_weight"] = weights.get(r["label"], 0.0)
                    leaderboards[key].append(_jsonable(r))
            notes.append("leaderboards scored with trade-agents track_record "
                         "engine functions")
    elo_curves = _elo_curves(events) if events else {}
    brier = _brier_calibration(events) if events else {
        "bins": [], "observed": [], "n": []}
    debates, dmsg = _debates_from_approvals(approvals_ledger_path, limit)
    notes.append(dmsg)
    queue, qmsg = _approval_queue(approvals_ledger_path, limit)
    notes.append(qmsg)
    return {
        "leaderboards": leaderboards,
        "elo_curves": elo_curves,
        "brier": brier,
        "debates": debates,
        "approval_queue": queue,
        "track_record_path": path,
        "message": "; ".join(notes),
    }

# ---------------------------------------------------------------------------
# 4. Correlation network (MST)
# ---------------------------------------------------------------------------

_MST_CUT = 1.0       # distance cut for single-linkage clusters (see docstring)
_FR_ITERATIONS = 300  # fixed: determinism given the seed
_DEMO_UNIVERSE = ["SPY", "QQQ", "DIA", "IWM", "XLK", "XLF", "XLE", "XLV",
                  "XLI", "XLU", "XLP", "XLY"]


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    den = math.sqrt(sum(a * a for a in dx) * sum(b * b for b in dy))
    if den <= 0:
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(dx, dy)) / den))


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def _correlation_matrix(returns: list[list[float]], method: str) -> list[list[float]]:
    """Sample correlation of per-asset return columns (t×n in).

    Pearson matches the trade-eda definition (correlation of simple daily
    returns); Spearman is Pearson on average ranks (ties averaged).
    """
    cols = [list(c) for c in zip(*returns)]
    if method == "spearman":
        cols = [_ranks(c) for c in cols]
    n = len(cols)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        out[i][i] = 1.0
        for j in range(i + 1, n):
            r = _pearson(cols[i], cols[j])
            out[i][j] = out[j][i] = r
    return out


def _corr_distance(rho: float) -> float:
    """Correlation -> Euclidean distance on the unit sphere: sqrt(2(1-ρ))."""
    rho = max(-1.0, min(1.0, rho))
    return math.sqrt(max(0.0, 2.0 * (1.0 - rho)))


def _kruskal_mst(n: int, dist: list[list[float]]) -> list[tuple[int, int]]:
    """Minimum spanning tree via Kruskal (union-find), deterministic."""
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    edges = sorted(((dist[i][j], i, j) for i in range(n)
                    for j in range(i + 1, n)))
    mst = []
    for _, i, j in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj
            mst.append((i, j))
            if len(mst) == n - 1:
                break
    return mst


def _single_linkage_clusters(n: int, mst: list[tuple[int, int]],
                             dist: list[list[float]],
                             cut: float) -> list[int]:
    """Clusters = connected components of the MST after cutting every edge
    longer than ``cut`` (Gower & Ross: MST single-linkage).  ``cut=1.0``
    keeps edges with ρ >= 0.5 — an arbitrary, documented choice; the
    dashboard shows the cut in the UI so it is never mistaken for a
    discovered structure."""
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, j in mst:
        if dist[i][j] <= cut:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj
    comp = {}
    labels = []
    for i in range(n):
        r = find(i)
        comp.setdefault(r, len(comp))
        labels.append(comp[r])
    return labels


def _fruchterman_reingold(n: int, edges: list[tuple[int, int]],
                          seed: int,
                          iterations: int = _FR_ITERATIONS) -> list[tuple[float, float]]:
    """Seeded Fruchterman-Reingold layout, pure Python.

    Fixed iteration count and a ``random.Random(seed)`` start make the
    layout bit-deterministic for a given seed (documented contract the
    desktop mirror relies on).  Coordinates are normalized to [-100, 100].
    """
    rng = random.Random(seed)
    pos = [(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(n)]
    area, k = 4.0, math.sqrt(4.0 / max(n, 1))
    temp = 1.0
    adj = [[] for _ in range(n)]
    for i, j in edges:
        adj[i].append(j)
        adj[j].append(i)

    def fr(d: float) -> float:
        return k * k / max(d, 1e-9)

    def fa(d: float) -> float:
        return d * d / k

    for _ in range(iterations):
        disp = [[0.0, 0.0] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                d = math.hypot(dx, dy) or 1e-9
                f = fr(d) / d
                disp[i][0] += dx * f
                disp[i][1] += dy * f
                disp[j][0] -= dx * f
                disp[j][1] -= dy * f
        for i, j in edges:
            dx = pos[i][0] - pos[j][0]
            dy = pos[i][1] - pos[j][1]
            d = math.hypot(dx, dy) or 1e-9
            f = fa(d) / d
            disp[i][0] -= dx * f
            disp[i][1] -= dy * f
            disp[j][0] += dx * f
            disp[j][1] += dy * f
        for i in range(n):
            d = math.hypot(disp[i][0], disp[i][1]) or 1e-9
            step = min(d, temp)
            pos[i] = (pos[i][0] + disp[i][0] / d * step,
                      pos[i][1] + disp[i][1] / d * step)
            pos[i] = (max(-2.0, min(2.0, pos[i][0])),
                      max(-2.0, min(2.0, pos[i][1])))
        temp *= 0.96
    return [(x * 50.0, y * 50.0) for x, y in pos]


def _demo_network_series(symbols: list[str], n: int,
                         seed: int) -> dict[str, list[float]]:
    """Seeded synthetic price series with planted sector blocks.

    Symbols sharing a 3-letter sector prefix move together — the MST demo
    shows visible clusters without any real data.
    """
    rng = random.Random(seed)
    n_blocks = max(1, (len(symbols) + 2) // 3)
    factors = [[rng.gauss(0, 0.012) for _ in range(n)]
               for _ in range(n_blocks)]
    out = {}
    for i, s in enumerate(symbols):
        f = factors[i % n_blocks]
        px, series = 100.0, []
        for t in range(n):
            px *= 1.0 + 0.0003 + 0.7 * f[t] + rng.gauss(0, 0.006)
            series.append(px)
        out[s] = series
    return out


def _fetch_network_bars(symbols: list[str], source: str,
                        days: int) -> dict[str, list[float]]:
    """``{symbol: closes}`` for the network job.

    ``source="yfinance"`` pulls daily closes via the trade-data-equities
    engine (lazy); ``source="demo"`` uses seeded synthetic series.
    """
    if source == "demo":
        return _demo_network_series(symbols, max(days, 60), DEMO_SEED)
    if source == "yfinance":
        _require("trade-data-equities", "trade_data_equities")
        from trade_data_equities.providers.yfinance import YFinanceProvider
        from trade_data_equities import EquitiesDataClient
        client = EquitiesDataClient(YFinanceProvider())
        out = {}
        for s in symbols:
            bars = client.get_daily_bars(s, days=days)
            closes = [float(b["close"] if isinstance(b, dict) else b.close)
                      for b in bars]
            if len(closes) >= 30:
                out[s] = closes
        missing = [s for s in symbols if s not in out]
        if missing:
            raise ValueError(f"no usable bars for {', '.join(missing)}")
        return out
    raise ValueError("source must be 'yfinance' or 'demo'")


def _overlay_extract(name: str, value) -> dict | None:
    snap = _snapshot_input(value)
    if snap is None:
        return None
    if name == "regime":
        h = snap.get("hysteresis") or {}
        return {"source": "trade-regime",
                "schema_version": snap.get("schema_version"),
                "conviction": snap.get("conviction"),
                "composite_raw": snap.get("composite_raw"),
                "exposure_scale": snap.get("exposure_scale"),
                "hysteresis_state": h.get("state"),
                "hysteresis_reason": h.get("reason"),
                "missing": snap.get("missing", [])}
    if name == "breadth":
        return {"source": "trade-breadth",
                "schema_version": snap.get("schema_version"),
                "regime": snap.get("regime"),
                "regime_score": snap.get("regime_score"),
                "fragility": snap.get("fragility")}
    if name == "macro":
        return {"source": "trade-macro",
                "schema_version": snap.get("schema_version"),
                "regime": snap.get("regime"),
                "z_score": snap.get("z_score"),
                "ratio_vs_200dma": snap.get("ratio_vs_200dma")}
    return None


def run_network_job(
    symbols=None,
    source="yfinance",
    days=252,
    method="pearson",
    seed=7,
    breadth=None,
    macro=None,
    regime=None,
) -> dict:
    """Correlation-network job: correlation -> MST -> clusters -> layout.

    Pipeline (all stdlib, deterministic given ``seed``):

    1. daily returns per symbol (common length, >= 30 obs);
    2. sample correlation (Pearson, or Spearman = Pearson on ranks) —
       computed by the canonical ``run_correlation_job`` machinery
       (trade-eda) on the real path, stdlib fallback in demo/bare mode;
    3. distance ``d = sqrt(2(1-ρ))`` — the chordal distance of correlation
       on the unit sphere;
    4. minimum spanning tree via Kruskal (union-find);
    5. clusters = single-linkage via the MST, cutting edges longer than
       ``_MST_CUT = 1.0`` (i.e. ρ < 0.5) — an arbitrary documented choice;
    6. seeded Fruchterman-Reingold layout (300 fixed iterations).

    Node size driver: annualized realized volatility.  ``breadth`` /
    ``macro`` / ``regime`` accept snapshot dicts (or JSON paths) conforming
    to their ``schema_version`` contracts; the regime arbiter's conviction
    + hysteresis state is included as the overlay block.  All optional.
    """
    if method not in ("pearson", "spearman"):
        raise ValueError("method must be 'pearson' or 'spearman'")
    days = int(days)
    if days < 30:
        raise ValueError("need >= 30 days")
    seed = int(seed)
    syms = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
    demo = not syms
    if demo:
        syms = list(_DEMO_UNIVERSE)
        series = _demo_network_series(syms, days, seed)
    else:
        if len(syms) < 3:
            raise ValueError("need at least 3 symbols for a network")
        if len(set(syms)) != len(syms):
            raise ValueError("duplicate symbols")
        series = _fetch_network_bars(syms, source, days)
        syms = sorted(series)
    m = min(len(c) for c in series.values())
    closes = {s: series[s][-m:] for s in syms}
    rets = [[closes[s][i] / closes[s][i - 1] - 1.0 for s in syms]
            for i in range(1, m)]
    # Correlation matrix: reuse the canonical run_correlation_job
    # machinery (trade-eda) on the real path.  Demo/bare-stdlib mode keeps
    # the built-in Pearson/Spearman so the job still works with no engine
    # installed.  The MST, clusters, and layout are always computed here.
    corr_source = "stdlib"
    n_obs = len(rets)
    corr = _correlation_matrix(rets, method)
    if not demo:
        try:
            from trade_dashboard_web.engine.research_service import (
                run_correlation_job)
            bar_dicts = {s: [{"close": c} for c in closes[s]] for s in syms}
            rep = run_correlation_job(list(syms), bar_dicts, method=method,
                                      lookback=days)
            rep_syms = list(rep["symbols"])
            order = [rep_syms.index(s) for s in syms]
            mat = rep["correlation"]["matrix"]
            corr = [[float(mat[i][j]) for j in order] for i in order]
            corr_source = "trade-eda"
            n_obs = int(rep["n_obs"])
        except (RuntimeError, ValueError):
            pass  # engine missing or bars too short: stdlib path above
    n = len(syms)
    dist = [[_corr_distance(corr[i][j]) for j in range(n)] for i in range(n)]
    mst = _kruskal_mst(n, dist)
    clusters = _single_linkage_clusters(n, mst, dist, _MST_CUT)
    vols = []
    for j in range(n):
        col = [rets[i][j] for i in range(len(rets))]
        mu = sum(col) / len(col)
        var = sum((x - mu) ** 2 for x in col) / max(len(col) - 1, 1)
        vols.append(math.sqrt(max(var, 0.0)) * math.sqrt(252.0))
    layout = _fruchterman_reingold(n, mst, seed)
    nodes = [{"id": i, "symbol": s, "x": _round(x, 2), "y": _round(y, 2),
              "vol": _round(v, 4), "cluster": c}
             for i, (s, (x, y), v, c)
             in enumerate(zip(syms, layout, vols, clusters))]
    edges = [{"a": i, "b": j, "weight": _round(corr[i][j], 4),
              "distance": _round(dist[i][j], 4)} for i, j in mst]
    comp: dict[int, list[str]] = {}
    for i, c in enumerate(clusters):
        comp.setdefault(c, []).append(syms[i])
    cluster_list = [{"id": c, "members": sorted(m)} for c, m in
                    sorted(comp.items())]
    return _jsonable({
        "nodes": nodes,
        "edges": edges,
        "symbols": syms,
        "correlation": [[_round(v, 4) for v in row] for row in corr],
        "clusters": cluster_list,
        "regime": _overlay_extract("regime", regime),
        "breadth": _overlay_extract("breadth", breadth),
        "macro": _overlay_extract("macro", macro),
        "params": {"source": source, "days": days, "method": method,
                   "seed": seed, "n_obs": n_obs,
                   "correlation_source": corr_source,
                   "mst_cut_distance": _MST_CUT,
                   "mst_cut_note": ("single-linkage cut at d=1.0 "
                                    "(rho>=0.5 kept); arbitrary choice, "
                                    "shown so clusters are not mistaken "
                                    "for discovered structure"),
                   "layout": (f"seeded Fruchterman-Reingold, "
                              f"{_FR_ITERATIONS} iterations, deterministic "
                              f"given seed"),
                   "demo": demo},
    })

# ---------------------------------------------------------------------------
# 5. Risk monitor
# ---------------------------------------------------------------------------

def _demo_risk_positions() -> tuple[list[dict], float]:
    rng = random.Random(DEMO_SEED)
    syms = ["SPY", "QQQ", "AAPL", "MSFT", "TSLA"]
    positions = []
    for i, s in enumerate(syms):
        qty = (i + 1) * 10 * (1 if i % 2 == 0 else -1)
        px = round(100 + rng.uniform(-30, 80), 2)
        positions.append({"symbol": s, "qty": float(qty), "price": px})
    return positions, 100_000.0


def _ledger_positions(db: sqlite3.Connection) -> tuple[list[dict], float | None]:
    """Net positions from fills; mark = last fill price per symbol.

    The ledger carries no live price feed, so the latest fill price is the
    mark (documented approximation — stale the moment the book trades).
    Equity = latest equity_snapshot when present, else None (fractions
    then come back null rather than fabricated).
    """
    fills = [dict(r) for r in db.execute(
        "SELECT symbol, side, quantity, price, filled_at FROM fills "
        "ORDER BY filled_at")]
    qty: dict[str, float] = {}
    mark: dict[str, float] = {}
    for fl in fills:
        sym = str(fl.get("symbol") or "").upper()
        q = float(fl.get("quantity") or 0.0)
        if str(fl.get("side") or "").lower() == "buy":
            qty[sym] = qty.get(sym, 0.0) + q
        else:
            qty[sym] = qty.get(sym, 0.0) - q
        mark[sym] = float(fl.get("price") or 0.0)
    positions = [{"symbol": s, "qty": q, "price": mark[s]}
                 for s, q in sorted(qty.items()) if abs(q) > 1e-12]
    equity = None
    if "equity_snapshots" in _tables(db):
        row = db.execute("SELECT equity FROM equity_snapshots "
                         "ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            equity = float(row[0])
    return positions, equity


def _exposures(positions: list[dict], equity: float | None) -> dict:
    """Net/gross exposure, beta-adjusted delta, Herfindahl.

    Beta approximation, stated honestly: the paper ledger carries no beta
    model, so β = 1.0 is assumed for every name and the beta-adjusted net
    delta equals the raw net delta.  It is reported as a separate field so
    a real beta feed can replace the assumption without a signature change.
    """
    per = []
    for p in positions:
        v = p["qty"] * p["price"]
        per.append({"symbol": p["symbol"], "qty": _round(p["qty"], 4),
                    "price": _round(p["price"], 4),
                    "value": _round(v, 2), "beta": 1.0,
                    "beta_adj_value": _round(v * 1.0, 2)})
    net = sum(p["qty"] * p["price"] for p in positions)
    gross = sum(abs(p["qty"] * p["price"]) for p in positions)
    weights = ([abs(p["qty"] * p["price"]) / gross for p in positions]
               if gross > 0 else [])
    herfindahl = sum(w * w for w in weights)
    ordered = sorted(zip([p["symbol"] for p in positions], weights),
                     key=lambda kv: kv[1], reverse=True)
    top = ordered[0] if ordered else (None, 0.0)

    def frac(x):
        return _round(x / equity, 6) if equity else None

    return {
        "n_positions": len(per),
        "per_symbol": per,
        "net_delta_dollars": _round(net, 2),
        "net_delta_dollars_beta_adj": _round(net, 2),
        "beta_assumption": ("beta=1.0 for every name (ledger carries no beta "
                            "model); beta-adjusted delta equals net delta"),
        "gross_dollars": _round(gross, 2),
        "net_frac": frac(net),
        "gross_frac": frac(gross),
        "herfindahl": _round(herfindahl, 6),
        "largest_position": {"symbol": top[0],
                             "weight": _round(top[1], 4)},
        "equity": _round(equity, 2) if equity else None,
    }


def _vol_regime(db: sqlite3.Connection | None,
                vol_days: int) -> dict:
    """Trailing 21-day annualized realized-vol timeline (equity based)."""
    if db is None or "equity_snapshots" not in _tables(db):
        return {"as_of": [], "vol": [], "window": 21,
                "note": "no equity_snapshots — vol-regime unavailable"}
    rows = [dict(r) for r in db.execute(
        "SELECT at, equity FROM equity_snapshots ORDER BY at")]
    rows = rows[-max(vol_days + 21, 2):]
    if len(rows) < 23:
        return {"as_of": [], "vol": [], "window": 21,
                "note": f"only {len(rows)} snapshots (< 23 needed)"}
    eq = [float(r["equity"]) for r in rows]
    rets = [math.log(eq[i] / eq[i - 1]) for i in range(1, len(eq))
            if eq[i - 1] > 0 and eq[i] > 0]
    as_of, vols = [], []
    for i in range(21, len(rets) + 1):
        w = rets[i - 21:i]
        mu = sum(w) / len(w)
        var = sum((x - mu) ** 2 for x in w) / (len(w) - 1)
        vols.append(_round(math.sqrt(var) * math.sqrt(252.0), 6))
        as_of.append(str(rows[i]["at"]))
    tail = max(vol_days, 1)
    return {"as_of": as_of[-tail:], "vol": vols[-tail:], "window": 21,
            "annualized": True,
            "note": "trailing 21d realized vol of equity, annualized"}


def _volforecast_block(value) -> dict | None:
    """Optional trade-volforecast overlay.

    Accepts the ``to_agent_vol_report`` shape (``realized_vol_21d`` plus
    ``garch``/``har``/``ewma`` forecast lists), leniently.
    """
    snap = _snapshot_input(value)
    if snap is None:
        return None
    block = {"source": snap.get("source", "trade-volforecast"),
             "realized_vol_21d": snap.get("realized_vol_21d")}
    for k in ("garch", "har", "ewma"):
        v = snap.get(k)
        if isinstance(v, list):
            block[k] = [_round(x, 6) if isinstance(x, (int, float)) else x
                        for x in v]
        elif isinstance(v, dict):
            block[k] = _jsonable(v)
    return block


def _kill_switch(hedge_state_path: str | None) -> dict:
    """Kill-switch status from a persisted trade-hedge LoopState.

    ``trade-hedge`` persists its ``LoopState`` via ``state_to_json``
    between scheduled runs; the conventional location is env
    ``TRADE_HEDGE_STATE`` else ``./trade-hedge-state.json``.  Absent ->
    ``"unknown"`` (never assumed safe, never assumed halted).
    """
    path = hedge_state_path
    if not path:
        env = os.environ.get("TRADE_HEDGE_STATE")
        path = env if env else "trade-hedge-state.json"
    p = Path(str(path)).expanduser()
    if not p.exists():
        return {"status": "unknown", "state_path": None,
                "note": ("no trade-hedge state file found "
                         "(TRADE_HEDGE_STATE or ./trade-hedge-state.json)")}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "unknown", "state_path": str(p),
                "note": f"unreadable state file: {exc}"}
    halts = int(state.get("consecutive_halts", 0) or 0)
    return {"status": "halted" if halts > 0 else "active",
            "consecutive_halts": halts,
            "cycles_run": state.get("cycles_run"),
            "last_cycle_ts": state.get("last_cycle_ts"),
            "state_path": str(p)}


def _regime_gauge(value) -> dict | None:
    snap = _snapshot_input(value)
    if snap is None:
        return None
    h = snap.get("hysteresis") or {}
    return {"source": "trade-regime",
            "schema_version": snap.get("schema_version"),
            "conviction": snap.get("conviction"),
            "composite_raw": snap.get("composite_raw"),
            "exposure_scale": snap.get("exposure_scale"),
            "hysteresis_state": h.get("state"),
            "hysteresis_reason": h.get("reason"),
            "prior_conviction": h.get("prior_conviction")}


def run_risk_monitor_job(
    ledger_path=None,
    hedge_state_path=None,
    regime=None,
    vol_days=63,
) -> dict:
    """Risk monitor: exposures, vol regime, kill-switch, conviction gauge.

    Exposures come from ledger fills (net positions, mark = last fill
    price — documented approximation); beta-adjusted delta assumes β=1.0
    per name (the ledger carries no beta model — stated in the payload).
    The vol-regime timeline is trailing 21-day annualized realized vol of
    the equity snapshots; an optional trade-volforecast snapshot adds its
    forecast block (supplied via the ``TRADE_VOLFORECAST_SNAPSHOT`` env var
    — a path to, or inline JSON of, a ``to_agent_vol_report`` dict — since
    the canonical signature carries no volforecast parameter).  Kill-switch
    status reads a persisted trade-hedge ``LoopState`` (``halted`` when
    ``consecutive_halts > 0``), else ``"unknown"``.  The regime block
    carries the arbiter's conviction plus its hysteresis held/updated
    state and reason.
    """
    vol_days = max(int(vol_days or 0), 1)
    path = resolve_ledger_path(ledger_path)
    notes: list[str] = []
    demo = False
    if path is None:
        positions, equity = _demo_risk_positions()
        vol = {"as_of": [], "vol": [], "window": 21,
               "note": "demo mode — no ledger, no vol timeline"}
        demo = True
        notes.append("DEMO — no paper ledger found; synthetic book shown")
        db = None
    else:
        db = _open_ro(path)
        try:
            if "fills" not in _tables(db):
                raise ValueError(f"ledger {path} has no fills table")
            positions, equity = _ledger_positions(db)
            vol = _vol_regime(db, vol_days)
            notes.append(f"{len(positions)} net positions read read-only "
                         f"from {path}")
        finally:
            db.close()
    exposures = _exposures(positions, equity)
    kill = _kill_switch(hedge_state_path)
    notes.append(f"kill-switch: {kill['status']}")
    gauge = _regime_gauge(regime)
    if gauge is None:
        notes.append("no regime snapshot supplied — conviction gauge empty")
    vol_env = os.environ.get("TRADE_VOLFORECAST_SNAPSHOT")
    vol_block = None
    if vol_env:
        try:
            vol_block = _volforecast_block(
                json.loads(vol_env) if vol_env.lstrip().startswith("{")
                else vol_env)
        except (ValueError, json.JSONDecodeError) as exc:
            notes.append(f"volforecast snapshot unreadable: {exc}")
    return _jsonable({
        "exposures": exposures,
        "vol_regime": vol,
        "volforecast": vol_block,
        "kill_switch": kill,
        "regime": gauge,
        "demo": demo,
        "ledger_path": path,
        "message": "; ".join(notes),
    })
