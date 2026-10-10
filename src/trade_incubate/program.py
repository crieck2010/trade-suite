"""The incubation program: stages, graduation criteria, kill conditions.

A strategy that passed validation (trade-swing's ValidationReport) earns a
63-trading-day paper quarter.  The program answers one question continuously:
"is the strategy behaving like its backtest?"  `evaluate()` returns
plain-data verdicts; nothing here executes anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------- stages

class Stage:
    WARMUP = "WARMUP"                    # days 1-10
    OBSERVATION = "OBSERVATION"          # days 11-40
    GRADUATION_REVIEW = "GRADUATION_REVIEW"  # days 41-63
    PAUSED = "PAUSED"                    # kill condition tripped
    GRADUATED = "GRADUATED"
    RETIRED = "RETIRED"


STAGE_BOUNDARIES = {
    Stage.WARMUP: (1, 10),
    Stage.OBSERVATION: (11, 40),
    Stage.GRADUATION_REVIEW: (41, 63),
}

# Size dial per stage: warmup trades half size so early, noisy days cost less.
STAGE_SIZE_MULTIPLIER = {
    Stage.WARMUP: 0.5,
    Stage.OBSERVATION: 1.0,
    Stage.GRADUATION_REVIEW: 1.0,
}


def stage_for(day: int) -> str:
    """Map a 1-based incubation day to its stage.  Days past 63 stay in review."""
    for stage, (lo, hi) in STAGE_BOUNDARIES.items():
        if lo <= day <= hi:
            return stage
    if day < 1:
        return Stage.WARMUP
    return Stage.GRADUATION_REVIEW


# ------------------------------------------------------- program config

@dataclass
class ProgramConfig:
    """All thresholds are configurable; defaults are documented in INCUBATION.md.

    Graduation (all must hold at day 63):
    - paper Sharpe >= backtest Sharpe - sharpe_tolerance
    - paper max drawdown <= dd_multiple * backtest max drawdown
    - at least min_trades closed trades
    - no kill-condition trip during the quarter
    - drift never reached VIOLATION

    Kill conditions (evaluated every day; any trip pauses the program):
    - drawdown > kill_dd_multiple * backtest max drawdown
    - drift verdict == VIOLATION
    """
    sharpe_tolerance: float = 0.75
    dd_multiple: float = 1.25
    min_trades: int = 20
    kill_dd_multiple: float = 1.5
    regime_min_conviction: float = 30.0   # below this: no NEW entries
    warmup_size: float = 0.5


DEFAULT_CRITERIA = ProgramConfig()


@dataclass
class IncubationProgram:
    """State machine for one strategy's paper quarter.

    ``backtest`` is the expectations source: a dict carrying at least
    ``sharpe``, ``max_drawdown`` (positive fraction), ``n_trades`` —
    the shape of trade-swing's ValidationReport["backtest"]["metrics"].
    """
    strategy_name: str
    backtest: dict
    config: ProgramConfig = field(default_factory=ProgramConfig)
    day: int = 0
    state: str = Stage.WARMUP
    kill_trips: list = field(default_factory=list)   # list of {day, condition, detail}
    drift_worst: str = "OK"

    # -- stage machinery -------------------------------------------------

    def advance(self) -> str:
        """Move to the next day; returns the new stage (PAUSED sticks)."""
        if self.state in (Stage.PAUSED, Stage.GRADUATED, Stage.RETIRED):
            return self.state
        self.day += 1
        self.state = stage_for(self.day)
        return self.state

    def size_multiplier(self) -> float:
        return STAGE_SIZE_MULTIPLIER.get(self.state, 1.0)

    # -- kill conditions --------------------------------------------------

    def check_kill(self, paper_stats: dict, drift_verdict: str) -> list:
        """Evaluate kill conditions against today's paper stats.

        ``paper_stats`` needs ``max_drawdown`` (positive fraction).
        Returns the list of newly-tripped conditions (empty if none).
        A trip pauses the program and records the event.
        """
        tripped = []
        bt_dd = abs(float(self.backtest.get("max_drawdown", 0.0)) or 1e-9)
        paper_dd = abs(float(paper_stats.get("max_drawdown", 0.0)))
        if paper_dd > self.config.kill_dd_multiple * bt_dd:
            tripped.append({
                "day": self.day, "condition": "drawdown_breach",
                "detail": f"paper DD {paper_dd:.2%} > "
                          f"{self.config.kill_dd_multiple}x backtest DD {bt_dd:.2%}",
            })
        if drift_verdict == "VIOLATION":
            tripped.append({
                "day": self.day, "condition": "drift_violation",
                "detail": "drift detector reached VIOLATION",
            })
        if tripped:
            self.kill_trips.extend(tripped)
            self.state = Stage.PAUSED
        return tripped

    def resume(self) -> str:
        """Human-only action: clear PAUSED after reviewing the trips."""
        if self.state == Stage.PAUSED:
            self.state = stage_for(max(self.day, 1))
        return self.state

    # -- graduation --------------------------------------------------------

    def graduation_check(self, paper_stats: dict) -> dict:
        """Evaluate graduation criteria.  Returns per-criterion pass/fail."""
        cfg = self.config
        bt_sharpe = float(self.backtest.get("sharpe", 0.0))
        bt_dd = abs(float(self.backtest.get("max_drawdown", 0.0)) or 1e-9)
        paper_sharpe = float(paper_stats.get("sharpe", float("-inf")))
        paper_dd = abs(float(paper_stats.get("max_drawdown", 0.0)))
        n_trades = int(paper_stats.get("n_trades", 0))

        criteria = {
            "sharpe_within_tolerance": {
                "pass": paper_sharpe >= bt_sharpe - cfg.sharpe_tolerance,
                "detail": f"paper {paper_sharpe:.2f} vs backtest {bt_sharpe:.2f} "
                          f"(tolerance {cfg.sharpe_tolerance})",
            },
            "drawdown_within_multiple": {
                "pass": paper_dd <= cfg.dd_multiple * bt_dd,
                "detail": f"paper {paper_dd:.2%} <= {cfg.dd_multiple}x "
                          f"backtest {bt_dd:.2%}",
            },
            "minimum_trades": {
                "pass": n_trades >= cfg.min_trades,
                "detail": f"{n_trades} closed trades (minimum {cfg.min_trades})",
            },
            "no_kill_trips": {
                "pass": not self.kill_trips,
                "detail": f"{len(self.kill_trips)} kill-condition trips",
            },
            "no_drift_violation": {
                "pass": self.drift_worst != "VIOLATION",
                "detail": f"worst drift verdict: {self.drift_worst}",
            },
        }
        graduated = all(c["pass"] for c in criteria.values())
        return {"criteria": criteria, "graduated": graduated,
                "day": self.day, "strategy": self.strategy_name}

    def graduate(self, paper_stats: dict) -> dict:
        """Run graduation review; on success the program state becomes GRADUATED."""
        result = self.graduation_check(paper_stats)
        if result["graduated"]:
            self.state = Stage.GRADUATED
        return result

    # -- the daily verdict --------------------------------------------------

    def evaluate(self, paper_stats: dict, drift_verdict: str,
                 conviction: float | None = None,
                 force_block_entries: bool = False) -> dict:
        """One plain-data verdict for the day.  schema_version 1.

        ``force_block_entries``: the runner sets this when its own policy
        (e.g. ``require_conviction`` with no conviction available) blocks
        entries beyond what the regime gate says.
        """
        if drift_verdict == "VIOLATION":
            self.drift_worst = "VIOLATION"
        elif drift_verdict == "WATCH" and self.drift_worst == "OK":
            self.drift_worst = "WATCH"
        kills = self.check_kill(paper_stats, drift_verdict)
        conviction = float(conviction) if conviction is not None else None
        new_entries_allowed = (
            self.state != Stage.PAUSED
            and not force_block_entries
            and (conviction is None or conviction >= self.config.regime_min_conviction)
        )
        return {
            "schema_version": 1,
            "strategy": self.strategy_name,
            "day": self.day,
            "stage": self.state,
            "size_multiplier": self.size_multiplier(),
            "new_entries_allowed": new_entries_allowed,
            "regime_conviction": conviction,
            "drift": drift_verdict,
            "kill_trips_today": kills,
            "paused": self.state == Stage.PAUSED,
        }
