"""Agent-side action interface for the Polymarket platform.

Defines the public async methods that agents can call.  Each method sends
a message through the :class:`Channel` to the platform server, which
processes it and returns a result.

The tool definitions are auto-generated from these method signatures and
docstrings by :meth:`BaseAction.get_openai_function_list`.
"""

from __future__ import annotations

from typing import Any, Dict

from simulation_engine.simulations.base import BaseAction
from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.typing import ActionType


class PolymarketAction(BaseAction):
    """Agent-side Polymarket action interface.

    Parameters
    ----------
    agent_id:
        The unique ID of the agent using this action interface.
    channel:
        The shared async channel to the Polymarket platform.
    """

    def __init__(self, agent_id: int, channel: Channel) -> None:
        super().__init__(agent_id, channel)

    async def buy_shares(
        self, market_id: int, outcome: str, amount_usd: float
    ) -> Dict[str, Any]:
        """Buy shares in a prediction market outcome.

        market_id: The ID of the market to trade in.
        outcome: The outcome to buy (e.g. 'YES' or 'NO').
        amount_usd: Dollar amount to spend on shares.
        """
        return await self.perform_action(
            (market_id, outcome, amount_usd),
            ActionType.BUY_SHARES,
        )

    async def sell_shares(
        self, market_id: int, outcome: str, shares: float
    ) -> Dict[str, Any]:
        """Sell shares you hold in a prediction market outcome.

        market_id: The ID of the market to sell in.
        outcome: The outcome to sell (e.g. 'YES' or 'NO').
        shares: Number of shares to sell.
        """
        return await self.perform_action(
            (market_id, outcome, shares),
            ActionType.SELL_SHARES,
        )

    async def browse_markets(self) -> Dict[str, Any]:
        """Browse all active prediction markets with current prices."""
        return await self.perform_action(
            {},
            ActionType.BROWSE_MARKETS,
        )

    async def view_portfolio(self) -> Dict[str, Any]:
        """View your current cash balance, positions, and P&L."""
        return await self.perform_action(
            {},
            ActionType.VIEW_PORTFOLIO,
        )

    async def comment_on_market(
        self, market_id: int, content: str
    ) -> Dict[str, Any]:
        """Post a comment on a prediction market.

        market_id: The ID of the market to comment on.
        content: Your comment text.
        """
        return await self.perform_action(
            (market_id, content),
            ActionType.COMMENT_ON_MARKET,
        )

    async def do_nothing(self) -> Dict[str, Any]:
        """Skip this turn and take no action."""
        return await self.perform_action(
            {},
            ActionType.DO_NOTHING,
        )
