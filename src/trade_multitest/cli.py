"""Command line: multiplicity-adjusted verdicts for a research round.

Reads a JSON or CSV file describing one research round's trials and
prints per-trial verdicts (``validated`` / ``invalidated``) under each
available correction, plus the round-level Reality Check / SPA verdict
when return series are supplied.

JSON schema (see ``docs/INTEROP.md`` for the versioned interchange)::

    {
      "periods_per_year": 252,
      "alpha": 0.05,
      "seed": 0,
      "n_boot": 1000,
      "benchmark_returns": [ ... ],          # optional
      "trials": [
        {"name": "idea-a", "sharpe": 1.2, "skew": 0.1, "kurt": 3.2,
         "returns": [ ... ]},                # returns optional
        ...
      ]
    }

CSV columns: ``name, sharpe[, skew, kurt, n_obs]`` (no return series —
DSR only; the bootstrap tests need full series, use JSON).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

from .dsr import dsr
from .holm import holm, t_test_pvalues
from .reality_check import reality_check
from .spa import spa_test

__all__ = ["load_round", "evaluate_round", "main"]


def load_round(path):
    """Load a research-round file (JSON or CSV) into a plain-data dict."""
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    elif path.endswith(".csv"):
        trials = []
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                trial = {"name": row["name"], "sharpe": float(row["sharpe"])}
                for key in ("skew", "kurt", "n_obs"):
                    if row.get(key):
                        trial[key] = float(row[key])
                trials.append(trial)
        data = {"trials": trials}
    else:
        raise ValueError("round file must be .json or .csv")
    if not data.get("trials"):
        raise ValueError("round file contains no trials")
    return data


def evaluate_round(data):
    """Evaluate every correction available for the round's data.

    Returns the ``multitest.report.v1`` dict (see docs/INTEROP.md).
    """
    trials = data["trials"]
    ppy = int(data.get("periods_per_year", 252))
    alpha = float(data.get("alpha", 0.05))
    seed = int(data.get("seed", 0))
    n_boot = int(data.get("n_boot", 1000))
    names = [t.get("name", f"trial-{i}") for i, t in enumerate(trials)]
    sharpes = [float(t["sharpe"]) for t in trials]
    n_obs = data.get("n_obs")

    per_trial = []
    for i, t in enumerate(trials):
        entry = {"name": names[i], "sharpe": sharpes[i]}
        n = int(t.get("n_obs", n_obs or 0))
        if n >= 2:
            entry["dsr"] = dsr(
                sharpes[i], sharpes, n,
                skew=float(t.get("skew", 0.0)),
                kurt=float(t.get("kurt", 3.0)),
                periods_per_year=ppy,
            )
            entry["dsr_verdict"] = (
                "validated" if entry["dsr"] > 0.8 else "invalidated"
            )
        else:
            entry["dsr"] = None
            entry["dsr_verdict"] = None
        per_trial.append(entry)

    report = {
        "schema": "multitest.report.v1",
        "n_trials": len(trials),
        "alpha": alpha,
        "periods_per_year": ppy,
        "per_trial": per_trial,
        "round_tests": {},
    }

    series = [t.get("returns") for t in trials]
    if all(s is not None for s in series):
        import numpy as np

        R = np.asarray(series, dtype=float).T  # (n_obs, n_trials)
        bench = data.get("benchmark_returns")
        B = np.asarray(bench, dtype=float) if bench is not None else None
        # Holm on raw one-sided t p-values (NOT on DSR outputs — the DSR
        # already carries the multiplicity correction; feeding 1-DSR into
        # Holm would double-count it).
        raw_p = t_test_pvalues(R, B)
        h = holm(raw_p, alpha)
        for entry, pv, adj, rej in zip(
            per_trial, raw_p, h["p_adjusted"], h["reject"]
        ):
            entry["t_pvalue"] = pv
            entry["holm_p_adjusted"] = adj
            entry["holm_verdict"] = "validated" if rej else "invalidated"
        report["round_tests"]["holm"] = {
            k: v for k, v in h.items() if k != "verdicts"
        }
        report["round_tests"]["reality_check"] = reality_check(
            R, B, n_boot=n_boot, seed=seed, alpha=alpha
        )
        report["round_tests"]["spa"] = spa_test(
            R, B, n_boot=n_boot, seed=seed, alpha=alpha
        )
    return report


def _print_report(report):
    print(f"trade-multitest round report  (n_trials={report['n_trials']}, "
          f"alpha={report['alpha']})")
    print("-" * 72)
    for t in report["per_trial"]:
        bits = [f"{t['name']:24s} sharpe={t['sharpe']:+.3f}"]
        if t.get("dsr") is not None:
            bits.append(f"DSR={t['dsr']:.3f} [{t['dsr_verdict']}]")
        if t.get("holm_verdict"):
            bits.append(f"Holm p_adj={t['holm_p_adjusted']:.4f} "
                        f"[{t['holm_verdict']}]")
        print("  " + "  ".join(bits))
    rt = report["round_tests"]
    if rt:
        print("-" * 72)
        rc = rt["reality_check"]
        print(f"  White Reality Check : p={rc['p_value']:.4f} "
              f"[{rc['verdict']}]  (best trial #{rc['best_trial']})")
        sp = rt["spa"]
        print(f"  Hansen SPA          : p={sp['p_value']:.4f} "
              f"[{sp['verdict']}]  (best trial #{sp['best_trial']})")
        print(f"  Holm rejected {rt['holm']['n_rejected']}/"
              f"{rt['holm']['n_trials']} trial nulls")


def main(argv=None):
    """Entry point for the ``trade-multitest`` console script."""
    ap = argparse.ArgumentParser(
        prog="trade-multitest",
        description="Multiplicity-adjusted verdicts for a research round.",
    )
    ap.add_argument("round_file", help="JSON or CSV research-round file")
    ap.add_argument("--json", action="store_true",
                    help="emit the multitest.report.v1 JSON instead of text")
    args = ap.parse_args(argv)
    try:
        report = evaluate_round(load_round(args.round_file))
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
