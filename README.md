# trade-suite

The meta-package for the **trade-suite** algorithmic and agentic trading
system: one install for all twelve modules, environment introspection,
end-to-end research workflows, and a unified CLI.

> **Research tooling only.** Backtesting, research, and paper-trading
> software. It does not trade live and it is not investment advice.

## The twelve modules

| Module | Role |
|---|---|
| [trade-data-equities](https://github.com/crieck2010/trade-data-equities) | Market data: stocks & ETFs (delayed) |
| [trade-data-options](https://github.com/crieck2010/trade-data-options) | Market data: options chains, pricing, Greeks |
| [trade-data-futures](https://github.com/crieck2010/trade-data-futures) | Market data: futures contracts & term structure |
| [trade-data-crypto](https://github.com/crieck2010/trade-data-crypto) | Market data: crypto spot / perpetuals |
| [trade-backtest](https://github.com/crieck2010/trade-backtest) | Event-driven backtesting engine |
| [trade-strategies](https://github.com/crieck2010/trade-strategies) | Strategy library (19 strategies, 7 families) |
| [trade-risk](https://github.com/crieck2010/trade-risk) | Risk limits, sizers, drawdown guards |
| [trade-agents](https://github.com/crieck2010/trade-agents) | Agentic research desk (scouts → portfolio manager → risk manager) |
| [trade-paper](https://github.com/crieck2010/trade-paper) | Paper-trading execution engine (Alpaca paper, 3×-daily runner, approval queue) |
| [trade-sentiment](https://github.com/crieck2010/trade-sentiment) | Social/news sentiment engine (Reddit, StockTwits, news RSS; feeds the agents' `sentiment_scout`) |
| [trade-dashboard-web](https://github.com/crieck2010/trade-dashboard-web) | Web dashboard |
| [trade-dashboard-desktop](https://github.com/crieck2010/trade-dashboard-desktop) | Desktop dashboard (tkinter) |

Design principles across the suite: pure-logic engines with no UI imports,
stdlib-only cores, lazy cross-module adapters, deterministic demo data so
everything works offline, semantic versioning, MIT licensing.

## Installation

Requires Python 3.10+ and git.

```bash
# everything at once
pip install git+https://github.com/crieck2010/trade-suite.git

# or module by module
pip install -r requirements.txt

# optional: real delayed equity data (demo data works without it)
pip install yfinance
```

On Linux, the desktop dashboard needs tkinter: `sudo apt install python3-tk`
(or the equivalent for your distro). It ships with standard CPython on
Windows and macOS.

## Quickstart

```bash
# what's installed?
trade-suite status

# diagnose the environment
trade-suite doctor

# run the agent desk on demo data (no network, no API keys)
trade-suite demo --symbols SPY,AAPL --days 250

# backtest a strategy
trade-suite backtest --strategy donchian_breakout --symbols SPY \
    --params entry=20,exit=10 --source demo --days 250

# scan social/news sentiment pops (Reddit, StockTwits, news RSS)
trade-suite sentiment --symbols SPY,AAPL,NVDA --window-hours 24

# paper-trading overview (paper only, never live)
trade-suite paper --config paper-config.json

# launch a dashboard
trade-suite launch web
trade-suite launch desktop

# or as a module
python -m trade_suite status
```

## Python API

```python
from trade_suite import env, pipeline
from trade_suite import data

# environment introspection
print(env.status_table())          # ✓/✗ per module with versions
missing = env.missing_modules()    # what isn't installed
trade_backtest = env.require("trade-backtest")  # import or helpful error

# market data (demo always works; "equities" needs trade-data-equities + yfinance)
bars = data.get_bars("SPY", source="demo", days=250)

# end-to-end workflows (plain-data in, plain-data out)
report = pipeline.run_desk(["SPY", "AAPL"], source="demo", days=250)
print(pipeline.summarize_desk(report))

result = pipeline.run_backtest("donchian_breakout", ["SPY"],
                               {"entry": 20, "exit": 10}, source="demo")
print(pipeline.summarize_backtest(result))

review = pipeline.evaluate_orders(
    [{"symbol": "SPY", "side": "buy", "quantity": 10, "price": 580.0}],
    limits=[["max_position_notional", {"max_pct": 0.10}]])
print(len(review["approved"]), "approved,", len(review["vetoed"]), "vetoed")

# desk -> backtest -> risk review in one call
out = pipeline.research_pipeline(["SPY"], backtest_strategy="donchian_breakout")

# social/news sentiment pops (trade-sentiment engine)
scan = pipeline.sentiment_scan(["SPY", "NVDA"], window_hours=24)
print(pipeline.summarize_sentiment(scan))
```

See `examples/end_to_end_demo.py` for a runnable script.

## Project structure

```
trade-suite/
├── src/trade_suite/
│   ├── __init__.py / __main__.py  # version, module entry point
│   ├── env.py                     # module registry + introspection
│   ├── data.py                    # get_bars via dashboard DataService
│   ├── pipeline.py                # run_backtest / run_desk /
│   │                              # evaluate_orders / research_pipeline
│   ├── cli.py                     # trade-suite command line
│   ├── licensing.py               # license-key check hook
│   └── updates.py                 # GitHub-releases update-check hook
├── examples/end_to_end_demo.py
├── tests/                         # 28 tests
├── docs/ARCHITECTURE.md
├── requirements.txt               # one-line-per-module install
├── CHANGELOG.md / LICENSE (MIT)
└── pyproject.toml                 # git-URL dependencies for all 11 modules
```

## Interoperability & scaling notes

- **One registry, derived everywhere.** `env.MODULES` is the single source
  of truth for module names, import paths, roles, and repo URLs; the
  `pyproject.toml` dependencies, `requirements.txt`, CLI `status`, and this
  README's table all derive from the same list.
- **No hard imports at package import time.** `import trade_suite` never
  imports a sibling; every workflow resolves its dependencies lazily and
  raises an error that names the exact `pip install` command for what's
  missing. Partial installs stay usable.
- **One engine, three consumers.** `pipeline` and `data` delegate to the
  shared dashboard-engine services (`trade_dashboard_web.engine` first,
  `trade_dashboard_desktop.engine` fallback), so a scripted workflow, the
  web dashboard, and the desktop dashboard produce identical results for
  the same inputs.
- **Plain data across boundaries.** Workflows return dicts/lists, never
  engine objects, so results serialize, log, and cross process boundaries
  cleanly — the seam where a future task queue or service split would attach.
- **Demo data everywhere.** Every workflow runs fully offline on
  deterministic synthetic data; real delayed data is an opt-in source, never
  a requirement.

## Windows packaging

`trade-suite` is a library/meta-package, so it ships no `.exe` of its own —
the distributables are the two dashboards, which each carry their own
PyInstaller single-file build (`build.py` / `build_exe.bat`) and Inno Setup
installer (`installer.iss`). Install this meta-package on Windows with
`pip install git+https://github.com/crieck2010/trade-suite.git` and launch
either dashboard from the `trade-suite launch` command.

## Monetization hooks

- **License keys** (`trade_suite/licensing.py`): community mode by default;
  `TS-XXXX-XXXX-XXXX` keys stored in `~/.trade_suite/license.key`, offline
  format check. Validate against a merchant of record (Gumroad / Lemon
  Squeezy) before gating premium features.
- **Update checks** (`trade_suite/updates.py`): compares against the latest
  GitHub release; stdlib only, degrades gracefully offline.
- Payments, when added, go through a merchant of record — never custom
  billing code.

## Testing

```bash
# connected (all siblings on the path)
PYTHONPATH=src:../trade-dashboard-web/src:../trade-dashboard-desktop/src:\
../trade-data-equities/src:../trade-data-options/src:../trade-data-futures/src:\
../trade-data-crypto/src:../trade-backtest/src:../trade-strategies/src:\
../trade-risk/src:../trade-agents/src:../trade-sentiment/src \
  python -m pytest tests/ -q
```

38 tests. Sibling-dependent tests use `pytest.importorskip`, so the suite
also runs (partially skipped) against a bare install.

## Changelog / License

See [CHANGELOG.md](CHANGELOG.md). MIT — see [LICENSE](LICENSE).
