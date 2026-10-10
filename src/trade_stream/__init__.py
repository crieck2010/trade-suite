"""trade-stream: real-time market-data streaming engine.

WebSocket-first transport with REST-polling fallback, a thread-safe
pub/sub bus, canonical message normalization, tick recording and replay,
tick-to-bar resampling, and price-spike alerts — stdlib-only, plain data
in / plain data out.

Part of the trade-suite algorithmic trading system. Research/backtesting/
paper-trading only — never live trading.
"""

from __future__ import annotations

from .adapters import LatestPriceCache, spike_alerts, subscribe_dashboard
from .alerts import MultiSpikeDetector, SpikeDetector
from .bars import VWAPTracker, resample
from .bus import MessageBus, Subscription
from .demo import DEMO_SYMBOLS, demo_feed, run_demo
from .licensing import check_license, check_update
from .normalizer import (
    SCHEMA_VERSION,
    normalize_coinbase,
    normalize_demo,
    validate_canonical,
)
from .recorder import TickRecorder
from .reconnect import PRESETS, ReconnectPolicy, preset
from .replay import read_ticks, replay, topic_for
from .runner import DemoTransport, FeedExhausted, StreamSession, make_polling_session
from .sources import (
    get_source,
    live_source_names,
    require_live,
    source_names,
)
from .transport import (
    PollingTransport,
    StaleConnectionError,
    WebSocketError,
    WebSocketTransport,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "DEMO_SYMBOLS",
    "PRESETS",
    "DemoTransport",
    "FeedExhausted",
    "LatestPriceCache",
    "MessageBus",
    "MultiSpikeDetector",
    "PollingTransport",
    "ReconnectPolicy",
    "SpikeDetector",
    "StaleConnectionError",
    "StreamSession",
    "Subscription",
    "TickRecorder",
    "VWAPTracker",
    "WebSocketError",
    "WebSocketTransport",
    "check_license",
    "check_update",
    "demo_feed",
    "get_source",
    "live_source_names",
    "make_polling_session",
    "normalize_coinbase",
    "normalize_demo",
    "preset",
    "read_ticks",
    "replay",
    "require_live",
    "resample",
    "run_demo",
    "source_names",
    "spike_alerts",
    "subscribe_dashboard",
    "topic_for",
    "validate_canonical",
]
