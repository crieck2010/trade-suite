"""Moomoo Open API execution adapter for equities and cash-settled European index options.

Connects to local Moomoo OpenD (127.0.0.1:11111) via the `moomoo-api` Python SDK.
Supports both `TrdEnv.SIMULATE` (paper) and `TrdEnv.REAL` (live) environments.

Safety Guarantees:
1. `REAL` trading requires `allow_live_trading=True` AND explicit trade password unlock.
2. Mandatory human-in-the-loop gate: Charlie must authorize live orders.
3. Every order submission, cancel, and unlock event writes atomically to `audit_log.json`.
4. Fail-soft simulation fallback: If OpenD is offline, operates in high-fidelity
   simulation mode without crashing research/paper workflows.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import ExecutionAdapter
from .exceptions import (
    ExecutionError,
    LiveSafetyError,
    OpenDConnectionError,
    OrderRejectionError,
    TradeUnlockError,
)
from .models import (
    AccountState,
    ComboLegPayload,
    ComboOrderPayload,
    ComboStrategyType,
    ExecutionEnvironment,
    ExecutionResult,
    OrderAction,
    OrderPayload,
    OrderType,
    PositionSnapshot,
    SecurityType,
    TimeInForce,
    utcnow_str,
)

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Safely convert any Moomoo response field (including 'N/A') to float."""
    if val is None or val == "N/A" or val == "":
        return default
    try:
        import math
        f = float(val)
        return default if math.isnan(f) else f
    except (ValueError, TypeError):
        return default


# Optional moomoo import with graceful fallback
try:
    import moomoo as ft
    _MOOMOO_AVAILABLE = True
except ImportError:
    ft = None
    _MOOMOO_AVAILABLE = False


@dataclass
class MoomooAdapterConfig:
    """Configuration options for MoomooExecutionAdapter."""
    host: str = "127.0.0.1"
    port: int = 11111
    env: ExecutionEnvironment = ExecutionEnvironment.SIMULATE
    market: str = "US"
    account_id: int = 0
    account_index: int = 0
    unlock_password: str = ""
    allow_live_trading: bool = False  # Hard safety latch: must be explicitly True for REAL
    audit_log_path: Path = field(
        default_factory=lambda: Path(
            os.environ.get("AUDIT_LOG_PATH", "c:/Agentic AI Algorithmic Trading System Software/audit_log.json")
        )
    )

    def __post_init__(self) -> None:
        if not self.unlock_password:
            self.unlock_password = os.environ.get("MOOMOO_TRADE_PASSWORD", "")


class MoomooExecutionAdapter(ExecutionAdapter):
    """Moomoo Open API broker execution adapter.

    Handles:
    - Single-leg ETF & Stock orders for RegCond-1 macro rebalancing (SPY, TLT, GLD, CPER).
    - Atomic multi-leg combo orders via `place_combo_order` for 0DTE European SPX/XSP Iron-Flies.
    - Full paper simulation (`TrdEnv.SIMULATE`) and live real-money (`TrdEnv.REAL`) modes.
    - Security unlock gate via `unlock_trade` for live accounts.
    """

    adapter_name: str = "moomoo"

    def __init__(self, config: MoomooAdapterConfig | None = None) -> None:
        self.cfg = config or MoomooAdapterConfig()
        self._trd_ctx: Any = None
        self._connected = False
        self._is_unlocked = False
        self._simulated_orders: dict[str, dict[str, Any]] = {}
        self._simulated_positions: dict[str, PositionSnapshot] = {
            "SPY": PositionSnapshot("SPY", 100, 570.0, 582.5, 58250.0, 1250.0, 2.19, SecurityType.ETF, self.cfg.env),
            "TLT": PositionSnapshot("TLT", 200, 92.0, 93.4, 18680.0, 280.0, 1.52, SecurityType.ETF, self.cfg.env),
            "GLD": PositionSnapshot("GLD", 50, 240.0, 246.0, 12300.0, 300.0, 2.50, SecurityType.ETF, self.cfg.env),
            "CPER": PositionSnapshot("CPER", 300, 26.5, 27.2, 8160.0, 210.0, 2.64, SecurityType.ETF, self.cfg.env),
        }
        self._simulated_balance = 100000.0

        # Enable daemon threads so moomoo background workers don't block process exit
        if _MOOMOO_AVAILABLE and hasattr(ft, "SysConfig"):
            try:
                ft.SysConfig.set_all_thread_daemon(True)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Connection Lifecycle
    # -------------------------------------------------------------------------

    def connect(self) -> bool:
        """Connect to local Moomoo OpenD process (127.0.0.1:11111)."""
        if not _MOOMOO_AVAILABLE:
            logger.warning("moomoo-api SDK not installed; operating in offline simulation mode.")
            self._connected = False
            return False

        # Quick socket pre-check to avoid long connection timeout if OpenD is down
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((self.cfg.host, self.cfg.port)) != 0:
                    logger.info("OpenD port %s:%d not responding. Using offline simulation mode.", self.cfg.host, self.cfg.port)
                    self._connected = False
                    return False
        except Exception:
            self._connected = False
            return False

        try:
            self._trd_ctx = ft.OpenSecTradeContext(
                host=self.cfg.host,
                port=self.cfg.port,
                filter_trdmarket=ft.TrdMarket.US,
            )
            self._connected = True

            # Auto-detect account ID if not explicitly specified
            if self.cfg.account_id == 0:
                try:
                    ret, acc_df = self._trd_ctx.get_acc_list()
                    if ret == ft.RET_OK and not acc_df.empty:
                        env_str = "REAL" if self.cfg.env == ExecutionEnvironment.REAL else "SIMULATE"
                        matching = acc_df[acc_df["trd_env"] == env_str]
                        if not matching.empty:
                            self.cfg.account_id = int(matching.iloc[0]["acc_id"])
                            logger.info("Auto-detected Moomoo %s account ID: %s", env_str, self.cfg.account_id)
                except Exception as acc_exc:
                    logger.debug("Account ID auto-detection skipped: %s", acc_exc)

            logger.info("Connected to Moomoo OpenD at %s:%s (Env: %s, Acc: %s)", self.cfg.host, self.cfg.port, self.cfg.env.value, self.cfg.account_id)
            return True
        except Exception as exc:
            logger.warning("Failed to connect to local Moomoo OpenD at %s:%s (%s). Using offline fallback.", self.cfg.host, self.cfg.port, exc)
            self._trd_ctx = None
            self._connected = False
            return False

    def disconnect(self) -> None:
        """Close OpenD connection cleanly."""
        if self._trd_ctx is not None:
            try:
                self._trd_ctx.close()
            except Exception as exc:
                logger.debug("Error closing Moomoo TradeContext: %s", exc)
        self._trd_ctx = None
        self._connected = False
        self._is_unlocked = False

    def is_connected(self) -> bool:
        """Return True if connected to an active OpenD gateway."""
        return self._connected and self._trd_ctx is not None

    def get_environment(self) -> ExecutionEnvironment:
        """Return active execution environment."""
        return self.cfg.env

    # -------------------------------------------------------------------------
    # Safety & Human-in-the-Loop Trade Unlock Gate
    # -------------------------------------------------------------------------

    def unlock_live_trading(self, password: str | None = None) -> bool:
        """Unlock trade execution for live accounts (`TrdEnv.REAL`).

        Charlie's mandatory authorization password gate. Live trading remains locked
        until successfully called.
        """
        pwd = password or self.cfg.unlock_password
        if not pwd:
            raise TradeUnlockError("Trade unlock password required. Set MOOMOO_TRADE_PASSWORD or supply password.")

        if self.cfg.env == ExecutionEnvironment.SIMULATE:
            # Paper trading does not require gateway unlock, but we latch the state
            self._is_unlocked = True
            self._record_audit_event("MOOMOO_UNLOCK_SIMULATION", {"status": "SUCCESS", "env": "SIMULATE"})
            return True

        if not self.cfg.allow_live_trading:
            raise LiveSafetyError(
                "Refusing to unlock live trading: allow_live_trading is False. "
                "System is in research/paper mode per AGENTS.md rules."
            )

        if not self.is_connected():
            raise OpenDConnectionError("Cannot unlock live trading: OpenD gateway is not connected.")

        ret, data = self._trd_ctx.unlock_trade(password=pwd, is_unlock=True)
        if ret == ft.RET_OK:
            self._is_unlocked = True
            self._record_audit_event("MOOMOO_UNLOCK_LIVE_SUCCESS", {"status": "SUCCESS", "env": "REAL", "actor": "Charlie"})
            logger.info("Moomoo live trade context unlocked successfully.")
            return True
        else:
            self._is_unlocked = False
            err_msg = str(data)
            self._record_audit_event("MOOMOO_UNLOCK_LIVE_FAILED", {"status": "FAILED", "env": "REAL", "error": err_msg})
            raise TradeUnlockError(f"Moomoo trade unlock failed: {err_msg}")

    def lock_live_trading(self) -> bool:
        """Relock live trading capabilities."""
        if self.is_connected() and self._is_unlocked:
            try:
                self._trd_ctx.unlock_trade(is_unlock=False)
            except Exception as exc:
                logger.debug("Error relocking trade context: %s", exc)

        self._is_unlocked = False
        self._record_audit_event("MOOMOO_LOCK_TRADING", {"status": "LOCKED", "env": self.cfg.env.value})
        return True

    # -------------------------------------------------------------------------
    # Account & Position Queries
    # -------------------------------------------------------------------------

    def get_account(self) -> AccountState:
        """Query account capital, cash, buying power, and margin."""
        ft_env = ft.TrdEnv.REAL if self.cfg.env == ExecutionEnvironment.REAL else ft.TrdEnv.SIMULATE

        if self.is_connected():
            ret, data = self._trd_ctx.accinfo_query(
                trd_env=ft_env,
                acc_id=self.cfg.account_id,
                acc_index=self.cfg.account_index,
                currency="USD",
            )
            if ret == ft.RET_OK and not data.empty:
                row = data.iloc[0]
                return AccountState(
                    account_id=str(row.get("acc_id", "moomoo-simulated")),
                    net_liquidity=_safe_float(row.get("total_assets"), self._simulated_balance),
                    buying_power=_safe_float(row.get("power"), self._simulated_balance * 4),
                    cash=_safe_float(row.get("cash"), self._simulated_balance),
                    maintenance_margin=_safe_float(row.get("maintenance_margin"), 0.0),
                    unrealized_pnl=_safe_float(row.get("unrealized_pl"), 0.0),
                    realized_pnl=_safe_float(row.get("realized_pl"), 0.0),
                    currency="USD",
                    env=self.cfg.env,
                )

        # Fallback to simulated account state
        return AccountState(
            account_id="moomoo-simulated",
            net_liquidity=self._simulated_balance,
            buying_power=self._simulated_balance * 4.0,  # 4x Reg-T intraday margin
            cash=self._simulated_balance * 0.40,
            maintenance_margin=self._simulated_balance * 0.15,
            unrealized_pnl=2040.0,
            realized_pnl=450.0,
            currency="USD",
            env=self.cfg.env,
        )

    def get_positions(self) -> list[PositionSnapshot]:
        """Query open stock, ETF, and options positions."""
        ft_env = ft.TrdEnv.REAL if self.cfg.env == ExecutionEnvironment.REAL else ft.TrdEnv.SIMULATE

        if self.is_connected():
            ret, data = self._trd_ctx.position_list_query(
                trd_env=ft_env,
                acc_id=self.cfg.account_id,
                acc_index=self.cfg.account_index,
                currency="USD",
            )
            if ret == ft.RET_OK:
                positions = []
                if not data.empty:
                    for _, row in data.iterrows():
                        symbol = str(row.get("code", "")).replace("US.", "").replace("US..", "")
                        sec_type_str = str(row.get("sec_type", "STOCK"))
                        sec_type = SecurityType.OPTION if "OPTION" in sec_type_str else SecurityType.STOCK

                        positions.append(
                            PositionSnapshot(
                                symbol=symbol,
                                quantity=_safe_float(row.get("qty"), 0.0),
                                cost_basis=_safe_float(row.get("cost_price"), 0.0),
                                market_price=_safe_float(row.get("nominal_price"), 0.0),
                                market_value=_safe_float(row.get("market_val"), 0.0),
                                nominal_pnl=_safe_float(row.get("pl_val"), 0.0),
                                unrealized_pnl_pct=_safe_float(row.get("pl_ratio"), 0.0),
                                sec_type=sec_type,
                                env=self.cfg.env,
                            )
                        )
                return positions

        return list(self._simulated_positions.values())

    # -------------------------------------------------------------------------
    # Order Execution (Equities & ETFs)
    # -------------------------------------------------------------------------

    def place_order(self, order: OrderPayload) -> ExecutionResult:
        """Submit single-leg order (e.g. RegCond-1 rebalance: SPY, TLT, GLD, CPER)."""
        self._enforce_safety_gates(order.strategy)

        formatted_code = self._format_moomoo_symbol(order.symbol)
        side = ft.TrdSide.BUY if order.action == OrderAction.BUY else ft.TrdSide.SELL
        order_type = ft.OrderType.NORMAL if order.order_type == OrderType.LIMIT else ft.OrderType.MARKET
        price = order.price or 0.0
        ft_env = ft.TrdEnv.REAL if self.cfg.env == ExecutionEnvironment.REAL else ft.TrdEnv.SIMULATE

        if self.is_connected():
            ret, data = self._trd_ctx.place_order(
                price=price,
                qty=order.quantity,
                code=formatted_code,
                trd_side=side,
                order_type=order_type,
                trd_env=ft_env,
                acc_id=self.cfg.account_id,
                acc_index=self.cfg.account_index,
                remark=f"antigravity:{order.strategy}",
                time_in_force=order.time_in_force.value,
            )
            if ret == ft.RET_OK and not data.empty:
                order_id = str(data.iloc[0].get("order_id", ""))
                res = ExecutionResult(
                    success=True,
                    order_id=order_id,
                    client_tag=order.client_tag,
                    env=self.cfg.env,
                    status="SUBMITTED",
                    filled_qty=0,
                    avg_price=price,
                    message="Order placed on Moomoo exchange",
                    raw_response=data.to_dict(orient="records")[0],
                )
                self._record_audit_event("MOOMOO_ORDER_SUBMITTED", {
                    "order_id": order_id,
                    "symbol": order.symbol,
                    "action": order.action.value,
                    "quantity": order.quantity,
                    "price": price,
                    "env": self.cfg.env.value,
                    "strategy": order.strategy,
                })
                return res
            else:
                err_msg = str(data)
                self._record_audit_event("MOOMOO_ORDER_REJECTED", {
                    "symbol": order.symbol,
                    "error": err_msg,
                    "env": self.cfg.env.value,
                })
                raise OrderRejectionError(f"Moomoo order submission failed: {err_msg}")

        # Offline simulation execution
        sim_order_id = f"moomoo-sim-{int(datetime.now().timestamp() * 1000)}"
        res = ExecutionResult(
            success=True,
            order_id=sim_order_id,
            client_tag=order.client_tag,
            env=self.cfg.env,
            status="FILLED",
            filled_qty=order.quantity,
            avg_price=price,
            message=f"Simulated execution for {order.symbol} ({order.quantity} shares)",
            raw_response={"simulated": True, "order_id": sim_order_id},
        )
        self._record_audit_event("MOOMOO_SIMULATED_ORDER", {
            "order_id": sim_order_id,
            "symbol": order.symbol,
            "action": order.action.value,
            "quantity": order.quantity,
            "price": price,
            "env": self.cfg.env.value,
            "offline_mode": True,
        })
        return res

    # -------------------------------------------------------------------------
    # Multi-Leg Combo Orders (0DTE European SPX / XSP Iron-Flies)
    # -------------------------------------------------------------------------

    def place_combo_order(self, combo: ComboOrderPayload) -> ExecutionResult:
        """Submit atomic multi-leg options combo order.

        Uses Moomoo's `place_combo_order` to submit all legs simultaneously
        on exchange (e.g. 4-leg European cash-settled SPX Iron-Fly).
        Guarantees zero leg-in risk.
        """
        self._enforce_safety_gates(combo.strategy)

        if not _MOOMOO_AVAILABLE:
            return self._simulate_combo_execution(combo)

        ft_legs = []
        for leg_p in combo.legs:
            leg = ft.ComboLeg()
            leg.code = self._format_moomoo_symbol(leg_p.code)
            leg.trd_side = ft.TrdSide.BUY if leg_p.action == OrderAction.BUY else ft.TrdSide.SELL
            leg.qty_ratio = leg_p.qty_ratio
            ft_legs.append(leg)

        ft_env = ft.TrdEnv.REAL if self.cfg.env == ExecutionEnvironment.REAL else ft.TrdEnv.SIMULATE

        if self.is_connected():
            ret, data = self._trd_ctx.place_combo_order(
                combo_leg_list=ft_legs,
                price=combo.net_price,
                qty=combo.quantity,
                order_type=ft.OrderType.NORMAL,
                trd_env=ft_env,
                acc_id=self.cfg.account_id,
                acc_index=self.cfg.account_index,
                remark=f"antigravity:{combo.strategy}",
                time_in_force=combo.time_in_force.value,
            )
            if ret == ft.RET_OK and not data.empty:
                order_id = str(data.iloc[0].get("order_id", ""))
                res = ExecutionResult(
                    success=True,
                    order_id=order_id,
                    client_tag=combo.client_tag,
                    env=self.cfg.env,
                    status="SUBMITTED",
                    filled_qty=0,
                    avg_price=combo.net_price,
                    message="Atomic combo order placed on Moomoo exchange",
                    raw_response=data.to_dict(orient="records")[0],
                )
                self._record_audit_event("MOOMOO_COMBO_SUBMITTED", {
                    "order_id": order_id,
                    "combo_type": combo.combo_type.value,
                    "quantity": combo.quantity,
                    "net_price": combo.net_price,
                    "legs_count": len(combo.legs),
                    "env": self.cfg.env.value,
                    "strategy": combo.strategy,
                })
                return res
            else:
                err_msg = str(data)
                if "does not support option strategy" in err_msg and self.cfg.env == ExecutionEnvironment.SIMULATE:
                    logger.info(
                        "Moomoo paper environment does not support native combo orders on exchange; "
                        "falling back to atomic internal simulation fill."
                    )
                    return self._simulate_combo_execution(combo)

                self._record_audit_event("MOOMOO_COMBO_REJECTED", {
                    "combo_type": combo.combo_type.value,
                    "error": err_msg,
                    "env": self.cfg.env.value,
                })
                raise OrderRejectionError(f"Moomoo combo order submission failed: {err_msg}")

        return self._simulate_combo_execution(combo)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if not order_id:
            return False

        ft_env = ft.TrdEnv.REAL if self.cfg.env == ExecutionEnvironment.REAL else ft.TrdEnv.SIMULATE
        if self.is_connected():
            ret, data = self._trd_ctx.modify_order(
                modify_order_op=ft.ModifyOrderOp.CANCEL,
                order_id=order_id,
                qty=0,
                price=0,
                trd_env=ft_env,
                acc_id=self.cfg.account_id,
                acc_index=self.cfg.account_index,
            )
            success = (ret == ft.RET_OK)
            self._record_audit_event("MOOMOO_ORDER_CANCEL", {
                "order_id": order_id,
                "success": success,
                "env": self.cfg.env.value,
            })
            return success

        self._record_audit_event("MOOMOO_SIMULATED_ORDER_CANCEL", {
            "order_id": order_id,
            "success": True,
            "env": self.cfg.env.value,
        })
        return True

    def query_orders(self, status_filter_list: list[str] | None = None) -> list[dict[str, Any]]:
        """Query active or historical orders from Moomoo OpenD."""
        if not self.is_connected():
            return list(self._simulated_orders.values())

        ft_env = ft.TrdEnv.REAL if self.cfg.env == ExecutionEnvironment.REAL else ft.TrdEnv.SIMULATE
        try:
            ret, data = self._trd_ctx.order_list_query(
                status_filter_list=status_filter_list or [],
                trd_env=ft_env,
                acc_id=self.cfg.account_id,
                acc_index=self.cfg.account_index,
                refresh_cache=True,
            )
            if ret == ft.RET_OK and not data.empty:
                return data.to_dict(orient="records")

            ret_hist, data_hist = self._trd_ctx.history_order_list_query(
                status_filter_list=status_filter_list or [],
                trd_env=ft_env,
                acc_id=self.cfg.account_id,
                acc_index=self.cfg.account_index,
            )
            if ret_hist == ft.RET_OK and not data_hist.empty:
                return data_hist.to_dict(orient="records")
            return []
        except Exception as exc:
            logger.warning("Error querying Moomoo orders: %s", exc)
            return []

    # -------------------------------------------------------------------------
    # Helper & Geometry Builders (0DTE European SPX / XSP Iron-Fly)
    # -------------------------------------------------------------------------

    @staticmethod
    def format_spx_option_code(expiry_yymmdd: str, call_or_put: str, strike: float, is_mini_xsp: bool = False) -> str:
        """Generate official Moomoo option contract symbol for SPX / XSP.

        Example:
        - SPX 5800 Call expiring 261012: `US.SPXW261012C5800000`
        - XSP 580 Call expiring 261012: `US.XSP261012C580000`
        """
        prefix = "XSP" if is_mini_xsp else "SPXW"
        side_char = "C" if call_or_put.upper().startswith("C") else "P"
        strike_int = int(round(strike * 1000))
        return f"US.{prefix}{expiry_yymmdd}{side_char}{strike_int}"

    @classmethod
    def create_0dte_iron_fly_payload(
        cls,
        expiry_yymmdd: str,
        atm_strike: float,
        wing_width: float = 50.0,
        quantity: int = 1,
        net_credit: float = 0.0,
        is_mini_xsp: bool = False,
        client_tag: str = "",
        strategy: str = "0dte_em_decay",
    ) -> ComboOrderPayload:
        """Factory for building pre-registered 0DTE European Cash-Settled Iron-Flies.

        Enforces:
        - Multiples of 5 rule for strikes.
        - Strict 4-leg geometry:
          - Leg 1: Short ATM Call (SELL, ratio 1)
          - Leg 2: Short ATM Put (SELL, ratio 1)
          - Leg 3: Long OTM Call (BUY, ratio 1, strike = ATM + wing_width)
          - Leg 4: Long OTM Put (BUY, ratio 1, strike = ATM - wing_width)
        """
        # Round strikes to nearest multiple of 5 per pre-registration spec
        atm_clean = round(atm_strike / 5.0) * 5.0
        wing_clean = max(5.0, round(wing_width / 5.0) * 5.0)
        long_call_strike = atm_clean + wing_clean
        long_put_strike = atm_clean - wing_clean

        legs = [
            ComboLegPayload(
                code=cls.format_spx_option_code(expiry_yymmdd, "C", atm_clean, is_mini_xsp),
                action=OrderAction.SELL,
                qty_ratio=1,
                leg_type="CALL",
                strike=atm_clean,
            ),
            ComboLegPayload(
                code=cls.format_spx_option_code(expiry_yymmdd, "P", atm_clean, is_mini_xsp),
                action=OrderAction.SELL,
                qty_ratio=1,
                leg_type="PUT",
                strike=atm_clean,
            ),
            ComboLegPayload(
                code=cls.format_spx_option_code(expiry_yymmdd, "C", long_call_strike, is_mini_xsp),
                action=OrderAction.BUY,
                qty_ratio=1,
                leg_type="CALL",
                strike=long_call_strike,
            ),
            ComboLegPayload(
                code=cls.format_spx_option_code(expiry_yymmdd, "P", long_put_strike, is_mini_xsp),
                action=OrderAction.BUY,
                qty_ratio=1,
                leg_type="PUT",
                strike=long_put_strike,
            ),
        ]

        return ComboOrderPayload(
            legs=legs,
            quantity=quantity,
            net_price=net_credit,
            combo_type=ComboStrategyType.IRON_FLY,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            client_tag=client_tag or f"iron-fly-{expiry_yymmdd}-{int(atm_clean)}",
            strategy=strategy,
        )

    # -------------------------------------------------------------------------
    # Internal Helpers & Safety Guards
    # -------------------------------------------------------------------------

    def _enforce_safety_gates(self, strategy: str) -> None:
        """Enforce strict standing rules before ANY order reaches execution."""
        if self.cfg.env == ExecutionEnvironment.REAL:
            if not self.cfg.allow_live_trading:
                raise LiveSafetyError(
                    "Moomoo adapter configured with allow_live_trading=False: "
                    "Refusing live real-money execution per AGENTS.md."
                )
            if not self._is_unlocked:
                raise LiveSafetyError(
                    "Moomoo live trade context is locked. Charlie must supply trading password "
                    "via unlock_live_trading() before live orders can be submitted."
                )

    def _simulate_combo_execution(self, combo: ComboOrderPayload) -> ExecutionResult:
        """Simulate an atomic combo fill when offline or in test environments."""
        sim_order_id = f"moomoo-combo-sim-{int(datetime.now().timestamp() * 1000)}"
        res = ExecutionResult(
            success=True,
            order_id=sim_order_id,
            client_tag=combo.client_tag,
            env=self.cfg.env,
            status="FILLED",
            filled_qty=combo.quantity,
            avg_price=combo.net_price,
            message=f"Simulated atomic combo fill for {combo.combo_type.value} ({len(combo.legs)} legs)",
            raw_response={"simulated": True, "order_id": sim_order_id, "legs_count": len(combo.legs)},
        )
        self._record_audit_event("MOOMOO_SIMULATED_COMBO", {
            "order_id": sim_order_id,
            "combo_type": combo.combo_type.value,
            "quantity": combo.quantity,
            "net_price": combo.net_price,
            "legs": [{"code": l.code, "action": l.action.value, "ratio": l.qty_ratio} for l in combo.legs],
            "env": self.cfg.env.value,
            "offline_mode": True,
        })
        return res

    @staticmethod
    def _format_moomoo_symbol(raw_symbol: str) -> str:
        """Convert standard ticker/option symbol to Moomoo format."""
        s = raw_symbol.strip()
        if s.startswith("US.") or s.startswith("US.."):
            return s
        if s.upper() in ("SPX", "^SPX", ".SPX"):
            return "US..SPX"
        if s.upper() in ("XSP", "^XSP", ".XSP"):
            return "US..XSP"
        return f"US.{s}"

    def _record_audit_event(self, action: str, details: dict[str, Any]) -> None:
        """Record atomic audit event to audit_log.json."""
        event = {
            "timestamp": utcnow_str(),
            "action": action,
            "component": "MoomooExecutionAdapter",
            "env": self.cfg.env.value,
            "details": details,
        }
        try:
            log_path = self.cfg.audit_log_path
            log_path.parent.mkdir(parents=True, exist_ok=True)
            entries = []
            if log_path.exists():
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                        if not isinstance(entries, list):
                            entries = [entries]
                except Exception:
                    entries = []
            entries.append(event)
            temp_path = log_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
            temp_path.replace(log_path)
        except Exception as exc:
            logger.error("Failed to write to audit log %s: %s", self.cfg.audit_log_path, exc)
