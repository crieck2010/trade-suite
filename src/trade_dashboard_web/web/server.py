"""Dependency-free web server (stdlib ``http.server``).

JSON API:
    GET  /api/health
    GET  /api/sources
    GET  /api/strategies
    GET  /api/bars?symbol=SPY&source=demo&days=365
    POST /api/backtest   {strategy, symbols[], params{}, source, initial_cash}
    POST /api/desk       {symbols[], equity, source}
    GET  /api/risk/limits
    POST /api/risk/evaluate  {orders[], limits[[name, params]], equity}
    GET  /api/paper/status?config=paper-config.json
    GET  /api/paper/approvals?config=&status=pending
    POST /api/paper/approve  {config, id, reason}
    GET  /api/paper/fidelity?config=paper-config.json
    POST /api/research/pairs        {symbols[], source, days, lookback, max_pairs}
    POST /api/research/orderbook    {symbol, side, quantity, order_type, levels}
    POST /api/research/optimize     {symbols[], source, days, method, max_weight}
    POST /api/research/montecarlo   {symbols[], weights[], source, days, equity, paths, steps, seed}
    POST /api/research/factors      {symbols[], source, days, model, months}
    POST /api/research/sentiment-price {symbol, source, days}
         (alias: /api/research/sentiment)
    POST /api/research/volsurface   {symbol, spot, risk_free}
    POST /api/research/correlation  {symbols[], source, days, method, shrinkage, lookback}
    POST /api/research/breadth      {preset, seed, days, thrust_window}
    POST /api/research/macro        {preset, seed, days}
    POST /api/research/reconcile-demo  {}  (demo only: mock MCP broker)
    GET  /api/stream/latest        latest demo-stream prices per symbol
    GET  /api/trades               trade blotter (query-string filters)
    GET  /api/trades/export        same filters, CSV download
    POST /api/performance          {source, ledger_path, backtest, backtest_path, risk_free}
    POST /api/agents/activity      {track_record_path, approvals_ledger_path, limit}
    POST /api/network              {symbols[], source, days, method, seed, breadth, macro, regime}
    POST /api/risk/monitor         {ledger_path, hedge_state_path, regime, vol_days}

The single-page UI is served from ``web/static/``.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..engine import (
    DataService,
    describe_limits,
    evaluate_orders_job,
    list_strategies,
    paper_approvals,
    paper_approve,
    paper_available,
    paper_fidelity,
    paper_status,
    run_backtest_job,
    run_breadth_job,
    run_correlation_job,
    run_desk_job,
    run_factor_analysis_job,
    run_macro_job,
    run_montecarlo_job,
    run_network_job,
    run_optimize_job,
    run_orderbook_job,
    run_pairs_job,
    run_performance_job,
    run_reconcile_demo_job,
    run_risk_monitor_job,
    run_sentiment_price_job,
    run_vol_surface_job,
    run_agent_activity_job,
    run_trades_job,
    trades_to_csv,
)

STATIC_DIR = Path(__file__).parent / "static"

# -- demo stream session ------------------------------------------------------
#
# A module-level lazily-started trade-stream session feeds
# ``GET /api/stream/latest``.  Started on the first request: a StreamSession
# with ``source="demo"`` over three demo symbols, with a LatestPriceCache
# attached to its bus as the read model for latest prices.
#
# The demo feed is finite (600 ticks), so the session's reconnect policy
# (balanced, unlimited attempts) re-creates the feed on exhaustion — a fresh
# generator is built on every restart with a monotonically increasing
# ``start_ts`` offset, keeping cache timestamps fresh so the session runs
# indefinitely.  Startup is guarded by a module lock and the cache is
# thread-safe, so concurrent requests are safe.  The background thread is a
# daemon and dies with the process.
_STREAM_SYMBOLS = ("AAA", "BBB", "CCC")
_stream_lock = threading.Lock()
_stream_session = None
_stream_cache = None


def _demo_stream_session():
    """Return the (session, price cache) singleton, starting it on first use."""
    global _stream_session, _stream_cache
    with _stream_lock:
        if _stream_session is None:
            try:
                import trade_stream
            except ImportError as exc:
                raise RuntimeError(
                    "trade-stream is not installed; install it with "
                    "`pip install git+https://github.com/crieck2010/trade-stream.git`"
                ) from exc
            batch = {"n": 0}

            def _feed():
                batch["n"] += 1
                return trade_stream.demo.demo_feed(
                    symbols=_STREAM_SYMBOLS, seed=7,
                    start_ts=(trade_stream.demo.BASE_TS + batch["n"] * 10_000.0))

            bus = trade_stream.MessageBus()
            _stream_cache = trade_stream.LatestPriceCache(bus)
            _stream_session = trade_stream.StreamSession(
                source="demo", symbols=list(_STREAM_SYMBOLS), bus=bus,
                transport=trade_stream.DemoTransport(_feed))
            _stream_session.start()
        return _stream_session, _stream_cache


class _Handler(BaseHTTPRequestHandler):
    data_service: DataService = DataService()

    # -- helpers ---------------------------------------------------------
    def _json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status=status)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc

    def log_message(self, fmt, *args):  # quieter logs
        pass

    def _csv(self, filename: str, text: str) -> None:
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _trade_filters(self, query: dict) -> dict:
        get = lambda k, d="": query.get(k, [d])[0]
        return {
            "ledger_path": get("ledger_path") or None,
            "date_from": get("date_from") or None,
            "date_to": get("date_to") or None,
            "symbol": get("symbol") or None,
            "side": get("side") or None,
            "strategy": get("strategy") or None,
            "agent": get("agent") or None,
            "outcome": get("outcome") or None,
            "limit": int(get("limit", "500") or 500),
        }

    # -- routing ----------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        try:
            if path == "/api/health":
                return self._json({"ok": True, "version": __version__})
            if path == "/api/sources":
                return self._json(self.data_service.sources())
            if path == "/api/strategies":
                return self._json(list_strategies())
            if path == "/api/bars":
                bars = self.data_service.get_bars(
                    query.get("symbol", [""])[0],
                    source=query.get("source", ["demo"])[0],
                    days=int(query.get("days", ["365"])[0]),
                )
                return self._json({"symbol": query["symbol"][0].upper(), "bars": bars})
            if path == "/api/risk/limits":
                return self._json(describe_limits())
            if path == "/api/paper/status":
                return self._json(paper_status(query.get("config", [""])[0]))
            if path == "/api/paper/approvals":
                return self._json(paper_approvals(
                    query.get("config", [""])[0],
                    status=query.get("status", ["pending"])[0]))
            if path == "/api/paper/fidelity":
                return self._json(paper_fidelity(query.get("config", [""])[0]))
            if path == "/api/stream/latest":
                return self._json(self._stream_latest())
            if path == "/api/trades":
                return self._json(run_trades_job(**self._trade_filters(query)))
            if path == "/api/trades/export":
                result = run_trades_job(**self._trade_filters(query))
                return self._csv("trades.csv", trades_to_csv(result))
            return self._serve_static(path)
        except (ValueError, KeyError, RuntimeError) as exc:
            return self._error(str(exc), 400)
        except Exception as exc:  # pragma: no cover - defensive
            return self._error(f"internal error: {exc}", 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = self._read_json()
            if path == "/api/backtest":
                return self._json(self._backtest(body))
            if path == "/api/desk":
                return self._json(self._desk(body))
            if path == "/api/risk/evaluate":
                return self._json(
                    evaluate_orders_job(
                        body.get("orders", []),
                        limits=body.get("limits"),
                        equity=float(body.get("equity", 100_000.0)),
                    )
                )
            if path == "/api/paper/approve":
                return self._json(paper_approve(
                    body.get("config", ""),
                    int(body.get("id", 0)),
                    reason=body.get("reason", "")))
            if path == "/api/performance":
                return self._json(run_performance_job(
                    source=body.get("source", "paper"),
                    ledger_path=body.get("ledger_path"),
                    backtest=body.get("backtest"),
                    backtest_path=body.get("backtest_path"),
                    risk_free=float(body.get("risk_free", 0.0))))
            if path == "/api/agents/activity":
                return self._json(run_agent_activity_job(
                    track_record_path=body.get("track_record_path"),
                    approvals_ledger_path=body.get("approvals_ledger_path"),
                    limit=int(body.get("limit", 50))))
            if path == "/api/network":
                return self._json(run_network_job(
                    symbols=body.get("symbols"),
                    source=body.get("source", "yfinance"),
                    days=int(body.get("days", 252)),
                    method=body.get("method", "pearson"),
                    seed=int(body.get("seed", 7)),
                    breadth=body.get("breadth"),
                    macro=body.get("macro"),
                    regime=body.get("regime")))
            if path == "/api/risk/monitor":
                return self._json(run_risk_monitor_job(
                    ledger_path=body.get("ledger_path"),
                    hedge_state_path=body.get("hedge_state_path"),
                    regime=body.get("regime"),
                    vol_days=int(body.get("vol_days", 63))))
            if path.startswith("/api/research/"):
                return self._json(self._research(path.rsplit("/", 1)[1], body))
            return self._error(f"unknown endpoint {path}", 404)
        except (ValueError, KeyError, RuntimeError) as exc:
            return self._error(str(exc), 400)
        except Exception as exc:  # pragma: no cover - defensive
            return self._error(f"internal error: {exc}", 500)

    # -- endpoints ---------------------------------------------------------
    def _backtest(self, body: dict) -> dict:
        symbols = [s.strip().upper() for s in body.get("symbols", []) if s.strip()]
        source = body.get("source", "demo")
        bars: list = []
        for symbol in symbols:
            bars.extend(
                self.data_service.get_bars(
                    symbol, source=source, days=int(body.get("days", 365))
                )
            )
        return run_backtest_job(
            body.get("strategy", ""),
            symbols,
            body.get("params") or {},
            bars,
            initial_cash=float(body.get("initial_cash", 100_000.0)),
        )

    def _desk(self, body: dict) -> dict:
        symbols = [s.strip().upper() for s in body.get("symbols", []) if s.strip()]
        source = body.get("source", "demo")
        bars_by_symbol = {
            s: self.data_service.get_bars(s, source=source, days=int(body.get("days", 365)))
            for s in symbols
        }
        return run_desk_job(
            symbols, bars_by_symbol, equity=float(body.get("equity", 100_000.0))
        )

    def _bars_many(self, body: dict, default_days: int = 365) -> tuple[list[str], dict[str, list]]:
        symbols = [s.strip().upper() for s in body.get("symbols", []) if s.strip()]
        source = body.get("source", "demo")
        days = int(body.get("days", default_days))
        return symbols, {
            s: self.data_service.get_bars(s, source=source, days=days)
            for s in symbols
        }

    def _research(self, name: str, body: dict) -> dict:
        if name == "pairs":
            symbols, bars = self._bars_many(body)
            return run_pairs_job(symbols, bars,
                                 lookback=int(body.get("lookback", 252)),
                                 max_pairs=int(body.get("max_pairs", 10)))
        if name == "orderbook":
            return run_orderbook_job(
                symbol=body.get("symbol", "DEMO"), side=body.get("side", "buy"),
                quantity=float(body.get("quantity", 100.0)),
                order_type=body.get("order_type", "market"),
                n_levels=int(body.get("levels", 5)))
        if name == "optimize":
            symbols, bars = self._bars_many(body)
            return run_optimize_job(symbols, bars,
                                    method=body.get("method", "max_sharpe"),
                                    max_weight=float(body.get("max_weight", 1.0)))
        if name == "montecarlo":
            symbols, bars = self._bars_many(body)
            weights = body.get("weights") or None
            return run_montecarlo_job(
                symbols, bars,
                weights=[float(w) for w in weights] if weights else None,
                equity=float(body.get("equity", 100_000.0)),
                n_paths=int(body.get("paths", 5_000)),
                n_steps=int(body.get("steps", 252)),
                seed=int(body.get("seed", 7)))
        if name == "factors":
            symbols, bars = self._bars_many(body, default_days=750)
            return run_factor_analysis_job(
                symbols, bars, model=body.get("model", "ff5"),
                n_months=int(body.get("months", 60)))
        if name in ("sentiment", "sentiment-price"):
            symbol = (body.get("symbol") or "").strip().upper()
            return run_sentiment_price_job(
                symbol, days=int(body.get("days", 180)))
        if name == "volsurface":
            return run_vol_surface_job(
                symbol=body.get("symbol", "SPY"),
                spot=body.get("spot"),
                risk_free=float(body.get("risk_free", 0.03)))
        if name == "correlation":
            symbols, bars = self._bars_many(body)
            return run_correlation_job(
                symbols, bars,
                method=body.get("method", "pearson"),
                shrinkage=body.get("shrinkage", "ledoit_wolf"),
                lookback=int(body.get("lookback", 252)))
        if name == "breadth":
            return run_breadth_job(
                preset=body.get("preset", "standard"),
                seed=int(body.get("seed", 7)),
                n_days=int(body.get("days", 600)),
                thrust_window=int(body.get("thrust_window", 10)))
        if name == "macro":
            return run_macro_job(
                preset=body.get("preset", "standard"),
                seed=int(body.get("seed", 42)),
                days=int(body.get("days", 600)))
        if name == "reconcile-demo":
            return run_reconcile_demo_job()
        raise KeyError(f"unknown research job {name!r}")

    def _stream_latest(self) -> dict:
        """Latest prices per symbol from the demo stream session.

        Starts the module-level session on first call; waits briefly for the
        first batch of ticks to land in the cache.
        """
        _session, cache = _demo_stream_session()
        prices = cache.as_dict()
        deadline = time.time() + 2.0
        while not prices and time.time() < deadline:
            time.sleep(0.05)
            prices = cache.as_dict()
        return {"demo": True, "source": "trade-stream",
                "symbols": list(_STREAM_SYMBOLS), "prices": prices}

    # -- static files -------------------------------------------------------
    def _serve_static(self, path: str):
        if path in ("/", ""):
            rel = "index.html"
        elif path.startswith("/static/"):
            rel = path[len("/static/"):]
        else:
            return self._error("not found", 404)
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return self._error("not found", 404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _Handler)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = create_server(host, port)
    print(f"trade-dashboard-web v{__version__} on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
