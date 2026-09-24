# trade-suite

The meta-package for the **trade-suite** algorithmic and agentic trading
system: one install for all twenty modules, environment introspection,
end-to-end research workflows, and a unified CLI.

> **Research tooling only.** Backtesting, research, and paper-trading
> software. It does not trade live and it is not investment advice.

## The twenty modules

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
| [trade-pairs](https://github.com/crieck2010/trade-pairs) | Pairs trading: cointegration screen, hedge ratios, signals |
| [trade-orderbook](https://github.com/crieck2010/trade-orderbook) | Limit-order-book simulator and execution analytics |
| [trade-optimize](https://github.com/crieck2010/trade-optimize) | Markowitz portfolio optimization and rebalancing |
| [trade-montecarlo](https://github.com/crieck2010/trade-montecarlo) | Monte Carlo simulation: VaR/CVaR, drawdowns, scenarios |
| [trade-volsurface](https://github.com/crieck2010/trade-volsurface) | Volatility surfaces: SVI fits, arbitrage checks, local vol |
| [trade-factors](https://github.com/crieck2010/trade-factors) | Factor analysis: Fama-French regressions, GRS, risk models |
| [trade-sentiment-vs-price](https://github.com/crieck2010/trade-sentiment-vs-price) | Sentiment vs price: lead/lag, event studies, IC, indicators |
| [trade-eda](https://github.com/crieck2010/trade-eda) | Correlation/covariance/EDA: Pearson/Spearman matrices, Ledoit-Wolf shrinkage, summary stats, data quality |
| [trade-dashboard-web](https://github.com/crieck2010/trade-dashboard-web) | Web dashboard |
| [trade-dashboard-desktop](https://github.com/crieck2010/trade-dashboard-desktop) | Desktop dashboard (tkinter) |
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

# --- research lab: the seven new quant engines, all demo-capable ---
# screen a universe for cointegrated pairs
trade-suite pairs --symbols SPY,QQQ,AAPL,MSFT,NVDA --max-pairs 10

# simulate an order against a seeded limit-order book
trade-suite orderbook --side buy --quantity 120

# optimize a long-only portfolio (max_sharpe | min_variance | risk_parity | equal_weight)
trade-suite optimize --symbols SPY,AAPL,MSFT --method max_sharpe

# simulated portfolio VaR/CVaR over correlated GBM paths
trade-suite montecarlo --symbols SPY,AAPL --paths 5000 --steps 252

# Fama-French factor regressions + GRS joint-alpha test
trade-suite factors --symbols SPY,AAPL --model ff5

# sentiment-vs-price verdict bundle (lead/lag, IC, event study)
trade-suite sentiment-price --symbol SPY

# SVI volatility surface fit (demo quotes; real chains via the engine)
trade-suite volsurface --symbol SPY

# correlation/EDA report: matrix, shrunk covariance, stats, data quality
trade-suite correlate --symbols SPY,QQQ,IWM,DIA

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

# --- research lab: one thin workflow per new engine ---
pairs = pipeline.run_pairs_screen(["SPY", "QQQ", "AAPL", "MSFT", "NVDA"])
print(pipeline.summarize_pairs(pairs))

sim = pipeline.run_orderbook_sim(side="buy", quantity=120.0)
print(pipeline.summarize_orderbook(sim))

opt = pipeline.run_optimize(["SPY", "AAPL", "MSFT"], method="max_sharpe")
print(pipeline.summarize_optimize(opt))

mc = pipeline.run_montecarlo(["SPY", "AAPL"], n_paths=5_000, n_steps=252)
print(pipeline.summarize_montecarlo(mc))

fac = pipeline.run_factor_analysis(["SPY", "AAPL"], model="ff5")
print(pipeline.summarize_factors(fac))

svp = pipeline.run_sentiment_price("SPY")
print(pipeline.summarize_sentiment_price(svp))

vs = pipeline.run_vol_surface(symbol="SPY")
print(pipeline.summarize_volsurface(vs))

# enrich the desk pipeline with sentiment-vs-price + factor exposures
out = pipeline.research_pipeline(["SPY"], sentiment_price=True, factor_model="ff5")
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

## The maths

**What you learn.** How numbers flow across the whole system: the desk
scores ideas, the portfolio manager weights them, the risk manager vetoes,
the backtester prices the survivors, and the research enrichments
(sentiment, factors) attach their verdicts — all as plain data through one
pipeline call.

**Why it matters.** The meta-package's value is composability, and
composability is a quantitative claim: a scripted workflow, the web
dashboard, and the desktop dashboard must produce *identical* results for
identical inputs. That holds because `pipeline` and `data` delegate to one
shared dashboard-engine service layer instead of reimplementing the maths
three times.

**The maths.**

- *Research pipeline* (`pipeline.research_pipeline`): `run_desk` →
  optional `run_backtest(strategy)` → `evaluate_orders(desk.approved_orders)`
  — desk research, strategy backtest, and risk review in one call, returning
  `{"desk": …, "backtest": …|None, "risk": …}` plus enrichment keys.
- *Desk economics* (via trade-agents): scout ideas scored as
  `sharpe × min(1, n_trades/10) − 1.5 × max_drawdown`, allocated with
  inverse-volatility weights `w_i ∝ 1/vol_i` (score-weighted fallback),
  regime-tilted, capped, renormalized — then risk-vetoed before any order
  is approved.
- *Backtest loop* (via trade-backtest): event-driven, no lookahead (signals
  at bar *t* fill at bar *t+1*'s open), adverse slippage in bps, FIFO
  accounting, Sharpe/Sortino/max-drawdown/Calmar panel on simple returns.
- *Risk review* (via trade-risk): order intents re-checked against the
  limit stack — first veto wins, exits never blocked.
- *Enrichments* (opt-in): `sentiment_price=True` attaches a per-symbol
  sentiment-vs-price verdict (lead/lag, information coefficient, event
  study); `factor_model="ff5"` attaches Fama-French regressions plus the
  GRS joint-alpha test, fetching 750 days of bars to clear the 24-month
  regression floor.
- *Plain-data boundaries*: every workflow returns dicts/lists, never engine
  objects — results serialize, log, and cross process boundaries cleanly,
  which is where a future task queue or service split attaches.

**Honest limitations.**

- Demo data is synthetic and regime-clean; every number it produces is a
  plumbing check, not evidence.
- Workflows are only as complete as the installed modules — partial installs
  degrade to clear "pip install …" errors rather than wrong answers.
- The web dashboard runs jobs inline (no task queue yet), so heavy sweeps
  block the server; the desktop dashboard runs them in background threads.
- Sentiment and factor enrichments inherit their engines' demo caveats
  (synthetic sentiment with a planted lead; synthetic factor dates).

## Changelog / License

See [CHANGELOG.md](CHANGELOG.md). MIT — see [LICENSE](LICENSE).
