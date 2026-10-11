"""Base data models and abstractions for trade_dashboard_app services.

All UI components interact exclusively with these typed dataclasses,
preserving clean separation between presentation and underlying engines.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class PortfolioMetrics:
    """Core executive metrics shown in the zero-scroll hero bar."""
    net_liquidity: float = 142500.00
    day_pnl: float = 1250.00
    day_pnl_pct: float = 0.88
    ytd_pnl: float = 12400.00
    ytd_pnl_pct: float = 9.50
    buying_power: float = 85000.00
    margin_utilization_pct: float = 40.35
    beta_weighted_delta: float = 150.0
    beta_weighted_delta_change: float = -15.0
    vix: float = 14.85
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Position:
    """Active book position, prioritizing 100-share round lots or spreads."""
    symbol: str
    asset_type: str
    quantity: int
    dte: Optional[int]
    cost_basis: float
    current_price: float
    unrealized_pnl: float
    delta: float
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AssetAllocation:
    """Asset allocation breakdown reflecting the Levenson Macro Framework."""
    real_assets_pct: float = 45.0  # Energy, Industrial Metals, Gold, Uranium
    equities_pct: float = 35.0     # S&P 500, QQQ
    cash_short_term_pct: float = 20.0  # T-Bills, Cash reserve

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentNodeStatus:
    """State of an individual node in the LangGraph cyclic workflow."""
    node_id: str
    name: str
    status: str  # "Active", "Listening", "Spawning", "Idle", "Error"
    detail: str
    pulse_active: bool = False


@dataclass
class DebateTurn:
    """Record of an inter-agent thesis debate (trade_agents v0.2.0)."""
    turn_index: int
    speaker: str
    role: str  # "Bull Challenger", "Bear Challenger", "Risk Manager", "Consensus"
    argument: str
    reputation_score: float
    vote_weight: float


@dataclass
class AgentReputation:
    """Leaderboard entry tracking research agent out-of-sample performance."""
    agent_name: str
    realized_oos_sharpe: float
    clawback_decay_pct: float
    effective_voting_weight: float
    calibration_brier: float
    status: str  # "Active", "Probation", "Sidelined"


@dataclass
class OrderRecord:
    """Historical or active order execution record."""
    order_id: str
    timestamp: str
    symbol: str
    side: str  # "BUY", "SELL"
    quantity: int
    order_type: str  # "LIMIT", "MARKET", "STOP"
    limit_price: Optional[float]
    fill_price: Optional[float]
    status: str  # "FILLED", "PENDING", "CANCELED", "REJECTED"
    agent_proposer: str
    rationale: str
    expected_price: float
    slippage_bps: float


@dataclass
class PendingProposal:
    """Staged trade proposal awaiting human-in-the-loop review."""
    proposal_id: str
    timestamp: str
    symbol: str
    side: str
    quantity: int
    strategy: str
    target_weight_pct: float
    rationale: str
    urgency: str  # "Normal", "High", "Critical"
    proposer_agent: str


@dataclass
class RiskStatus:
    """Global risk controls, gamma exposure, and emergency stop state."""
    kill_switch_active: bool = False
    kill_switch_reason: Optional[str] = None
    hyper_gamma_0dte: float = 142.50
    hyper_gamma_threshold: float = 250.00
    vix_spike_alert: bool = False
    max_sector_exposure_pct: float = 30.0
    current_highest_sector: str = "Energy (XLE)"
    current_highest_sector_pct: float = 22.4


@dataclass
class HardwareInferenceMetrics:
    """Local inference metrics (M3 Ultra / Local LLM serving)."""
    vram_used_gb: float = 448.0
    vram_total_gb: float = 512.0
    vram_free_gb: float = 64.0
    token_generation_speed: float = 78.4  # tokens/sec
    prompt_cache_hit_rate_pct: float = 94.2
    gpu_temperature_c: float = 54.0
    throttling_status: str = "Nominal (No Throttling)"
