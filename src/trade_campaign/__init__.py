"""trade-campaign: long-running paper campaigns for validated strategies.

Wires a validated strategy (today: REGCOND-1) through the trade-safety
kernel to a broker adapter in SIMULATE, records every session into the
trade-incubate ledger, and renders the daily digest.  Paper-only by
construction: the campaign config refuses any non-SIMULATE environment.
"""

from .config import CampaignConfig
from .runner import run_campaign_day

__version__ = "0.1.0"
__all__ = ["CampaignConfig", "run_campaign_day", "__version__"]
