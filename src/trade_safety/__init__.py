"""trade_safety — the execution safety kernel (live-roadmap Phase 1).

Broker-agnostic, stdlib-only. One latch service every order must pass:
E-Stop, daily-loss circuit breaker with session lockout, per-trade and
exposure caps, margin-cushion guard (Moomoo IML proxy), approval policy
(approve / veto-window / autonomous), pre-flight checklist, and a
heartbeat watchdog. See README.md.
"""

from .alerts import MattermostWebhookSink, MemoryAlertSink, NullAlertSink
from .audit import JsonAuditWriter, MemoryAuditWriter
from .config import SafetyConfig
from .kernel import SafetyKernel
from .models import AccountSnapshot, Decision, OrderIntent
from .policy import ApprovalMode, AutoApprover, CallbackApprover, authorize
from .preflight import PreflightReport, run_preflight
from .state import SafetyState
from .watchdog import Watchdog

__version__ = "0.1.0"

__all__ = [
    "AccountSnapshot",
    "ApprovalMode",
    "AutoApprover",
    "CallbackApprover",
    "Decision",
    "JsonAuditWriter",
    "MattermostWebhookSink",
    "MemoryAlertSink",
    "MemoryAuditWriter",
    "NullAlertSink",
    "OrderIntent",
    "PreflightReport",
    "SafetyConfig",
    "SafetyKernel",
    "SafetyState",
    "Watchdog",
    "__version__",
    "authorize",
    "run_preflight",
]
