"""Macro regime classification from a trend/z-score panel.

Regimes:

- ``EXPANSION`` — the market is pricing economic growth: the ratio sits
  *above* its long moving average *and* unusually high (positive z-score).
- ``CONTRACTION`` — the mirror: ratio below its long MA and unusually low.
- ``NEUTRAL`` — everything else.  Most days are NEUTRAL; that is by design.

The classifier is written against *generic* keys (``value``/``ma``/``z`` via
``value_key``/``ma_key``/``z_key``) so future indicators in the registry
can reuse it without touching this module's contract.

Whipsaw control: a regime change only takes effect after the raw signal
persists for ``persist_days`` consecutive sessions.  A single-day spike
through a threshold does not flip the regime.
"""

from __future__ import annotations

EXPANSION = "EXPANSION"
CONTRACTION = "CONTRACTION"
NEUTRAL = "NEUTRAL"

REGIMES = (EXPANSION, CONTRACTION, NEUTRAL)

PRESETS: dict[str, dict] = {
    # z_threshold: |z| needed to leave NEUTRAL
    # persist_days: consecutive sessions the raw signal must hold
    # transition_dz: |Δz| over transition_window sessions that fires an alert
    # transition_window: lookback for the Δz alert
    "sensitive": {
        "z_threshold": 0.75,
        "persist_days": 3,
        "transition_dz": 1.0,
        "transition_window": 21,
    },
    "standard": {
        "z_threshold": 1.0,
        "persist_days": 5,
        "transition_dz": 1.5,
        "transition_window": 21,
    },
    "calm": {
        "z_threshold": 1.5,
        "persist_days": 10,
        "transition_dz": 2.0,
        "transition_window": 21,
    },
}


def _preset(name: str) -> dict:
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose from {sorted(PRESETS)}")
    return PRESETS[name]


def _raw_regime(row: dict, thr: float, value_key: str, ma_key: str,
                z_key: str) -> str:
    z, ma, value = row.get(z_key), row.get(ma_key), row.get(value_key)
    if z is None or ma is None or value is None:
        return NEUTRAL  # insufficient history: abstain
    if z > thr and value > ma:
        return EXPANSION
    if z < -thr and value < ma:
        return CONTRACTION
    return NEUTRAL


def classify_regime(
    rows: list[dict],
    preset: str = "standard",
    value_key: str = "ratio",
    ma_key: str = "ratio_ma200",
    z_key: str = "z_252",
) -> list[dict]:
    """Classify each row; adds ``regime`` and ``regime_raw``.

    Starts at NEUTRAL and only leaves it after the raw signal persists for
    ``persist_days`` sessions (whipsaw control).  Rows are never reordered.
    """
    cfg = _preset(preset)
    thr, persist = cfg["z_threshold"], cfg["persist_days"]
    out: list[dict] = []
    current, candidate, run = NEUTRAL, NEUTRAL, 0
    for r in rows:
        raw = _raw_regime(r, thr, value_key, ma_key, z_key)
        if raw == candidate:
            run += 1
        else:
            candidate, run = raw, 1
        if candidate != current and run >= persist:
            current = candidate
        row = dict(r)
        row["regime"] = current
        row["regime_raw"] = raw
        out.append(row)
    return out


def detect_transitions(
    rows: list[dict],
    preset: str = "standard",
    z_key: str = "z_252",
) -> list[dict]:
    """Fire alerts on fast z-score moves: ``|z_t - z_{t-window}| > dz``.

    Catches sharp regime *shifts* (e.g. a growth scare) days before the
    persisted regime label flips.  Returns a list of
    ``{"date", "direction", "dz", "z"}`` dicts, ascending by date.
    """
    cfg = _preset(preset)
    window, dz_thr = cfg["transition_window"], cfg["transition_dz"]
    alerts: list[dict] = []
    for i in range(window, len(rows)):
        z_now, z_then = rows[i].get(z_key), rows[i - window].get(z_key)
        if z_now is None or z_then is None:
            continue
        dz = z_now - z_then
        if abs(dz) > dz_thr:
            alerts.append({
                "date": rows[i]["date"],
                "direction": "expansionary" if dz > 0 else "contractionary",
                "dz": dz,
                "z": z_now,
            })
    return alerts
