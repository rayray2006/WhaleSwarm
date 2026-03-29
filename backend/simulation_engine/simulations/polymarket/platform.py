"""Polymarket prediction-market platform.

Extends :class:`BasePlatform` with handlers for creating markets, buying
and selling outcome shares via a constant-product AMM, browsing markets,
viewing portfolios, and commenting.

Each handler writes to the SQLite database via ``self.db`` and returns a
result dict to the calling agent through the channel.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from simulation_engine.simulations.base import BasePlatform
from simulation_engine.simulations.polymarket.amm import (
    TradeResult,
    anchor_to_real_price,
    get_price,
    quote_buy,
    quote_sell,
)
from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.platform_utils import now_iso

logger = logging.getLogger(__name__)

# Schema directory for Polymarket-specific tables.
_POLYMARKET_SCHEMA_DIR = Path(__file__).resolve().parent / "schema"

# Default starting balance for new portfolios.
DEFAULT_INITIAL_BALANCE = 1000.0


# ------------------------------------------------------------------
# Divergence Tracker
# ------------------------------------------------------------------

@dataclass
class DivergenceTracker:
    """Track the gap between the internal AMM price and a known real-world
    price for each market.

    The simulation runner can feed in real prices each round and then
    query the divergence history for analysis.
    """

    # market_id -> list of (round, internal_price_yes, real_price_yes, gap)
    history: Dict[int, List[Dict[str, float]]] = field(default_factory=dict)

    def record(
        self,
        market_id: int,
        round_num: int,
        internal_price_yes: float,
        real_price_yes: float,
    ) -> float:
        """Record a divergence observation and return the absolute gap."""
        gap = abs(internal_price_yes - real_price_yes)
        entry = {
            "round": round_num,
            "internal": internal_price_yes,
            "real": real_price_yes,
            "gap": gap,
        }
        self.history.setdefault(market_id, []).append(entry)
        return gap

    def get_history(self, market_id: int) -> List[Dict[str, float]]:
        return self.history.get(market_id, [])

    def latest_gap(self, market_id: int) -> Optional[float]:
        hist = self.history.get(market_id)
        if not hist:
            return None
        return hist[-1]["gap"]


# ------------------------------------------------------------------
# PolymarketPlatform
# ------------------------------------------------------------------

class PolymarketPlatform(BasePlatform):
    """Prediction-market platform backed by a constant-product AMM.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    channel:
        The async channel connecting agents to this platform.
    initial_balance:
        Default starting cash for new portfolios.
    """

    # Core schemas loaded by BasePlatform (user, trace).
    # We load polymarket-specific schemas ourselves since they live in
    # a separate directory from the core schema/ folder.
    required_schemas: List[str] = []

    def __init__(
        self,
        db_path: str,
        channel: Channel,
        *,
        initial_balance: float = DEFAULT_INITIAL_BALANCE,
        **kwargs: Any,
    ) -> None:
        super().__init__(db_path, channel, **kwargs)
        self.initial_balance = initial_balance
        self.divergence_tracker = DivergenceTracker()
        self._load_polymarket_schemas()

    def _load_polymarket_schemas(self) -> None:
        """Load Polymarket-specific table schemas from the local schema/ dir."""
        for name in ("market", "portfolio", "position", "trade", "comment"):
            sql_path = _POLYMARKET_SCHEMA_DIR / f"{name}.sql"
            if sql_path.exists():
                sql = sql_path.read_text(encoding="utf-8")
                self.db.conn.executescript(sql)
                logger.debug("Loaded polymarket schema '%s' from %s", name, sql_path)
            else:
                logger.warning("Polymarket schema file not found: %s", sql_path)

    # ------------------------------------------------------------------
    # sign_up
    # ------------------------------------------------------------------

    def sign_up(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Register an agent and create their portfolio.

        Expected *message*: dict with ``user_name``, ``name``, ``bio``.
        If *message* is a tuple/list with a 4th element, use it as
        initial_balance (Extension B: variable balances).
        """
        # Support tuple-style messages for variable initial balance.
        balance = self.initial_balance
        if isinstance(message, (list, tuple)):
            if len(message) >= 4:
                try:
                    balance = float(message[3])
                except (TypeError, ValueError):
                    pass
            # Convert to dict for uniform handling.
            msg_dict: Dict[str, Any] = {}
            if len(message) >= 1:
                msg_dict["user_name"] = message[0]
            if len(message) >= 2:
                msg_dict["name"] = message[1]
            if len(message) >= 3:
                msg_dict["bio"] = message[2]
            message = msg_dict
        elif not isinstance(message, dict):
            message = {}

        user_name = message.get("user_name", f"trader_{agent_id}")
        name = message.get("name", user_name)
        bio = message.get("bio", "")
        created_at = now_iso()

        user_id = agent_id

        # Insert into the core user table.
        self.db.execute(
            "INSERT OR IGNORE INTO user "
            "(user_id, agent_id, user_name, name, bio, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, agent_id, user_name, name, bio, created_at),
        )

        # Create portfolio with initial balance.
        self.db.execute(
            "INSERT OR IGNORE INTO portfolio (user_id, balance, updated_at) "
            "VALUES (?, ?, ?)",
            (user_id, balance, created_at),
        )

        self.log_trace(
            user_id,
            "sign_up",
            json.dumps({"user_name": user_name, "balance": balance}),
            created_at,
        )

        return {
            "success": True,
            "user_id": user_id,
            "user_name": user_name,
            "balance": balance,
        }

    # ------------------------------------------------------------------
    # create_market
    # ------------------------------------------------------------------

    def create_market(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Create a new binary prediction market.

        Expected *message*: tuple/list of
        ``(question, outcome_a, outcome_b, initial_probability)``.
        """
        if isinstance(message, (list, tuple)):
            if len(message) < 4:
                return {"success": False, "error": "need (question, outcome_a, outcome_b, initial_probability)"}
            question, outcome_a, outcome_b, initial_prob = (
                message[0],
                message[1],
                message[2],
                float(message[3]),
            )
        elif isinstance(message, dict):
            question = message.get("question", "")
            outcome_a = message.get("outcome_a", "YES")
            outcome_b = message.get("outcome_b", "NO")
            initial_prob = float(message.get("initial_probability", 0.5))
        else:
            return {"success": False, "error": "invalid message format"}

        if not question:
            return {"success": False, "error": "question is required"}
        if initial_prob <= 0.0 or initial_prob >= 1.0:
            return {"success": False, "error": "initial_probability must be in (0, 1)"}

        # Set up AMM reserves so that:
        #   price_a = reserve_b / (reserve_a + reserve_b) = initial_prob
        # Liquidity should be large enough relative to agent capital so
        # that individual trades move the price meaningfully but don't
        # get rejected by the trade-size cap.  With N agents each
        # holding ~$1000 and a 10% cap, reserves of ~5000 work well.
        k = 25_000_000.0  # reserves ~5000 each at 50/50
        # new_reserve_b = sqrt(k * p / (1 - p))
        reserve_b = math.sqrt(k * initial_prob / (1.0 - initial_prob))
        reserve_a = k / reserve_b

        created_at = now_iso()
        cursor = self.db.execute(
            "INSERT INTO market "
            "(creator_id, question, outcome_a, outcome_b, reserve_a, reserve_b, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (agent_id, question, outcome_a, outcome_b, reserve_a, reserve_b, created_at),
        )
        market_id = cursor.lastrowid

        price_a, price_b = get_price(reserve_a, reserve_b)

        self.log_trace(
            agent_id,
            "create_market",
            json.dumps({
                "market_id": market_id,
                "question": question,
                "price_a": round(price_a, 4),
                "price_b": round(price_b, 4),
            }),
            created_at,
        )

        return {
            "success": True,
            "market_id": market_id,
            "question": question,
            "outcome_a": outcome_a,
            "outcome_b": outcome_b,
            "price_a": price_a,
            "price_b": price_b,
            "reserve_a": reserve_a,
            "reserve_b": reserve_b,
        }

    # ------------------------------------------------------------------
    # buy_shares
    # ------------------------------------------------------------------

    def buy_shares(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Buy outcome shares on a market.

        Expected *message*: tuple/list of ``(market_id, outcome, amount_usd)``
        or dict with those keys.
        """
        if isinstance(message, (list, tuple)):
            if len(message) < 3:
                return {"success": False, "error": "need (market_id, outcome, amount_usd)"}
            market_id = int(message[0])
            outcome = str(message[1])
            amount_usd = float(message[2])
        elif isinstance(message, dict):
            market_id = int(message["market_id"])
            outcome = str(message["outcome"])
            amount_usd = float(message["amount_usd"])
        else:
            return {"success": False, "error": "invalid message format"}

        if amount_usd <= 0:
            return {"success": False, "error": "amount_usd must be positive"}

        # Fetch market.
        market = self.db.fetchone(
            "SELECT * FROM market WHERE market_id = ? AND resolved = 0",
            (market_id,),
        )
        if market is None:
            return {"success": False, "error": f"market {market_id} not found or resolved"}

        # Fetch portfolio.
        portfolio = self.db.fetchone(
            "SELECT * FROM portfolio WHERE user_id = ?", (agent_id,)
        )
        if portfolio is None:
            return {"success": False, "error": "no portfolio found; sign up first"}

        balance = portfolio["balance"]
        if amount_usd > balance:
            return {"success": False, "error": f"insufficient balance: ${balance:.2f} < ${amount_usd:.2f}"}

        reserve_a = market["reserve_a"]
        reserve_b = market["reserve_b"]

        # Normalize outcome to match market labels.
        outcome_upper = outcome.upper()
        if outcome_upper in (market["outcome_a"].upper(), "YES", "A"):
            amm_outcome = "YES"
        elif outcome_upper in (market["outcome_b"].upper(), "NO", "B"):
            amm_outcome = "NO"
        else:
            return {"success": False, "error": f"unknown outcome '{outcome}'"}

        # Quote via AMM (enforces 2% cap internally).
        try:
            result = quote_buy(reserve_a, reserve_b, amm_outcome, amount_usd)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        created_at = now_iso()

        # Update market reserves.
        self.db.execute(
            "UPDATE market SET reserve_a = ?, reserve_b = ? WHERE market_id = ?",
            (result.new_reserve_a, result.new_reserve_b, market_id),
        )

        # Deduct from balance.
        new_balance = balance - amount_usd
        self.db.execute(
            "UPDATE portfolio SET balance = ?, updated_at = ? WHERE user_id = ?",
            (new_balance, created_at, agent_id),
        )

        # Update or create position.
        outcome_label = market["outcome_a"] if amm_outcome == "YES" else market["outcome_b"]
        position = self.db.fetchone(
            "SELECT * FROM position WHERE user_id = ? AND market_id = ? AND outcome = ?",
            (agent_id, market_id, outcome_label),
        )
        if position is None:
            self.db.execute(
                "INSERT INTO position (user_id, market_id, outcome, shares) "
                "VALUES (?, ?, ?, ?)",
                (agent_id, market_id, outcome_label, result.shares_out),
            )
        else:
            self.db.execute(
                "UPDATE position SET shares = shares + ? "
                "WHERE user_id = ? AND market_id = ? AND outcome = ?",
                (result.shares_out, agent_id, market_id, outcome_label),
            )

        # Record trade.
        self.db.execute(
            "INSERT INTO trade "
            "(user_id, market_id, side, outcome, shares, price, cost, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id,
                market_id,
                "buy",
                outcome_label,
                result.shares_out,
                result.effective_price,
                amount_usd,
                created_at,
            ),
        )

        new_price_a, new_price_b = get_price(result.new_reserve_a, result.new_reserve_b)

        self.log_trace(
            agent_id,
            "buy_shares",
            json.dumps({
                "market_id": market_id,
                "outcome": outcome_label,
                "shares": round(result.shares_out, 6),
                "cost": round(amount_usd, 4),
                "eff_price": round(result.effective_price, 4),
                "new_price_a": round(new_price_a, 4),
                "new_price_b": round(new_price_b, 4),
            }),
            created_at,
        )

        return {
            "success": True,
            "market_id": market_id,
            "outcome": outcome_label,
            "shares_bought": result.shares_out,
            "effective_price": result.effective_price,
            "cost_usd": amount_usd,
            "new_balance": new_balance,
            "new_price_a": new_price_a,
            "new_price_b": new_price_b,
        }

    # ------------------------------------------------------------------
    # sell_shares
    # ------------------------------------------------------------------

    def sell_shares(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Sell outcome shares on a market.

        Expected *message*: tuple/list of ``(market_id, outcome, shares)``
        or dict with those keys.
        """
        if isinstance(message, (list, tuple)):
            if len(message) < 3:
                return {"success": False, "error": "need (market_id, outcome, shares)"}
            market_id = int(message[0])
            outcome = str(message[1])
            shares = float(message[2])
        elif isinstance(message, dict):
            market_id = int(message["market_id"])
            outcome = str(message["outcome"])
            shares = float(message["shares"])
        else:
            return {"success": False, "error": "invalid message format"}

        if shares <= 0:
            return {"success": False, "error": "shares must be positive"}

        # Fetch market.
        market = self.db.fetchone(
            "SELECT * FROM market WHERE market_id = ? AND resolved = 0",
            (market_id,),
        )
        if market is None:
            return {"success": False, "error": f"market {market_id} not found or resolved"}

        # Determine outcome label.
        outcome_upper = outcome.upper()
        if outcome_upper in (market["outcome_a"].upper(), "YES", "A"):
            amm_outcome = "YES"
            outcome_label = market["outcome_a"]
        elif outcome_upper in (market["outcome_b"].upper(), "NO", "B"):
            amm_outcome = "NO"
            outcome_label = market["outcome_b"]
        else:
            return {"success": False, "error": f"unknown outcome '{outcome}'"}

        # Check position.
        position = self.db.fetchone(
            "SELECT * FROM position WHERE user_id = ? AND market_id = ? AND outcome = ?",
            (agent_id, market_id, outcome_label),
        )
        if position is None or position["shares"] < shares:
            held = position["shares"] if position else 0.0
            return {
                "success": False,
                "error": f"insufficient shares: hold {held:.4f}, trying to sell {shares:.4f}",
            }

        reserve_a = market["reserve_a"]
        reserve_b = market["reserve_b"]

        # Quote via AMM.
        try:
            result = quote_sell(reserve_a, reserve_b, amm_outcome, shares)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        created_at = now_iso()
        usd_out = result.cost_usd  # For sells, cost_usd = USD returned.

        # Update market reserves.
        self.db.execute(
            "UPDATE market SET reserve_a = ?, reserve_b = ? WHERE market_id = ?",
            (result.new_reserve_a, result.new_reserve_b, market_id),
        )

        # Credit balance.
        self.db.execute(
            "UPDATE portfolio SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
            (usd_out, created_at, agent_id),
        )

        # Update position.
        new_shares = position["shares"] - shares
        if new_shares <= 1e-9:
            self.db.execute(
                "DELETE FROM position WHERE user_id = ? AND market_id = ? AND outcome = ?",
                (agent_id, market_id, outcome_label),
            )
        else:
            self.db.execute(
                "UPDATE position SET shares = ? "
                "WHERE user_id = ? AND market_id = ? AND outcome = ?",
                (new_shares, agent_id, market_id, outcome_label),
            )

        # Record trade.
        self.db.execute(
            "INSERT INTO trade "
            "(user_id, market_id, side, outcome, shares, price, cost, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                agent_id,
                market_id,
                "sell",
                outcome_label,
                shares,
                result.effective_price,
                usd_out,
                created_at,
            ),
        )

        portfolio = self.db.fetchone(
            "SELECT balance FROM portfolio WHERE user_id = ?", (agent_id,)
        )
        new_balance = portfolio["balance"] if portfolio else 0.0

        new_price_a, new_price_b = get_price(result.new_reserve_a, result.new_reserve_b)

        self.log_trace(
            agent_id,
            "sell_shares",
            json.dumps({
                "market_id": market_id,
                "outcome": outcome_label,
                "shares": round(shares, 6),
                "usd_out": round(usd_out, 4),
                "eff_price": round(result.effective_price, 4),
                "new_price_a": round(new_price_a, 4),
                "new_price_b": round(new_price_b, 4),
            }),
            created_at,
        )

        return {
            "success": True,
            "market_id": market_id,
            "outcome": outcome_label,
            "shares_sold": shares,
            "usd_received": usd_out,
            "effective_price": result.effective_price,
            "new_balance": new_balance,
            "new_price_a": new_price_a,
            "new_price_b": new_price_b,
        }

    # ------------------------------------------------------------------
    # browse_markets
    # ------------------------------------------------------------------

    def browse_markets(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Return all active (unresolved) markets with current prices."""
        markets = self.db.fetchall(
            "SELECT * FROM market WHERE resolved = 0 ORDER BY market_id"
        )

        results = []
        for m in markets:
            price_a, price_b = get_price(m["reserve_a"], m["reserve_b"])
            trade_count = self.db.fetchone(
                "SELECT COUNT(*) AS cnt FROM trade WHERE market_id = ?",
                (m["market_id"],),
            )
            results.append({
                "market_id": m["market_id"],
                "question": m["question"],
                "outcome_a": m["outcome_a"],
                "outcome_b": m["outcome_b"],
                "price_a": round(price_a, 4),
                "price_b": round(price_b, 4),
                "trade_count": trade_count["cnt"] if trade_count else 0,
                "created_at": m["created_at"],
            })

        self.log_trace(
            agent_id,
            "browse_markets",
            json.dumps({"count": len(results)}),
            now_iso(),
        )

        return {"success": True, "markets": results}

    # ------------------------------------------------------------------
    # view_portfolio
    # ------------------------------------------------------------------

    def view_portfolio(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Return the agent's cash balance, positions with P&L, and total value."""
        portfolio = self.db.fetchone(
            "SELECT * FROM portfolio WHERE user_id = ?", (agent_id,)
        )
        if portfolio is None:
            return {"success": False, "error": "no portfolio found; sign up first"}

        balance = portfolio["balance"]

        # Fetch positions with current market prices.
        positions = self.db.fetchall(
            "SELECT p.*, m.question, m.outcome_a, m.outcome_b, m.reserve_a, m.reserve_b "
            "FROM position p "
            "JOIN market m ON p.market_id = m.market_id "
            "WHERE p.user_id = ?",
            (agent_id,),
        )

        position_details = []
        total_position_value = 0.0

        for pos in positions:
            price_a, price_b = get_price(pos["reserve_a"], pos["reserve_b"])
            if pos["outcome"] == pos["outcome_a"]:
                current_price = price_a
            else:
                current_price = price_b

            market_value = pos["shares"] * current_price

            # Compute cost basis from trades.
            cost_row = self.db.fetchone(
                "SELECT SUM(CASE WHEN side='buy' THEN cost ELSE 0 END) - "
                "SUM(CASE WHEN side='sell' THEN cost ELSE 0 END) AS net_cost "
                "FROM trade WHERE user_id = ? AND market_id = ? AND outcome = ?",
                (agent_id, pos["market_id"], pos["outcome"]),
            )
            net_cost = cost_row["net_cost"] if cost_row and cost_row["net_cost"] else 0.0
            pnl = market_value - net_cost

            position_details.append({
                "market_id": pos["market_id"],
                "question": pos["question"],
                "outcome": pos["outcome"],
                "shares": pos["shares"],
                "current_price": round(current_price, 4),
                "market_value": round(market_value, 4),
                "cost_basis": round(net_cost, 4),
                "pnl": round(pnl, 4),
            })

            total_position_value += market_value

        total_value = balance + total_position_value

        self.log_trace(
            agent_id,
            "view_portfolio",
            json.dumps({
                "balance": round(balance, 2),
                "positions": len(position_details),
                "total_value": round(total_value, 2),
            }),
            now_iso(),
        )

        return {
            "success": True,
            "balance": balance,
            "positions": position_details,
            "total_position_value": round(total_position_value, 4),
            "total_value": round(total_value, 4),
        }

    # ------------------------------------------------------------------
    # comment_on_market
    # ------------------------------------------------------------------

    def comment_on_market(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Post a comment on a market.

        Expected *message*: tuple/list of ``(market_id, content)`` or dict.
        """
        if isinstance(message, (list, tuple)):
            if len(message) < 2:
                return {"success": False, "error": "need (market_id, content)"}
            market_id = int(message[0])
            content = str(message[1])
        elif isinstance(message, dict):
            market_id = int(message["market_id"])
            content = str(message.get("content", ""))
        else:
            return {"success": False, "error": "invalid message format"}

        if not content.strip():
            return {"success": False, "error": "empty content"}

        # Verify market exists.
        market = self.db.fetchone(
            "SELECT market_id FROM market WHERE market_id = ?", (market_id,)
        )
        if market is None:
            return {"success": False, "error": f"market {market_id} not found"}

        created_at = now_iso()
        cursor = self.db.execute(
            "INSERT INTO poly_comment (market_id, creator_id, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (market_id, agent_id, content.strip(), created_at),
        )
        comment_id = cursor.lastrowid

        self.log_trace(
            agent_id,
            "comment_on_market",
            json.dumps({"comment_id": comment_id, "market_id": market_id}),
            created_at,
        )

        return {
            "success": True,
            "comment_id": comment_id,
            "market_id": market_id,
        }

    # ------------------------------------------------------------------
    # do_nothing
    # ------------------------------------------------------------------

    def do_nothing(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """No-op action. The agent chose to do nothing this turn."""
        self.log_trace(agent_id, "do_nothing", "{}", now_iso())
        return {"success": True}
