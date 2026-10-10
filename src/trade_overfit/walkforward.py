"""Walk-forward analysis: rolling train/test windows, out-of-sample honesty."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ._stats import median
from .metrics import max_drawdown, sharpe_ratio, total_return


@dataclass
class WindowResult:
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    is_sharpe: float | None
    oos_sharpe: float | None
    oos_return: float | None
    oos_max_drawdown: float | None


def _windows(n: int, train_len: int, test_len: int, step: int,
             anchored: bool) -> list[tuple[int, int, int, int]]:
    """(train_start, train_end, test_start, test_end) index tuples."""
    out = []
    start = 0
    while True:
        test_start = start + train_len
        test_end = test_start + test_len
        if test_end > n:
            break
        train_start = 0 if anchored else start
        out.append((train_start, test_start, test_start, test_end))
        start += step
    return out


def walk_forward(returns: list[float], train_len: int = 252, test_len: int = 63,
                 step: int | None = None, anchored: bool = False,
                 rf_annual: float = 0.0, periods: int = 252) -> dict:
    """Walk-forward train/test analysis over ``returns``.

    - ``anchored=False`` (default): rolling fixed-length train window.
    - ``anchored=True``: train window grows from bar 0 (expanding).
    - ``step`` defaults to ``test_len`` (non-overlapping test windows).

    Returns plain-data dict with per-window results plus a summary:
    median/mean OOS Sharpe, OOS hit-rate (fraction of windows with OOS
    Sharpe > 0), mean in-sample Sharpe, and train-vs-OOS degradation.
    """
    n = len(returns)
    step = test_len if step is None else step
    wins = _windows(n, train_len, test_len, step, anchored)
    results: list[WindowResult] = []
    for ts, te, ss, se in wins:
        train = returns[ts:te]
        test = returns[ss:se]
        dd = max_drawdown(test)
        results.append(WindowResult(
            train_start=ts, train_end=te, test_start=ss, test_end=se,
            is_sharpe=sharpe_ratio(train, rf_annual, periods),
            oos_sharpe=sharpe_ratio(test, rf_annual, periods),
            oos_return=total_return(test),
            oos_max_drawdown=dd["max_drawdown"],
        ))
    oos = [w.oos_sharpe for w in results if w.oos_sharpe is not None]
    iss = [w.is_sharpe for w in results if w.is_sharpe is not None]
    mean_oos = sum(oos) / len(oos) if oos else None
    mean_is = sum(iss) / len(iss) if iss else None
    summary = {
        "n_windows": len(results),
        "train_len": train_len,
        "test_len": test_len,
        "step": step,
        "anchored": anchored,
        "median_oos_sharpe": median(oos),
        "mean_oos_sharpe": mean_oos,
        "oos_hit_rate": (sum(1 for s in oos if s > 0.0) / len(oos)) if oos else None,
        "mean_is_sharpe": mean_is,
        # Degradation: how much Sharpe evaporates out of sample. Positive = decay.
        "degradation": (mean_is - mean_oos) if (mean_is is not None and mean_oos is not None) else None,
    }
    return {"windows": [asdict(w) for w in results], "summary": summary}
