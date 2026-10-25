"""Campaign configuration.

One campaign = one validated strategy, one paper account, one incubation
program.  Everything campaign-specific lives here so the runner stays
generic plumbing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from trade_safety import SafetyConfig
from trade_safety.policy import ApprovalMode

#: REGCOND-1's frozen universe (trade_strategies.regcond_1.SYMBOLS).
SYMBOLS = ("SPY", "CPER", "TLT", "GLD")

#: Tier-1 validated expectations (docs/validation, GATES.md two-tier
#: framework): walk-forward OOS median Sharpe 1.385, max drawdown 23.0%.
BACKTEST = {"sharpe": 1.385, "max_drawdown": 0.23, "n_trades": 500}

#: Drift expectations.  win_rate/payoff are not published for REGCOND-1;
#: the trade-incubate defaults are used and the drift bands are wide.
EXPECTED = {
    "sharpe": BACKTEST["sharpe"],
    "win_rate": 0.45,
    "payoff": 1.0,
    "max_drawdown": BACKTEST["max_drawdown"],
    # A monthly 4-leg rebalance closes at most ~4 positions a month.
    "trades_per_day": 4.0 / 63.0,
}


def campaign_safety_config() -> SafetyConfig:
    """Safety posture for an autonomous *paper* allocation campaign.

    Deliberate choices, all recorded here rather than hidden in defaults:

    - ``approval_mode=AUTONOMOUS`` — the campaign runs unattended; the
      kernel's structural gates are the control, per the Oct 2026
      autonomous-paper direction.
    - **No daily-loss breaker** (both limits ``None``): REGCOND-1 is a
      hold-through-drawdown allocation strategy whose validated max
      drawdown is 23%.  A daily 2% breaker would fight the strategy's
      design.  Drawdown protection lives one level up, in the incubation
      program's kill conditions (pause at 1.5x backtest DD, drift
      VIOLATION pauses), and in the manual E-Stop.
    - Exposure cap 105%: the strategy is fully invested by design
      (weights sum to 1.0); the cap leaves room for price drift between
      signal and fill.
    - Per-trade cap: none at kernel level — position size is bounded by
      the target weights themselves plus the exposure cap.
    - Margin-cushion floor 10%: the paper account must stay well clear
      of Moomoo's intraday-margin-deficit zone even in simulation.
    """
    return SafetyConfig(
        approval_mode=ApprovalMode.AUTONOMOUS,
        max_daily_loss_pct=None,
        max_daily_loss_abs=None,
        per_trade_cap_abs=None,
        max_total_exposure_pct=1.05,
        min_margin_cushion_pct=0.10,
    )


@dataclass
class CampaignConfig:
    strategy_id: str = "REGCOND-1"
    strategy_name: str = "regcond_1"
    symbols: tuple = SYMBOLS
    #: SIMULATE only — enforced in __post_init__.
    env: str = "SIMULATE"
    campaign_dir: Path = field(
        default_factory=lambda: Path(
            os.path.expanduser("~/.trade-campaign/regcond1")))
    #: Calendar days of history fetched per run (the strategy needs
    #: >= 260 trading days of warmup; 1200 calendar days is ~820 sessions
    #: the first run and the provider caches afterwards).
    history_days: int = 1200
    #: Bars source: "yfinance" (real delayed closes) or "demo"
    #: (deterministic synthetic — plumbing tests only, never a campaign).
    bars_source: str = "yfinance"
    backtest: dict = field(default_factory=lambda: dict(BACKTEST))
    expected: dict = field(default_factory=lambda: dict(EXPECTED))
    incubation_preset: str = "balanced"
    #: Rebalance orders are marketable limits this far through the
    #: reference (last) close — fills at market, never worse than the
    #: band.  The strategy's cost model is 5 bps/side; 30 bps is a guard,
    #: not an expectation.
    limit_band_bps: float = 30.0
    #: Skip non-exit orders whose value is below this (dust control).
    min_order_notional: float = 25.0
    safety: SafetyConfig = field(default_factory=campaign_safety_config)

    def __post_init__(self) -> None:
        if self.env != "SIMULATE":
            raise ValueError(
                "campaigns are paper-only: env must be SIMULATE, "
                f"got {self.env!r}")
        self.campaign_dir = Path(self.campaign_dir)

    # -- paths ---------------------------------------------------------
    @property
    def state_path(self) -> Path:
        return self.campaign_dir / "state.json"

    @property
    def ledger_path(self) -> Path:
        return self.campaign_dir / "incubation.jsonl"

    @property
    def fills_path(self) -> Path:
        return self.campaign_dir / "fills.jsonl"

    @property
    def safety_state_path(self) -> Path:
        return self.campaign_dir / "safety_state.json"

    @property
    def audit_log_path(self) -> Path:
        return self.campaign_dir / "audit_log.json"

    @property
    def digest_dir(self) -> Path:
        return self.campaign_dir / "digests"

    def ensure_dirs(self) -> None:
        self.campaign_dir.mkdir(parents=True, exist_ok=True)
        self.digest_dir.mkdir(parents=True, exist_ok=True)
