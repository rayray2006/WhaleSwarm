#!/usr/bin/env python3
"""CLI script to run a multi-market evolution series.

Reads a series configuration JSON file and executes the full
market-series loop using :class:`MarketSeriesController`.

Usage::

    python scripts/run_market_series.py --config path/to/series_config.json

Example config file::

    {
        "series_id": "us-election-2024-backtest",
        "series_name": "US Election 2024 Backtest",
        "market_cohort": "politics:medium:normal",
        "graph_id": "graph-uuid-here",
        "initial_agent_count": 100,
        "initial_balance": 1000.0,
        "kill_threshold": 0.0,
        "whale_threshold_percentile": 0.01,
        "elite_threshold_percentile": 0.001,
        "markets": [
            {
                "question": "Will Biden win the 2024 Democratic primary?",
                "outcome_a": "YES",
                "outcome_b": "NO",
                "initial_probability": 0.85,
                "winning_outcome": "NO",
                "documents": [],
                "max_rounds": 15,
                "category": "politics",
                "duration_days": 90
            },
            {
                "question": "Will Trump win the 2024 Republican primary?",
                "outcome_a": "YES",
                "outcome_b": "NO",
                "initial_probability": 0.60,
                "winning_outcome": "YES",
                "documents": [],
                "max_rounds": 15,
                "category": "politics",
                "duration_days": 120
            }
        ]
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.models.persistent_agent import MarketSeriesConfig
from app.services.market_series_controller import MarketSeriesController

logger = logging.getLogger(__name__)


def load_series_config(config_path: str) -> MarketSeriesConfig:
    """Load and validate a series configuration file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Generate series_id if not provided
    if not data.get("series_id"):
        data["series_id"] = str(uuid.uuid4())[:12]

    config = MarketSeriesConfig.from_dict(data)

    # Validation
    if not config.markets:
        raise ValueError("Series config must contain at least one market")

    if config.initial_agent_count < 2:
        raise ValueError("Need at least 2 agents")

    for i, market in enumerate(config.markets):
        if not market.question:
            raise ValueError(f"Market {i} has no question")
        if not (0 < market.initial_probability < 1):
            raise ValueError(
                f"Market {i} initial_probability must be in (0, 1), "
                f"got {market.initial_probability}"
            )

    return config


async def run_series(
    series_config: MarketSeriesConfig,
    app_config: Config,
) -> dict:
    """Run the market series and return the summary."""
    controller = MarketSeriesController(series_config, app_config)
    summary = await controller.run_series()
    return summary


def print_summary(summary: dict) -> None:
    """Print a human-readable summary to stdout."""
    print("\n" + "=" * 70)
    print(f"  SERIES COMPLETE: {summary.get('series_name', 'unnamed')}")
    print("=" * 70)
    print(f"  Series ID:       {summary.get('series_id', '?')}")
    print(f"  Markets run:     {summary.get('markets_run', 0)}")
    print(f"  Final pool size: {summary.get('final_pool_size', 0)}")

    balance_stats = summary.get("balance_stats", {})
    if balance_stats:
        print(f"\n  Balance Statistics:")
        print(f"    Mean:   ${balance_stats.get('mean', 0):,.2f}")
        print(f"    Median: ${balance_stats.get('median', 0):,.2f}")
        print(f"    Min:    ${balance_stats.get('min', 0):,.2f}")
        print(f"    Max:    ${balance_stats.get('max', 0):,.2f}")

    pnl_stats = summary.get("pnl_stats", {})
    if pnl_stats:
        print(f"\n  P&L Statistics:")
        print(f"    Mean PnL:       ${pnl_stats.get('mean', 0):,.2f}")
        print(f"    Total gains:    ${pnl_stats.get('total_positive', 0):,.2f}")
        print(f"    Total losses:   ${pnl_stats.get('total_negative', 0):,.2f}")

    tier_dist = summary.get("tier_distribution", {})
    if tier_dist:
        print(f"\n  Model Tier Distribution:")
        print(f"    Top (pro):  {tier_dist.get('top', 0)}")
        print(f"    Mid (whale): {tier_dist.get('mid', 0)}")
        print(f"    Base:       {tier_dist.get('base', 0)}")

    top_agents = summary.get("top_10_agents", [])
    if top_agents:
        print(f"\n  Top Agents:")
        print(f"  {'Rank':<6} {'Name':<25} {'PnL':>12} {'Balance':>12} {'Win%':>8} {'Tier':<6}")
        print("  " + "-" * 72)
        for rank, agent in enumerate(top_agents[:10], 1):
            print(
                f"  {rank:<6} {agent.get('name', '?'):<25} "
                f"${agent.get('total_pnl', 0):>10,.2f} "
                f"${agent.get('wallet_balance', 0):>10,.2f} "
                f"{agent.get('win_rate', 0) * 100:>6.1f}% "
                f"{agent.get('model_tier', '?'):<6}"
            )

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Run a multi-market agent evolution series"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the series configuration JSON file",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override the output directory for series results",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Load configs
    app_config = Config.from_env()
    series_config = load_series_config(args.config)

    logger.info(
        "Loaded series '%s' with %d markets and %d initial agents",
        series_config.series_name,
        len(series_config.markets),
        series_config.initial_agent_count,
    )

    # Run
    summary = asyncio.run(run_series(series_config, app_config))

    # Print results
    print_summary(summary)

    # Report output location
    series_dir = os.path.join(
        app_config.upload_dir, "series", series_config.series_id
    )
    print(f"\nFull results saved to: {series_dir}")


if __name__ == "__main__":
    main()
