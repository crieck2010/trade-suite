"""Hedge configurations: conservative / balanced / aggressive presets.

A config is a plain dict. Every key below is honored by the rules engine;
unknown keys are ignored. Merge over DEFAULT_CONFIG with dict unpacking.
"""

from __future__ import annotations

DEFAULT_CONFIG: dict = {
    "equity": 100_000.0,            # account equity; exposure fractions divide by this
    "delta_target": 0.0,            # beta-adjusted net delta target (fraction of equity)
    "hysteresis_band": 0.02,        # no-trade zone around target: |d - target| <= band -> no proposal
    "hedge_instrument": "SPY",      # configurable; mapping to a real instrument is user config
    "hedge_instrument_beta": 1.0,   # assumed beta of the hedge instrument vs the portfolio
    "vol_target": 0.15,             # annualized target portfolio vol
    "vol_act_threshold": 1.25,      # act when realized vol > target * threshold
    "vol_realized_window": 63,      # trailing window (bars) for realized vol
    "use_volforecast": False,       # prefer trade-volforecast's estimator when installed
    "gross_cap": 2.0,               # gross exposure cap (fraction of equity)
    "net_cap": 1.0,                 # net exposure cap (fraction of equity, absolute)
    "cap_trim_mode": "highest_beta_first",  # or "pro_rata"
    "max_drawdown": 0.10,           # kill-switch: halt beyond this drawdown
    "max_stale_minutes": 60,        # kill-switch: halt when prices older than this
    "betas": {},                    # symbol -> beta; absent symbols default to 1.0
    "concentration_top_n": 5,       # top-N share window for concentration stats
}

PRESETS: dict[str, dict] = {
    "conservative": {
        **DEFAULT_CONFIG,
        "hysteresis_band": 0.01,
        "vol_target": 0.10,
        "vol_act_threshold": 1.15,
        "gross_cap": 1.2,
        "net_cap": 0.5,
        "max_drawdown": 0.06,
        "max_stale_minutes": 30,
    },
    "balanced": dict(DEFAULT_CONFIG),
    "aggressive": {
        **DEFAULT_CONFIG,
        "hysteresis_band": 0.04,
        "vol_target": 0.25,
        "vol_act_threshold": 1.5,
        "gross_cap": 3.0,
        "net_cap": 1.5,
        "max_drawdown": 0.20,
        "max_stale_minutes": 240,
        "cap_trim_mode": "pro_rata",
    },
}


def describe_presets() -> list[dict]:
    """One row per preset: name + the keys that differ from the default."""
    rows = []
    for name, cfg in PRESETS.items():
        diff = {k: v for k, v in cfg.items() if DEFAULT_CONFIG.get(k) != v}
        rows.append({"name": name, "differs_from_default": diff})
    return rows
