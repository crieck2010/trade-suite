# Changelog

All notable changes to `trade-suite` are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and versioning follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `trade_dashboard_app`: Streamlit-first Broker-Grade Agentic Trading Dashboard
  (v1.1.0). Implements the command center architecture specified in
  `Trading_Dashboard_Architecture_Spec_v1.1.0.md` and
  `Dashboard_Features_Specification.md`:
  - **Zero-Scroll Hero Metrics Bar**: Real-time Net Liquidity, Day P&L,
    YTD P&L, Buying Power with margin utilization, Beta-Weighted Delta (SPY),
    and VIX level.
  - **Tab 1: Global Macro & P&L**: Macro regime indicator (copper:gold ratio,
    z-score, MA200 trend, Benner Cycle phase), Levenson framework asset
    allocation (Real Assets vs. Equities vs. Cash), active positions grid
    strictly formatted for 100-share round lots and spread legs with live Greeks.
  - **Tab 2: Agent Visualizer (The Orchestrator's Brain)**: Live LangGraph
    cyclic state DAG topology (Mattermost Ingest -> Node A Orchestrator ->
    Node B Dispatcher -> Node C Worker Pool -> Node D Review), BusinessState
    dictionary inspector, live debate transcript stream (trade_agents v0.2.0),
    agent reputation leaderboard (realized OOS Sharpe with clawback decay),
    and local hardware inference metrics (M3 Ultra 512GB, VRAM context cache,
    tokens/sec).
  - **Tab 3: Master Execution Blotter**: Order audit blotter with algorithmic
    rationale tracking and expected vs. actual fill slippage fidelity checks.
  - **Tab 4: Strategy & Walk-Forward Validation**: Deflated Sharpe Ratio
    (DSR) validation telemetry (Bailey & de Prado), 13-fold walk-forward
    consistency matrix, and Tier-1 pre-registration gate accounting.
  - **Tab 5: Risk Controls & The "E-Stop"**: Physical-style emergency Kill
    Switch halting order execution, human-in-the-loop proposal staging with
    approval/rejection audit trail, hyper-gamma 0DTE threshold alerts, and
    trade_hedge auto-hedging loop status.
  - **Tab 6: 0DTE Options & Volatility Surface (`tab6_options_surface.py`)**:
    Real-time Expected Move (EM) decay monitor integrating
    `trade_data_options.em_decay` against the pre-registered 83.0% entry
    threshold; tail-risk calendar conditioning gate (`trade_macro.skip_days`)
    tracking FOMC decisions, monthly OpEx, and month-end flows; pre-registered
    0DTE Iron-Fly strike and wing geometry (`50 -> 20` schedule, multiples of 5,
    $\le 30\%$ account risk cap); and variance risk premium spread ($IV_{0DTE} - RV$)
    with VIX / VIX3M term structure contango/backwardation curve.
  - **Tab 7: Portfolio Stress Testing & Scenarios (`tab7_stress_test.py`)**:
    Macro shock simulation engine (`stress_service.py`) supporting simultaneous
    $\Delta SPX$ (%), $\Delta VIX$ (pts), and $\Delta 10Y$ Treasury yield (bps)
    shocks; Taylor expansion decomposition across equities, duration (TLT), and
    0DTE options spreads; non-linear hyper-gamma surge curves across spot moves;
    automated hedge generation via `trade_hedge` rules (`delta_trim_rule`) with
    one-click staging to desk; and historical stress presets (2020 COVID Crash,
    2022 Correlated Bond-Equity Crash, 0DTE Gamma Squeeze, Melt-Up).
  - **Master Audit Logging (`audit_service.py`)**: Thread-safe, atomic
    append-only audit log (`audit_log.json`) recording all manual overrides.
  - **Strict Engine/UI Separation**: Zero trading logic or raw calculations in
    UI components; pure presentation delegating to typed service layer with
    fail-soft fallback handlers when engines or offline.
  - Packaging-ready for PyInstaller + pywebview Windows `.exe` desktop wrapping.
  - 7 comprehensive unit tests (`tests/test_dashboard_app.py`) covering all
    services, data contracts, atomic audit logging, 0DTE EM decay, skip days,
    stress testing, and risk controls.
  - Registered console script `trade-dashboard-app` in `pyproject.toml`.
- `trade_data_options.providers.ThetaDataOptionsProvider`: EOD options
  chains via a local ThetaData Terminal (v3) — stdlib `urllib` only, zero
  new dependencies, no credentials in code (the terminal authenticates
  itself). Implements the `OptionsDataProvider` ABC (`get_expiries`,
  `get_chain`, `get_underlying_price`) against the documented v3
  endpoints (`/v3/option/list/expirations`,
  `/v3/option/history/eod`, `/v3/stock/history/eod`); configurable
  `base_url`, client-side rate-limit guard (default 25/min, conservative
  under the free tier's 30), clear errors when the terminal is down
  (never silent empty chains), European style for index underlyings
  (SPX/SPXW/NDX/RUT/XSP). Module docstring documents free-tier
  capabilities (EOD chains from 2023-06-01, 1-day delay) vs paid-tier
  needs (intraday bars). 15 new tests
  (`tests/test_data_options_thetadata.py`), all fixture-based (no
  network). README "ThetaData options data" setup section.
- `trade_data_options.em_decay`: EM-decay entry trigger — a pure-stdlib
  timing filter on premium decay (current ATM straddle as a fraction of the
  opening EM). `em_decay()`, `em_decay_from_expected_move()` (takes an
  `ExpectedMove`), `decay_trigger()` and frozen `DecayTrigger`; default
  threshold 0.83 is the PRE-REGISTERED HYPOTHESIS VALUE from the source
  video, explicitly not a tuned optimum. Module docstring states "a
  trigger, not an edge" — the edge claim lives in the hypothesis doc.
- `trade_strategies/research/0dte-em-decay-ironfly.md`: pre-registered
  hypothesis doc with the FULL frozen rule set (83% EM-decay entry, iron-fly
  structure, 50→20 wing schedule, ±(credit−5) adds, cut at credit distance,
  FOMC/OpEx/month-end skip days, ≤30% account / ≤1% per-fly sizing),
  validation plan (Tier-1, DSR trial accounting via trade-multitest from
  day one), data requirement (ThetaData intraday SPX NBBO), and 1C recorded
  as blocked on data + NBBO fill engine.
- 20 new tests (`tests/test_data_options_em_decay.py`): hand-computed decay
  fractions, threshold boundary (0.8301 vs 0.8299), invalid inputs,
  ExpectedMove integration.
- `trade_macro.skip_days`: skip-day conditioning — tail-risk-day research
  filter for short-premium work (FOMC announcement days, monthly
  options-expiration days, month-end). Pure stdlib calendar read, no data,
  no look-ahead, no fitted parameters.
  - `SkipCalendar` (frozen): shipped static FOMC announcement list (23
    dates covering 2025/2026/announced-2027; quarterly refresh cadence
    documented; the field is the adapter slot for a future Fed-calendar
    feed); `opex_rule="third_friday"` default with the source video's
    third-Wednesday claim kept configurable (discrepancy recorded in the
    docstring); `month_end=True`.
  - `is_skip_day(d, calendar, trading_days=None) -> SkipDay`: month-end
    pins to real sessions when a session set is supplied, else calendar
    month-end (documented approximation). Returns `skipped`, ordered
    `reasons`, and a human-readable reason.
  - Usage contract: research filter for conditioning backtests ONLY —
    not wired into any live runner or strategy.
- 14 new tests (`tests/test_macro_skip_days.py`): known FOMC dates,
  third-Friday OpEx incl. year boundary, month-end with/without session
  input, Wednesday/Friday discrepancy, multi-reason ordering.
- `trade_macro.weather`: trading-weather composite barometer — one
  categorical readout (calm | caution | storm) plus a 0-100 score for the
  bet-sizing layer, built ONLY from existing validated inputs (copper:gold
  regime label, buyback-blackout read, forced-selling read). Rule-based
  with documented, conventional (never fitted) component points:
  forced_selling.elevated -> storm (50); CONTRACTION + deep blackout ->
  storm (20+20); any single flag -> caution; otherwise calm.
  - `trading_weather(as_of, *, regime, buyback, forced_selling,
    em_state=None) -> WeatherReport`: frozen dataclass with category,
    score, human-readable reasons, and traceable input echo; `em_state`
    accepted-and-ignored slot for a future EM term-structure input.
    Strict as-of-date agreement across inputs (no-look-ahead discipline).
  - `adapters.weather_input(report) -> {"weather": {...}}` for the agents'
    `market_context` merge, following existing adapter conventions.
  - Usage contract: sizing context ONLY, never an entry signal; no fitted
    weights (any weighting proposal requires pre-registration first).
- 21 new tests (`tests/test_macro_weather.py`): each rule in isolation,
  rule combinations, score-mapping boundaries, em_state ignored,
  as-of mismatch / bad regime / wrong-type errors, adapter shape,
  report validation.

## [0.7.0] - 2026-09-26

### Added
- `pipeline.run_allocate` + `pipeline.summarize_allocate` and the
  `trade-suite allocate` CLI command, delegating to trade-allocate's
  canonical pipeline (risk_parity | hrp | equal). Default is the seeded
  demo (synthetic strategies + synthetic evidence, clearly labeled,
  deterministic, offline); `--inputs FILE` allocates over real validated
  strategies from a JSON inputs file. CLI and library paths run the same
  engine, so they agree exactly (tested).

## [0.6.0] - 2026-09-26

### Added
- Registered **trade-allocate v0.1.0** as the twenty-fourth suite module:
  strategy allocation across validated strategies (risk parity / HRP /
  equal weight, OAS correlation shrinkage, turnover damping, deallocation
  on health breach, portfolio-level gates). Wired into the module table,
  `requirements.txt`, `pyproject.toml` dependencies, and the `env.MODULES`
  registry.

## [0.5.0] - 2026-09-26

### Added
- Wired in the **terminal wave** from trade-dashboard-web v0.5.0: five
  monitoring/analysis workflows delegating to the dashboards' canonical
  `run_trades_job` / `run_performance_job` / `run_agent_activity_job` /
  `run_network_job` / `run_risk_monitor_job` via `pipeline._services()`
  (web engine first), so scripted, CLI, and dashboard runs of the same
  job agree exactly:
  - `pipeline.run_trades` + `summarize_trades` + `pipeline.trades_to_csv`
    — read-only paper-ledger blotter (FIFO realized P&L, win/loss/open/
    outcome labels) with the web CSV export shape; new
    `trade-suite trades [--from/--to/--symbol/--side/--strategy/--agent/--outcome/--limit]`
    and `trade-suite trades export --format csv [--out FILE]`.
  - `pipeline.run_performance` + `summarize_performance` — equity,
    drawdown, monthly, 63-day rolling Sharpe/vol, return histogram, and
    trade-P&L summary; new `trade-suite performance --source paper|backtest
    [--backtest-path]`.
  - `pipeline.run_agent_activity` + `summarize_agent_activity` —
    track-record leaderboards, Elo curves, Brier calibration, debate
    timeline, approval queue; new `trade-suite agents [--limit]`.
  - `pipeline.run_network` + `summarize_network` — correlation → MST →
    clusters → seeded layout; new `trade-suite network [--symbols]
    [--source yfinance|demo] [--days] [--method] [--seed]`
    (no `--symbols` = seeded demo universe, no network).
  - `pipeline.run_risk_monitor` + `summarize_risk_monitor` — exposures,
    vol-regime timeline, trade-hedge kill-switch, regime-conviction
    gauge; new `trade-suite risk [--vol-days]`.
- These are dashboard *views* over already-wired engines (trade-paper
  ledgers, trade-agents track records, trade-hedge loop state, regime
  snapshots), not new engines: the module registry stays at 23
  (`env.MODULES` unchanged) — documented in the README and ARCHITECTURE.
- Parameter names mirror the canonical web jobs exactly; the math itself
  is documented in trade-dashboard-web's `docs/METHODOLOGY.md` and is
  summarized (not duplicated) in the README's `## The maths` section.
- A missing dashboard raises the standard `RuntimeError`; when the
  desktop fallback lacks the terminal jobs, `pipeline._terminal_job`
  raises a `RuntimeError` naming the `trade-dashboard-web>=0.5.0`
  install instead of surfacing an `AttributeError`.

## [0.4.0] - 2026-09-24

### Added
- Wired in **trade-breadth** (v0.1.0) as suite module twenty-one: market
  breadth engine (advance/decline, % above moving averages, new
  highs/lows, McClellan oscillator, breadth thrusts, broadening/narrowing
  regime, fragility gauge). New `pipeline.run_breadth` workflow +
  `summarize_breadth`, new `trade-suite breadth --preset --seed --days`
  CLI command, registry entry in `trade_suite.env`.
- Wired in **trade-macro** (v0.1.0) as suite module twenty-two: macro
  regime engine (EXPANSION / CONTRACTION / NEUTRAL from the copper:gold
  growth-expectations proxy, transition alerts on fast z-score moves).
  New `pipeline.run_macro` workflow + `summarize_macro`, new
  `trade-suite macro --preset --seed --days` CLI command, registry entry
  in `trade_suite.env`.
- Wired in **trade-stream** (v0.1.0) as suite module twenty-three:
  real-time streaming engine (WebSocket transport, pub/sub bus, message
  normalization, tick recording/replay, tick-to-bar resampling, spike
  alerts). New `pipeline.run_stream_demo` workflow +
  `summarize_stream_demo`, new `trade-suite stream --symbols --seed
  --ticks` CLI command (demo tick feed, no network), registry entry in
  `trade_suite.env`.
- New `pipeline.run_reconcile_demo` workflow + `summarize_reconcile` and
  `trade-suite reconcile` CLI command: a DEMO read-only reconcile of the
  paper ledger against an in-memory mock broker, exercising trade-paper
  v0.2.0's reconcile machinery (the same read-only diff the Robinhood
  MCP adapter uses). Printed output is labeled
  "DEMO — read-only reconcile against a mock broker"; it can never touch
  live state.
- All four flows delegate to the dashboards' canonical
  `run_breadth_job` / `run_macro_job` / `run_stream_demo_job` /
  `run_reconcile_demo_job` via `pipeline._services()` (web engine first,
  desktop fallback), following the established 0.2.0/0.3.0 wiring pattern:
  scripted, CLI, and dashboard runs of the same job agree exactly.

### Fixed
- **trade-eda** (wired in 0.3.0) was missing its git-URL dependency line in
  `pyproject.toml` and `requirements.txt`; added, alongside the three new
  modules.

### Notes
- trade-data-equities v0.2.0 added a PolygonProvider, but that is
  **data-layer only** — no suite code change was needed; the suite keeps
  talking to the engines through the unchanged `DataService`/`get_bars`
  paths.
- Registry is now twenty-three modules; `trade-suite status` derives its
  counts from `trade_suite.env` unchanged.

## [0.3.0] - 2026-09-24

### Added
- Wired in **trade-eda** as suite module twenty: correlation/covariance/
  EDA engine (Pearson/Spearman matrices, Ledoit-Wolf shrinkage, per-asset
  summary stats, data-quality checks, diversification stats). New
  `pipeline.run_correlation` workflow + `summarize_correlation`, new
  `trade-suite correlate` CLI command, registry entry in `trade_suite.env`.
  The workflow delegates to the dashboards' canonical
  `run_correlation_job`, so CLI, scripted, and Research Lab runs of the
  same universe agree exactly.
- Research Lab grows to eight panels in both dashboards (new Correlations
  panel), following the established 0.2.0 wiring pattern unchanged.

## [0.2.0] - 2026-09-24

### Added
- Wired in the seven new quant engines as suite modules thirteen through
  nineteen: **trade-pairs** (cointegration screen, hedge ratios, signals),
  **trade-orderbook** (limit-order-book simulator, execution analytics),
  **trade-optimize** (Markowitz optimization, efficient frontier),
  **trade-montecarlo** (simulated VaR/CVaR, drawdown scenarios),
  **trade-volsurface** (SVI surface fits, arbitrage checks),
  **trade-factors** (Fama-French regressions, GRS joint-alpha test), and
  **trade-sentiment-vs-price** (lead/lag, event studies, information
  coefficient, sentiment indicators). Git-URL dependencies in
  `pyproject.toml` / `requirements.txt`, registry entries in
  `trade_suite.env` (nineteen modules), and one thin workflow per engine
  in `trade_suite.pipeline` — plain data in, plain data out, demo-capable,
  each naming its engine of record the way `paper_overview` and
  `sentiment_scan` already do.
- Seven matching CLI commands: `trade-suite pairs|orderbook|optimize|
  montecarlo|factors|sentiment-price|volsurface`, each printing a one-screen
  summary.
- `research_pipeline()` gains two opt-in enrichments (off by default):
  `sentiment_price=True` attaches a per-symbol sentiment-vs-price verdict,
  and `factor_model="ff5"` attaches a Fama-French factor report.
- `docs/ARCHITECTURE.md` documents the research-lab wiring pattern; README
  quickstart and Python API examples cover all seven flows.

### Notes
- Demo bars cap at 750 days, so demo factor regressions use about two
  years of monthly history (synthetic factor date labels; alignment is
  what matters). Real Ken French CSVs plug into the engine's
  `load_french_csv`; real option chains into `from_option_chain`; real
  sentiment history into `run_sentiment_price(..., sentiment_rows=...)`.

## [0.1.2] - 2026-09-23

### Added
- Wired in the new **trade-sentiment** social/news sentiment engine as the
  twelfth module: git-URL dependency in `pyproject.toml` /
  `requirements.txt`, registry entry in `trade_suite.env`, new
  `trade_suite.sentiment_scan()` workflow (plain-data pops and verdicts,
  configurable window / mention / conviction bars), and a
  `trade-suite sentiment --symbols --window-hours --min-mentions
  --min-conviction` CLI command. The same engine feeds the trade-agents
  `sentiment_scout`, so the CLI and the desk see identical pops.
- README quickstart and Python API examples cover the sentiment flow;
  `docs/ARCHITECTURE.md` documents the direct-to-engine data flow and the
  one-engine-two-consumers design.

## [0.1.1] - 2026-09-23

### Added
- Wired in the new **trade-paper** paper-trading engine: git-URL dependency
  in `pyproject.toml` / `requirements.txt`, registry entry in
  `trade_suite.env` (eleven modules), new `trade_suite.paper_overview()`
  workflow, and a `trade-suite paper --config` CLI command printing the
  paper account, positions, active strategies, and the strategy-approval
  queue.
- Both dashboards' new **Paper** tabs (v0.1.1 releases) monitor the same
  `trade-paper` engine.

## [0.1.0] - 2026-09-23

### Added
- Meta-package over the ten trade-suite modules: one `pip install` for the
  whole system (git-URL dependencies in `pyproject.toml`, mirrored in
  `requirements.txt`).
- `trade_suite.env`: module registry with roles and repo URLs;
  `module_status()` / `installed_modules()` / `require()` introspection.
- `trade_suite.data`: `get_bars()` delegating to the dashboard engines'
  `DataService` (demo + delayed equities), with a clear install hint when
  no dashboard package is present.
- `trade_suite.pipeline`: end-to-end workflows — `run_backtest`,
  `run_desk`, `evaluate_orders` — orchestrating the sibling engines through
  the shared dashboard-engine services (identical results in either UI).
- `trade-suite` CLI: `status`, `doctor`, `demo`, `backtest`, `launch web|desktop`.
- `examples/end_to_end_demo.py`: desk → backtest → risk review on demo data.
- License-key check hook and GitHub-releases update-check hook.
- MIT license, README, architecture doc, test suite.
