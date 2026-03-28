#!/usr/bin/env python3
"""Collect raw trade data from Polymarket (API) and Polygon (on-chain).

This script pulls two complementary data sources:

1. **Polymarket REST API** -- market metadata (question, slug, category,
   volume, timestamps).
2. **Polygon blockchain** -- on-chain CTF (Conditional Token Framework)
   ``TransferSingle`` / ``TransferBatch`` events to capture every trade
   with sender wallet, token ID, and amount.

The combined output is a set of Parquet files in ``data/raw/polymarket/``
that :mod:`scripts.build_cdf_tables` consumes to build empirical CDFs.

Usage::

    python scripts/collect_polymarket_data.py \\
        --output-dir data/raw/polymarket \\
        --from-date 2024-01-01 \\
        --to-date 2024-12-31

Requirements::

    pip install requests web3 polars tqdm
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

POLYMARKET_API_BASE = "https://clob.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"
POLYGON_RPC = "https://polygon-rpc.com"

# Polymarket CTF Exchange on Polygon
CTF_EXCHANGE_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_CTF_ADDRESS = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

# ERC-1155 TransferSingle event topic
TRANSFER_SINGLE_TOPIC = (
    "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
)


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------

@dataclass
class MarketMeta:
    """Metadata for a single Polymarket market."""
    condition_id: str = ""
    question: str = ""
    slug: str = ""
    category: str = ""
    end_date: str = ""
    created_at: str = ""
    volume: float = 0.0
    liquidity: float = 0.0
    outcome_a: str = "Yes"
    outcome_b: str = "No"
    token_id_a: str = ""
    token_id_b: str = ""
    resolved: bool = False
    winning_outcome: Optional[str] = None


@dataclass
class RawTrade:
    """A single on-chain trade event."""
    tx_hash: str = ""
    block_number: int = 0
    timestamp: int = 0
    wallet: str = ""
    token_id: str = ""
    amount_shares: float = 0.0
    amount_usd: float = 0.0
    side: str = ""  # "buy" or "sell"
    market_condition_id: str = ""


@dataclass
class CollectionResult:
    """Summary of a collection run."""
    markets_fetched: int = 0
    trades_fetched: int = 0
    wallets_seen: int = 0
    output_dir: str = ""
    errors: List[str] = field(default_factory=list)


# ------------------------------------------------------------------
# Polymarket API client (stubs)
# ------------------------------------------------------------------

class PolymarketAPIClient:
    """Client for the Polymarket REST / Gamma API.

    All methods are stubs that document the expected API endpoints and
    response shapes.  Replace the ``# STUB`` bodies with real HTTP calls
    when deploying.
    """

    def __init__(self, base_url: str = GAMMA_API_BASE) -> None:
        self.base_url = base_url
        # In production: self.session = requests.Session()

    def fetch_markets(
        self,
        from_date: str,
        to_date: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[MarketMeta]:
        """Fetch market metadata from the Gamma API.

        Endpoint: ``GET /markets``

        Query params::

            ?closed=true
            &start_date_min=<from_date>
            &start_date_max=<to_date>
            &limit=<limit>
            &offset=<offset>

        Response shape (per item)::

            {
                "condition_id": "0xabc...",
                "question": "Will X happen?",
                "slug": "will-x-happen",
                "category": "Politics",
                "end_date_iso": "2024-11-05T00:00:00Z",
                "start_date_iso": "2024-06-01T00:00:00Z",
                "volume": 1234567.89,
                "liquidity": 50000.00,
                "tokens": [
                    {"token_id": "12345", "outcome": "Yes"},
                    {"token_id": "12346", "outcome": "No"}
                ]
            }
        """
        # STUB: Replace with actual HTTP request
        # response = self.session.get(
        #     f"{self.base_url}/markets",
        #     params={
        #         "closed": "true",
        #         "start_date_min": from_date,
        #         "start_date_max": to_date,
        #         "limit": limit,
        #         "offset": offset,
        #     },
        # )
        # response.raise_for_status()
        # items = response.json()
        # return [self._parse_market(item) for item in items]
        logger.info(
            "STUB: fetch_markets(from=%s, to=%s, limit=%d, offset=%d)",
            from_date, to_date, limit, offset,
        )
        return []

    def fetch_market_by_slug(self, slug: str) -> Optional[MarketMeta]:
        """Fetch a single market by slug.

        Endpoint: ``GET /markets/<slug>``
        """
        # STUB
        logger.info("STUB: fetch_market_by_slug(%s)", slug)
        return None

    def fetch_prices_history(
        self,
        token_id: str,
        interval: str = "1h",
        fidelity: int = 60,
    ) -> List[Dict[str, Any]]:
        """Fetch historical price data for a token.

        Endpoint: ``GET /prices-history``

        Query params::

            ?market=<token_id>
            &interval=<interval>
            &fidelity=<fidelity>

        Response: list of ``{"t": unix_timestamp, "p": price_float}``
        """
        # STUB
        logger.info("STUB: fetch_prices_history(token=%s)", token_id)
        return []

    @staticmethod
    def _parse_market(raw: Dict[str, Any]) -> MarketMeta:
        """Parse a raw API response dict into a MarketMeta."""
        tokens = raw.get("tokens", [])
        token_a = tokens[0] if len(tokens) > 0 else {}
        token_b = tokens[1] if len(tokens) > 1 else {}
        return MarketMeta(
            condition_id=raw.get("condition_id", ""),
            question=raw.get("question", ""),
            slug=raw.get("slug", ""),
            category=raw.get("category", ""),
            end_date=raw.get("end_date_iso", ""),
            created_at=raw.get("start_date_iso", ""),
            volume=float(raw.get("volume", 0)),
            liquidity=float(raw.get("liquidity", 0)),
            outcome_a=token_a.get("outcome", "Yes"),
            outcome_b=token_b.get("outcome", "No"),
            token_id_a=str(token_a.get("token_id", "")),
            token_id_b=str(token_b.get("token_id", "")),
        )


# ------------------------------------------------------------------
# Polygon on-chain reader (stubs)
# ------------------------------------------------------------------

class PolygonTradeReader:
    """Read ERC-1155 transfer events from the Polymarket CTF contract.

    Uses ``eth_getLogs`` to fetch ``TransferSingle`` and ``TransferBatch``
    events, then maps token IDs back to market condition IDs.

    All methods are stubs.
    """

    def __init__(
        self,
        rpc_url: str = POLYGON_RPC,
        ctf_address: str = CTF_EXCHANGE_ADDRESS,
    ) -> None:
        self.rpc_url = rpc_url
        self.ctf_address = ctf_address
        # In production:
        # from web3 import Web3
        # self.w3 = Web3(Web3.HTTPProvider(rpc_url))

    def fetch_trades_for_market(
        self,
        token_id_a: str,
        token_id_b: str,
        from_block: int,
        to_block: int,
        condition_id: str = "",
    ) -> List[RawTrade]:
        """Fetch all on-chain trades for a market's token pair.

        Queries ``eth_getLogs`` for ``TransferSingle`` events where the
        ``id`` field matches either ``token_id_a`` or ``token_id_b``.

        Algorithm:
        1. Build log filter with topics for TransferSingle.
        2. Paginate in chunks of 2000 blocks (Polygon RPC limit).
        3. Decode each log:
           - ``from`` = zero address -> mint (buy from AMM)
           - ``to`` = zero address -> burn (sell to AMM)
           - Otherwise -> peer transfer (secondary market)
        4. Estimate USD value: shares * mid_price (from CLOB or AMM).
        """
        # STUB: Replace with actual web3 calls
        # contract = self.w3.eth.contract(
        #     address=self.ctf_address,
        #     abi=CTF_ABI,
        # )
        # event_filter = {
        #     "fromBlock": from_block,
        #     "toBlock": to_block,
        #     "address": self.ctf_address,
        #     "topics": [TRANSFER_SINGLE_TOPIC],
        # }
        # logs = self.w3.eth.get_logs(event_filter)
        # trades = []
        # for log in logs:
        #     decoded = contract.events.TransferSingle().process_log(log)
        #     trade = self._decode_trade(decoded, condition_id)
        #     if trade and trade.token_id in (token_id_a, token_id_b):
        #         trades.append(trade)
        # return trades
        logger.info(
            "STUB: fetch_trades_for_market(tokens=%s/%s, blocks=%d-%d)",
            token_id_a, token_id_b, from_block, to_block,
        )
        return []

    def get_block_at_timestamp(self, timestamp: int) -> int:
        """Binary-search for the block number closest to a unix timestamp.

        Uses ``eth_getBlockByNumber`` with bisection between genesis and
        latest block.
        """
        # STUB
        logger.info("STUB: get_block_at_timestamp(%d)", timestamp)
        return 0

    @staticmethod
    def _decode_trade(event: Dict, condition_id: str) -> Optional[RawTrade]:
        """Decode a raw TransferSingle event into a RawTrade."""
        # STUB
        return None


# ------------------------------------------------------------------
# Wallet balance estimator
# ------------------------------------------------------------------

def estimate_wallet_balance(
    wallet: str,
    trades: List[RawTrade],
) -> float:
    """Estimate a wallet's balance at time of each trade.

    Heuristic: cumulative sum of (buy costs - sell proceeds) gives a
    rough lower bound on the wallet's Polymarket-allocated capital.
    A more accurate approach would query USDC balance on Polygon.
    """
    # STUB: In production, query USDC.e balance on Polygon
    # or aggregate from CLOB order history.
    cumulative = 0.0
    for t in sorted(trades, key=lambda x: x.timestamp):
        if t.wallet.lower() == wallet.lower():
            if t.side == "buy":
                cumulative += t.amount_usd
            else:
                cumulative -= t.amount_usd
    return max(cumulative, 0.0)


# ------------------------------------------------------------------
# Main collection pipeline
# ------------------------------------------------------------------

def collect_polymarket_data(
    output_dir: str,
    from_date: str,
    to_date: str,
) -> CollectionResult:
    """Run the full data collection pipeline.

    Steps:
    1. Fetch all resolved markets in the date range from Gamma API.
    2. For each market, fetch on-chain trades from Polygon.
    3. Estimate wallet balances at trade time.
    4. Write raw trades and market metadata to Parquet files.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    result = CollectionResult(output_dir=output_dir)

    # -- Step 1: Fetch markets --
    api = PolymarketAPIClient()
    all_markets: List[MarketMeta] = []
    offset = 0
    page_size = 100

    while True:
        batch = api.fetch_markets(from_date, to_date, limit=page_size, offset=offset)
        if not batch:
            break
        all_markets.extend(batch)
        offset += page_size
        if len(batch) < page_size:
            break
        time.sleep(0.5)  # Rate limiting

    result.markets_fetched = len(all_markets)
    logger.info("Fetched %d markets", len(all_markets))

    # Save market metadata
    markets_path = output_path / "markets.json"
    with open(markets_path, "w") as f:
        json.dump([asdict(m) for m in all_markets], f, indent=2)

    # -- Step 2: Fetch on-chain trades --
    chain_reader = PolygonTradeReader()
    all_trades: List[RawTrade] = []
    wallets_seen: set = set()

    from_ts = int(datetime.fromisoformat(from_date).timestamp())
    to_ts = int(datetime.fromisoformat(to_date).timestamp())
    from_block = chain_reader.get_block_at_timestamp(from_ts)
    to_block = chain_reader.get_block_at_timestamp(to_ts)

    for market in all_markets:
        try:
            trades = chain_reader.fetch_trades_for_market(
                token_id_a=market.token_id_a,
                token_id_b=market.token_id_b,
                from_block=from_block,
                to_block=to_block,
                condition_id=market.condition_id,
            )
            all_trades.extend(trades)
            wallets_seen.update(t.wallet for t in trades)
        except Exception as e:
            msg = f"Error fetching trades for {market.slug}: {e}"
            logger.warning(msg)
            result.errors.append(msg)
        time.sleep(0.2)  # Rate limiting

    result.trades_fetched = len(all_trades)
    result.wallets_seen = len(wallets_seen)

    # Save raw trades
    trades_path = output_path / "trades.json"
    with open(trades_path, "w") as f:
        json.dump([asdict(t) for t in all_trades], f, indent=2)

    # -- Step 3: Save price histories for backtesting --
    prices_dir = output_path / "prices"
    prices_dir.mkdir(exist_ok=True)

    for market in all_markets:
        if market.token_id_a:
            history = api.fetch_prices_history(market.token_id_a)
            if history:
                price_path = prices_dir / f"{market.slug}_yes.json"
                with open(price_path, "w") as f:
                    json.dump(history, f)
            time.sleep(0.3)

    logger.info(
        "Collection complete: %d markets, %d trades, %d wallets",
        result.markets_fetched,
        result.trades_fetched,
        result.wallets_seen,
    )

    # Save collection result summary
    summary_path = output_path / "collection_summary.json"
    with open(summary_path, "w") as f:
        json.dump(asdict(result), f, indent=2)

    return result


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Collect raw trade data from Polymarket + Polygon"
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/polymarket",
        help="Directory to write output files (default: data/raw/polymarket)",
    )
    parser.add_argument(
        "--from-date",
        default="2024-01-01",
        help="Start date in YYYY-MM-DD format (default: 2024-01-01)",
    )
    parser.add_argument(
        "--to-date",
        default="2024-12-31",
        help="End date in YYYY-MM-DD format (default: 2024-12-31)",
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

    result = collect_polymarket_data(
        output_dir=args.output_dir,
        from_date=args.from_date,
        to_date=args.to_date,
    )

    print(f"\nCollection summary:")
    print(f"  Markets fetched:  {result.markets_fetched}")
    print(f"  Trades fetched:   {result.trades_fetched}")
    print(f"  Unique wallets:   {result.wallets_seen}")
    print(f"  Errors:           {len(result.errors)}")
    print(f"  Output directory: {result.output_dir}")


if __name__ == "__main__":
    main()
