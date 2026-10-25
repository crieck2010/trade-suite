#!/usr/bin/env python3
"""Run one REGCOND-1 paper-campaign session (live-roadmap Phase 2).

On Charlie's PC, with OpenD running and logged into the SIMULATE
(paper) account:

    pip install -e ".[live,execution]"
    python scripts/run_regcond1_campaign.py

Fetches real delayed daily closes, replays the frozen REGCOND-1
strategy, advances the incubation program by one day, places any due
monthly rebalance through the safety kernel into the Moomoo paper
account, and writes the day record + digest under the campaign dir
(default ~/.trade-campaign/regcond1).

Flags:
    --source demo       deterministic synthetic closes (plumbing only)
    --dry-run           compute the rebalance, submit nothing
    --allow-offline     proceed even if OpenD is not connected (the
                        adapter's offline simulation is used — NOT the
                        real paper account; for plumbing checks)
    --campaign-dir DIR  override the campaign state directory
    --json              print the run summary as JSON instead of the digest

Exit codes: 0 = ok / already current, 2 = pre-flight failed,
3 = offline without --allow-offline, 1 = other error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="yfinance",
                        choices=["yfinance", "demo"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-offline", action="store_true")
    parser.add_argument("--campaign-dir", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from trade_campaign import CampaignConfig, run_campaign_day
    from trade_campaign.data import fetch_closes

    cfg = CampaignConfig(bars_source=args.source)
    if args.campaign_dir:
        cfg.campaign_dir = Path(args.campaign_dir)
        cfg.__post_init__()

    from trade_execution import (
        EnvironmentType,
        MoomooAdapterConfig,
        MoomooExecutionAdapter,
    )

    adapter = MoomooExecutionAdapter(MoomooAdapterConfig(
        env=EnvironmentType.SIMULATE,
        auto_launch_opend=False,
        safety_config=cfg.safety,
        safety_state_path=str(cfg.safety_state_path),
        audit_log_path=str(cfg.audit_log_path),
    ))
    adapter.connect()
    if not adapter.is_connected() and not args.allow_offline:
        print("OpenD is not connected — this run would use the "
              "adapter's offline simulation, not your paper account. "
              "Start OpenD, log into the SIMULATE account, and re-run; "
              "or pass --allow-offline for a plumbing check.")
        return 3

    closes = fetch_closes(list(cfg.symbols), cfg.history_days,
                          source=cfg.bars_source)
    summary = run_campaign_day(cfg, adapter, closes,
                               safety_kernel=adapter.safety,
                               dry_run=args.dry_run)
    if args.json:
        print(json.dumps(summary, indent=1, default=str))
    elif summary.get("digest"):
        print(summary["digest"])
    else:
        print(json.dumps(summary, indent=1, default=str))
    if summary["status"] == "preflight_failed":
        return 2
    return 0 if summary["status"] in ("ok", "already_current") else 1


if __name__ == "__main__":
    sys.exit(main())
