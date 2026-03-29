"""Virtual whale trader that pegs the simulated AMM to real Polymarket prices.

The whale executes real trades through the AMM (mint-and-swap) to move the
internal price toward the real-world price.  It is exempt from the per-trade
size cap since it represents external market forces.

Whale trades are recorded in the ``trade`` table with ``user_id = -1`` so
they show up in the action log but are excluded from agent volume tracking.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from simulation_engine.simulations.polymarket.amm import (
    compute_whale_trade,
    get_price,
    quote_buy,
)

logger = logging.getLogger(__name__)

WHALE_USER_ID = -1


@dataclass
class WhaleTrader:
    """Virtual house account that trades the AMM toward a target price."""

    balance_usd: float = 0.0
    shares_yes: float = 0.0
    shares_no: float = 0.0

    def execute_peg(
        self,
        db,
        market_id: int,
        target_price_yes: float,
    ) -> dict:
        """Execute a whale trade to move the AMM price to *target_price_yes*.

        Returns a summary dict with trade details, or an empty dict if no
        trade was needed.
        """
        market = db.fetchone(
            "SELECT * FROM market WHERE market_id = ? AND resolved = 0",
            (market_id,),
        )
        if market is None:
            return {}

        reserve_a = market["reserve_a"]
        reserve_b = market["reserve_b"]
        current_price, _ = get_price(reserve_a, reserve_b)

        side, amount_usd = compute_whale_trade(
            reserve_a, reserve_b, target_price_yes,
        )

        if amount_usd < 0.01:
            return {}

        # Execute the trade through the AMM without the cap.
        if side == "buy_yes":
            result = quote_buy(
                reserve_a, reserve_b, "YES", amount_usd, enforce_cap=False,
            )
            self.shares_yes += result.shares_out
        else:
            result = quote_buy(
                reserve_a, reserve_b, "NO", amount_usd, enforce_cap=False,
            )
            self.shares_no += result.shares_out

        self.balance_usd -= amount_usd

        # Update market reserves.
        db.execute(
            "UPDATE market SET reserve_a = ?, reserve_b = ? WHERE market_id = ?",
            (result.new_reserve_a, result.new_reserve_b, market_id),
        )

        # Record the trade so it appears in logs.
        outcome_label = market["outcome_a"] if side == "buy_yes" else market["outcome_b"]
        from simulation_engine.social_platform.platform_utils import now_iso

        created_at = now_iso()
        db.execute(
            "INSERT INTO trade "
            "(user_id, market_id, side, outcome, shares, price, cost, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                WHALE_USER_ID,
                market_id,
                "buy",
                outcome_label,
                result.shares_out,
                result.effective_price,
                amount_usd,
                created_at,
            ),
        )

        new_price, _ = get_price(result.new_reserve_a, result.new_reserve_b)

        summary = {
            "side": side,
            "amount_usd": round(amount_usd, 2),
            "shares_out": round(result.shares_out, 4),
            "price_before": round(current_price, 4),
            "price_after": round(new_price, 4),
            "target_price": round(target_price_yes, 4),
        }
        logger.info(
            "Whale trade on market %d: %s $%.2f → price %.4f→%.4f (target %.4f)",
            market_id, side, amount_usd, current_price, new_price, target_price_yes,
        )
        return summary
