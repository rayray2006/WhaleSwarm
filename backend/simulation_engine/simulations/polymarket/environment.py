"""Polymarket observation environment.

Converts the current platform state visible to an agent into a text prompt
that the LLM can reason about.  Includes portfolio, active markets, and
any cross-platform social-media context injected by the bridge.
"""

from __future__ import annotations

from typing import Any

from simulation_engine.simulations.base import BaseEnvironment
from simulation_engine.simulations.polymarket.amm import get_price
from simulation_engine.social_platform.database import Database


class PolymarketEnvironment(BaseEnvironment):
    """Renders the prediction-market world state as a text observation.

    Parameters
    ----------
    db:
        The shared SQLite :class:`Database` instance used by the platform.
    """

    def __init__(self, db: Database) -> None:
        super().__init__()
        self.db = db

    async def to_text_prompt(self, agent_id: int) -> str:
        """Build the observation prompt for *agent_id*.

        Sections:
        1. YOUR PORTFOLIO -- cash, positions with P&L, total value
        2. ACTIVE MARKETS -- question, YES/NO prices, trade count
        3. SOCIAL MEDIA CONTEXT -- cross-platform observations (if any)
        4. "What do you want to do?" call-to-action
        """
        sections: list[str] = []

        # ---- 1. Portfolio ------------------------------------------------
        portfolio = self.db.fetchone(
            "SELECT * FROM portfolio WHERE user_id = ?", (agent_id,)
        )
        if portfolio is not None:
            balance = portfolio["balance"]

            positions = self.db.fetchall(
                "SELECT p.*, m.question, m.outcome_a, m.outcome_b, "
                "m.reserve_a, m.reserve_b "
                "FROM position p "
                "JOIN market m ON p.market_id = m.market_id "
                "WHERE p.user_id = ?",
                (agent_id,),
            )

            pos_lines: list[str] = []
            total_position_value = 0.0

            for pos in positions:
                price_a, price_b = get_price(pos["reserve_a"], pos["reserve_b"])
                if pos["outcome"] == pos["outcome_a"]:
                    current_price = price_a
                else:
                    current_price = price_b

                market_value = pos["shares"] * current_price

                # Cost basis from trades.
                cost_row = self.db.fetchone(
                    "SELECT SUM(CASE WHEN side='buy' THEN cost ELSE 0 END) - "
                    "SUM(CASE WHEN side='sell' THEN cost ELSE 0 END) AS net_cost "
                    "FROM trade WHERE user_id = ? AND market_id = ? AND outcome = ?",
                    (agent_id, pos["market_id"], pos["outcome"]),
                )
                net_cost = cost_row["net_cost"] if cost_row and cost_row["net_cost"] else 0.0
                pnl = market_value - net_cost
                pnl_sign = "+" if pnl >= 0 else ""

                pos_lines.append(
                    f"  - Market #{pos['market_id']}: {pos['question']}\n"
                    f"    {pos['outcome']}: {pos['shares']:.2f} shares @ ${current_price:.4f} "
                    f"= ${market_value:.2f} (P&L: {pnl_sign}${pnl:.2f})"
                )
                total_position_value += market_value

            total_value = balance + total_position_value

            portfolio_text = f"===== YOUR PORTFOLIO =====\n"
            portfolio_text += f"Cash: ${balance:.2f}\n"
            if pos_lines:
                portfolio_text += "Positions:\n" + "\n".join(pos_lines) + "\n"
            else:
                portfolio_text += "Positions: (none)\n"
            portfolio_text += f"Total Value: ${total_value:.2f}"
            sections.append(portfolio_text)
        else:
            sections.append("===== YOUR PORTFOLIO =====\n(not registered yet)")

        # ---- 2. Active Markets -------------------------------------------
        markets = self.db.fetchall(
            "SELECT * FROM market WHERE resolved = 0 ORDER BY market_id"
        )

        if markets:
            market_lines: list[str] = []
            for m in markets:
                price_a, price_b = get_price(m["reserve_a"], m["reserve_b"])
                trade_count_row = self.db.fetchone(
                    "SELECT COUNT(*) AS cnt FROM trade WHERE market_id = ?",
                    (m["market_id"],),
                )
                trade_count = trade_count_row["cnt"] if trade_count_row else 0

                # Fetch recent comments.
                comments = self.db.fetchall(
                    "SELECT c.content, u.user_name "
                    "FROM poly_comment c "
                    "LEFT JOIN user u ON c.creator_id = u.user_id "
                    "WHERE c.market_id = ? "
                    "ORDER BY c.comment_id DESC LIMIT 3",
                    (m["market_id"],),
                )

                line = (
                    f"  Market #{m['market_id']}: {m['question']}\n"
                    f"    {m['outcome_a']}: ${price_a:.4f}  |  "
                    f"{m['outcome_b']}: ${price_b:.4f}  |  "
                    f"Trades: {trade_count}"
                )

                if comments:
                    comment_strs = []
                    for c in reversed(list(comments)):
                        who = c["user_name"] if c["user_name"] else "anon"
                        comment_strs.append(f"      @{who}: {c['content']}")
                    line += "\n    Recent comments:\n" + "\n".join(comment_strs)

                market_lines.append(line)

            sections.append(
                "===== ACTIVE MARKETS =====\n" + "\n".join(market_lines)
            )
        else:
            sections.append("===== ACTIVE MARKETS =====\n(no active markets)")

        # ---- 3. Social Media Context -------------------------------------
        if self.extra_observation_context:
            sections.append(
                "===== SOCIAL MEDIA CONTEXT =====\n"
                + self.extra_observation_context
            )

        # ---- 4. Call to action -------------------------------------------
        sections.append(
            "What do you want to do? Choose one action from the available tools."
        )

        return "\n\n".join(sections)
