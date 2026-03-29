"""Polymarket CLOB API client for real-price anchoring.

Fetches live market prices from Polymarket's public API.
No API key required — the CLOB endpoints are public.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

DEFAULT_CLOB_URL = "https://clob.polymarket.com"


class PolymarketClient:
    """Client for Polymarket's CLOB (Central Limit Order Book) API."""

    def __init__(self, base_url: str = DEFAULT_CLOB_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "WhaleSwarm/1.0",
        })

    def get_market(self, condition_id: str) -> Optional[Dict]:
        """Get market data by condition ID.

        Returns market metadata including current prices.
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/markets/{condition_id}",
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Failed to fetch market {condition_id}: {e}")
            return None

    def get_price(self, token_id: str) -> Optional[float]:
        """Get the current midpoint price for a token.

        Args:
            token_id: The CLOB token ID for a specific outcome.

        Returns:
            Price as a float (0-1), or None on failure.
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/midpoint",
                params={"token_id": token_id},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("mid", data.get("price", 0.5)))
        except Exception as e:
            logger.warning(f"Failed to fetch price for token {token_id}: {e}")
            return None

    def get_prices(self, token_ids: List[str]) -> Dict[str, float]:
        """Get midpoint prices for multiple tokens."""
        prices = {}
        for tid in token_ids:
            price = self.get_price(tid)
            if price is not None:
                prices[tid] = price
        return prices

    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """Get the order book for a token.

        Returns bids and asks with price/size.
        """
        try:
            resp = self.session.get(
                f"{self.base_url}/book",
                params={"token_id": token_id},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Failed to fetch orderbook for {token_id}: {e}")
            return None

    def search_markets(self, query: str, limit: int = 10) -> List[Dict]:
        """Search for markets by keyword.

        The Gamma API's query/title params don't actually filter, so we
        fetch a large batch of active events sorted by volume and filter
        client-side.  Each event may contain multiple sub-markets; we
        flatten them and return the best matches.
        """
        try:
            resp = self.session.get(
                "https://gamma-api.polymarket.com/events",
                params={
                    "limit": 200,
                    "active": True,
                    "closed": False,
                    "order": "volume24hr",
                    "ascending": False,
                },
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json()
        except Exception as e:
            logger.warning(f"Failed to fetch Polymarket events: {e}")
            return []

        # Client-side keyword search across event titles and market questions.
        query_lower = query.lower().strip()
        keywords = query_lower.split()

        scored: List[tuple] = []
        for event in events:
            title = (event.get("title") or "").lower()
            # Check sub-markets within the event.
            markets = event.get("markets") or []
            for market in markets:
                question = (market.get("question") or market.get("title") or "").lower()
                text = f"{title} {question}"
                # Score: count how many keywords match.
                hits = sum(1 for kw in keywords if kw in text)
                if hits > 0:
                    # Attach event-level metadata to market for display.
                    market["_event_title"] = event.get("title", "")
                    scored.append((hits, market))

        # Sort by keyword hits descending, then take top N.
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    def get_market_prices_for_question(self, question: str) -> Optional[Tuple[float, float]]:
        """Search for a market matching a question and return (yes_price, no_price).

        This is the main entry point for the simulation engine to get real prices.
        """
        markets = self.search_markets(question, limit=3)
        if not markets:
            logger.info(f"No Polymarket market found for: {question[:60]}...")
            return None

        market = markets[0]

        # Extract token IDs from outcomes
        tokens = market.get("clobTokenIds")
        if not tokens or len(tokens) < 2:
            # Try alternative field names
            tokens = market.get("clob_token_ids")

        if not tokens or len(tokens) < 2:
            logger.warning(f"Market found but no token IDs: {market.get('question', '?')}")
            return None

        yes_token = tokens[0]
        no_token = tokens[1]

        yes_price = self.get_price(yes_token)
        no_price = self.get_price(no_token)

        if yes_price is None:
            return None

        # If we only got YES, derive NO
        if no_price is None:
            no_price = 1.0 - yes_price

        logger.info(
            f"Polymarket price for '{market.get('question', '?')[:50]}': "
            f"YES=${yes_price:.3f}, NO=${no_price:.3f}"
        )
        return (yes_price, no_price)

    def ping(self) -> bool:
        """Check if the CLOB API is reachable."""
        try:
            resp = self.session.get(f"{self.base_url}/", timeout=5)
            return resp.status_code < 500
        except Exception:
            return False
