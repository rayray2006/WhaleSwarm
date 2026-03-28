#!/usr/bin/env python3
"""Build empirical CDF tables from raw Polymarket trade data.

Reads the output of :mod:`scripts.collect_polymarket_data` and produces
the ``cdfs.json`` file consumed by :class:`BetSizeCalibrator`.

The build process (PRD section 6.3):

1. Load raw trades and market metadata.
2. Classify each market into a cohort (category x duration x liquidity).
3. Estimate each wallet's balance at the time of each trade.
4. Bucket wallets by wealth tier.
5. For each (cohort, bucket, position) triple, collect all bet sizes
   and sort them to form an empirical CDF.
6. Write the CDF store to JSON.

Usage::

    python scripts/build_cdf_tables.py \\
        --input-dir data/raw/polymarket \\
        --output data/polymarket_cdfs/cdfs.json

Requirements::

    pip install polars tqdm
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent directory to path so we can import from the project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from simulation_engine.simulations.polymarket.calibrator import (
    BetSizeCDF,
    WEALTH_BUCKETS,
    _get_wealth_bucket,
    classify_market_cohort,
)

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data loading
# ------------------------------------------------------------------

@dataclass
class TradeRecord:
    """Flattened trade record for CDF building."""
    wallet: str
    market_slug: str
    condition_id: str
    token_id: str
    side: str  # "buy" or "sell"
    amount_usd: float
    amount_shares: float
    timestamp: int
    category: str
    duration_days: int
    total_volume: float
    position: str  # "YES" or "NO"


def load_markets(input_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load market metadata, keyed by condition_id."""
    markets_path = input_dir / "markets.json"
    if not markets_path.exists():
        logger.warning("No markets.json found in %s", input_dir)
        return {}

    with open(markets_path, "r") as f:
        raw = json.load(f)

    markets = {}
    for m in raw:
        cid = m.get("condition_id", "")
        if cid:
            # Compute duration in days
            try:
                created = datetime.fromisoformat(
                    m.get("created_at", "2024-01-01").replace("Z", "+00:00")
                )
                ended = datetime.fromisoformat(
                    m.get("end_date", "2024-12-31").replace("Z", "+00:00")
                )
                duration_days = max(1, (ended - created).days)
            except (ValueError, TypeError):
                duration_days = 30  # default

            markets[cid] = {
                **m,
                "duration_days": duration_days,
            }

    logger.info("Loaded %d markets", len(markets))
    return markets


def load_trades(input_dir: Path) -> List[Dict[str, Any]]:
    """Load raw trade records."""
    trades_path = input_dir / "trades.json"
    if not trades_path.exists():
        logger.warning("No trades.json found in %s", input_dir)
        return []

    with open(trades_path, "r") as f:
        raw = json.load(f)

    logger.info("Loaded %d raw trades", len(raw))
    return raw


# ------------------------------------------------------------------
# Wallet balance estimation
# ------------------------------------------------------------------

def estimate_wallet_balances(
    trades: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Estimate each wallet's peak balance from cumulative trade flow.

    For each wallet, track cumulative (buys - sells) and take the
    maximum as a proxy for allocated capital.  This is an approximation;
    the true balance would require on-chain USDC queries.
    """
    wallet_flows: Dict[str, List[Tuple[int, float]]] = defaultdict(list)

    for t in trades:
        wallet = t.get("wallet", "").lower()
        amount = float(t.get("amount_usd", 0))
        ts = int(t.get("timestamp", 0))
        side = t.get("side", "buy")

        if side == "buy":
            wallet_flows[wallet].append((ts, amount))
        else:
            wallet_flows[wallet].append((ts, -amount))

    balances: Dict[str, float] = {}
    for wallet, flows in wallet_flows.items():
        flows.sort(key=lambda x: x[0])
        cumulative = 0.0
        peak = 0.0
        for _, delta in flows:
            cumulative += delta
            peak = max(peak, cumulative)
        balances[wallet] = peak

    logger.info("Estimated balances for %d wallets", len(balances))
    return balances


# ------------------------------------------------------------------
# CDF builder
# ------------------------------------------------------------------

def build_cdf_tables(
    input_dir: str | Path,
    output_path: str | Path,
    min_bettors: int = 3,
) -> Dict[str, BetSizeCDF]:
    """Build empirical CDF tables from raw data.

    Parameters
    ----------
    input_dir:
        Directory containing ``markets.json`` and ``trades.json``
        (output of :func:`collect_polymarket_data`).
    output_path:
        Path to write the resulting ``cdfs.json``.
    min_bettors:
        Minimum number of unique bettors required to include a CDF
        in the output.  Slices with fewer bettors are dropped.

    Returns
    -------
    Dict[str, BetSizeCDF]
        The built CDF store, also written to ``output_path``.
    """
    input_dir = Path(input_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Load data
    markets = load_markets(input_dir)
    raw_trades = load_trades(input_dir)

    if not markets or not raw_trades:
        logger.warning(
            "No data to process (markets=%d, trades=%d). "
            "Writing empty CDF file.",
            len(markets), len(raw_trades),
        )
        with open(output_path, "w") as f:
            json.dump({}, f)
        return {}

    # Step 2: Estimate wallet balances
    wallet_balances = estimate_wallet_balances(raw_trades)

    # Step 3: Classify markets into cohorts
    market_cohorts: Dict[str, str] = {}
    for cid, m in markets.items():
        cohort = classify_market_cohort(
            category=m.get("category", "other"),
            duration_days=m.get("duration_days", 30),
            total_volume=float(m.get("volume", 0)),
        )
        market_cohorts[cid] = cohort

    # Step 4: Bucket trades by (cohort, wealth_bucket, position)
    # Key: "cohort:bucket:position" -> list of bet sizes
    bet_size_buckets: Dict[str, List[float]] = defaultdict(list)
    # Track unique bettors per bucket
    bettor_sets: Dict[str, set] = defaultdict(set)

    for trade in raw_trades:
        cid = trade.get("market_condition_id", "")
        if cid not in market_cohorts:
            continue

        wallet = trade.get("wallet", "").lower()
        side = trade.get("side", "")
        amount_usd = float(trade.get("amount_usd", 0))

        # Only count buys for bet-size calibration
        if side != "buy" or amount_usd <= 0:
            continue

        # Determine position (YES/NO) from token_id
        market = markets.get(cid, {})
        token_id = str(trade.get("token_id", ""))
        if token_id == market.get("token_id_a", ""):
            position = "YES"
        elif token_id == market.get("token_id_b", ""):
            position = "NO"
        else:
            # Unknown token, try to infer from trade metadata
            position = "YES"  # default

        # Get wealth bucket from estimated balance
        balance = wallet_balances.get(wallet, 0.0)
        bucket = _get_wealth_bucket(balance)

        # Build key
        cohort = market_cohorts[cid]
        key = f"{cohort}:{bucket}:{position}"

        bet_size_buckets[key].append(amount_usd)
        bettor_sets[key].add(wallet)

    # Step 5: Sort bet sizes to form empirical CDFs
    cdf_store: Dict[str, BetSizeCDF] = {}

    for key, sizes in bet_size_buckets.items():
        n_bettors = len(bettor_sets.get(key, set()))

        if n_bettors < min_bettors:
            logger.debug(
                "Skipping %s: only %d bettors (need %d)",
                key, n_bettors, min_bettors,
            )
            continue

        parts = key.split(":")
        # key format: "cat:dur:liq:bucket:position"
        if len(parts) == 5:
            cohort = f"{parts[0]}:{parts[1]}:{parts[2]}"
            bucket = parts[3]
            position = parts[4]
        else:
            cohort = key
            bucket = "unknown"
            position = "YES"

        sorted_sizes = sorted(sizes)

        cdf_store[key] = BetSizeCDF(
            market_cohort=cohort,
            wealth_bucket=bucket,
            position=position,
            sorted_bet_sizes=sorted_sizes,
            n_bettors=n_bettors,
        )

    # Step 6: Serialize to JSON
    serializable = {}
    for key, cdf in cdf_store.items():
        serializable[key] = {
            "market_cohort": cdf.market_cohort,
            "wealth_bucket": cdf.wealth_bucket,
            "position": cdf.position,
            "sorted_bet_sizes": [round(s, 2) for s in cdf.sorted_bet_sizes],
            "n_bettors": cdf.n_bettors,
        }

    with open(output_path, "w") as f:
        json.dump(serializable, f, indent=2)

    logger.info(
        "Built %d CDF entries -> %s",
        len(cdf_store),
        output_path,
    )

    # Also write metadata
    metadata_path = output_path.parent / "metadata.json"
    metadata = {
        "version": "1.0.0",
        "description": "Empirical bet-size CDFs built from Polymarket trade data.",
        "collection_window": {
            "source_dir": str(input_dir),
        },
        "freshness": {
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "refresh_cadence": "monthly",
        },
        "statistics": {
            "total_markets_analyzed": len(markets),
            "total_trades_processed": len(raw_trades),
            "total_unique_wallets": len(wallet_balances),
            "cdf_entries_generated": len(cdf_store),
            "min_bettors_threshold": min_bettors,
        },
        "schema_version": "1.0",
        "generated_by": "scripts/build_cdf_tables.py",
    }

    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return cdf_store


# ------------------------------------------------------------------
# Diagnostics
# ------------------------------------------------------------------

def print_cdf_summary(cdf_store: Dict[str, BetSizeCDF]) -> None:
    """Print a summary table of the built CDFs."""
    print(f"\n{'Key':<50} {'Bettors':>8} {'Median':>10} {'P90':>10} {'Max':>10}")
    print("-" * 92)

    for key in sorted(cdf_store.keys()):
        cdf = cdf_store[key]
        median = cdf.sample_at_quantile(0.5)
        p90 = cdf.sample_at_quantile(0.9)
        max_bet = cdf.sorted_bet_sizes[-1] if cdf.sorted_bet_sizes else 0
        print(
            f"{key:<50} {cdf.n_bettors:>8} "
            f"${median:>9.2f} ${p90:>9.2f} ${max_bet:>9.2f}"
        )

    print(f"\nTotal CDF entries: {len(cdf_store)}")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build empirical CDF tables from raw Polymarket data"
    )
    parser.add_argument(
        "--input-dir",
        default="data/raw/polymarket",
        help="Directory with markets.json and trades.json",
    )
    parser.add_argument(
        "--output",
        default="data/polymarket_cdfs/cdfs.json",
        help="Output CDF JSON file path",
    )
    parser.add_argument(
        "--min-bettors",
        type=int,
        default=3,
        help="Minimum unique bettors per CDF slice (default: 3)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    cdf_store = build_cdf_tables(
        input_dir=args.input_dir,
        output_path=args.output,
        min_bettors=args.min_bettors,
    )

    print_cdf_summary(cdf_store)


if __name__ == "__main__":
    main()
