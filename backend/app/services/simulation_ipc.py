"""IPC helpers for reading simulation state from disk.

The simulation subprocess writes its progress to ``actions.jsonl`` and
SQLite databases.  These helpers parse that output so the Flask API can
report real-time progress without direct memory sharing.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ======================================================================
# Helpers
# ======================================================================

def _summarise_action(action_name: str, args: dict, response: Any) -> str:
    """Build a short human-readable string describing an action."""
    # Social media posts / comments
    if action_name in ("post", "tweet", "comment"):
        text = args.get("content") or args.get("text") or args.get("body") or ""
        return str(text)[:200] if text else action_name
    # Trades
    if action_name in ("buy_shares", "sell_shares"):
        outcome = args.get("outcome", "?")
        market = args.get("market_id", "?")
        conv = args.get("conviction", "")
        return f"{action_name} {outcome} on market {market}" + (f" (conviction {conv})" if conv else "")
    # Social interactions
    if action_name in ("like", "retweet", "repost", "quote_post", "upvote", "downvote"):
        target = args.get("post_id") or args.get("tweet_id") or args.get("target_id") or ""
        return f"{action_name} {target}".strip()
    if action_name in ("follow", "unfollow"):
        target = args.get("user_id") or args.get("target") or ""
        return f"{action_name} {target}".strip()
    if action_name == "search":
        query = args.get("query") or args.get("q") or ""
        return f"search: {query}" if query else "search"
    # Fallback: stringify args keys
    if args:
        parts = [f"{k}={v}" for k, v in list(args.items())[:3]]
        return f"{action_name}({', '.join(parts)})"
    return action_name


# ======================================================================
# actions.jsonl parsing
# ======================================================================

def parse_actions_jsonl(sim_dir: str) -> List[Dict[str, Any]]:
    """Parse all action records from ``actions.jsonl``.

    Args:
        sim_dir: Path to the simulation directory.

    Returns:
        List of action dicts, in chronological order.  Returns an empty
        list if the file does not exist or is empty.
    """
    actions_path = os.path.join(sim_dir, "actions.jsonl")
    if not os.path.exists(actions_path):
        return []

    actions: List[Dict[str, Any]] = []
    try:
        with open(actions_path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    actions.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.debug(
                        "Skipping malformed JSON at line %d in %s",
                        line_num, actions_path,
                    )
    except Exception:
        logger.exception("Failed to read %s", actions_path)

    return actions


# ======================================================================
# Run state extraction
# ======================================================================

def get_run_state_from_actions(
    sim_dir: str,
    max_rounds: int = 10,
) -> Dict[str, Any]:
    """Derive the simulation run state from ``actions.jsonl``.

    Args:
        sim_dir: Path to the simulation directory.
        max_rounds: Total expected rounds (from config).

    Returns:
        Dict with:
        - ``current_round``: The last completed round number (0-indexed).
        - ``total_rounds``: Total expected rounds.
        - ``progress``: Float in [0, 1].
        - ``action_counts``: Dict mapping action names to counts.
        - ``agent_action_count``: Total agent actions taken.
        - ``recent_actions``: Last 20 agent actions.
        - ``status``: Derived status string.
        - ``rounds_completed``: Number of rounds fully completed.
    """
    actions = parse_actions_jsonl(sim_dir)

    if not actions:
        return {
            "current_round": 0,
            "total_rounds": max_rounds,
            "progress": 0.0,
            "action_counts": {},
            "agent_action_count": 0,
            "recent_actions": [],
            "status": "pending",
            "rounds_completed": 0,
        }

    # Track state from actions.
    current_round = 0
    rounds_completed = 0
    action_counts: Dict[str, int] = {}
    agent_actions: List[Dict[str, Any]] = []
    status = "running"
    simulation_started = False

    for action in actions:
        action_type = action.get("type", "")

        if action_type == "simulation_start":
            simulation_started = True
            max_rounds = action.get("max_rounds", max_rounds)

        elif action_type == "round_start":
            current_round = action.get("round", current_round)

        elif action_type == "round_end":
            round_num = action.get("round", 0)
            rounds_completed = max(rounds_completed, round_num + 1)
            # Merge action counts from round.
            round_counts = action.get("action_counts", {})
            for name, count in round_counts.items():
                action_counts[name] = action_counts.get(name, 0) + count

        elif action_type == "agent_action":
            action_name = action.get("action", "unknown")
            if action_name == "do_nothing":
                action_counts["do_nothing"] = action_counts.get("do_nothing", 0) + 1
                continue
            action_counts[action_name] = action_counts.get(action_name, 0) + 1
            # Build a human-readable content string from arguments/response.
            args = action.get("arguments", {})
            response = action.get("response")
            content = _summarise_action(action_name, args, response)
            agent_actions.append({
                "round": action.get("_round", current_round),
                "agent_id": action.get("agent_id"),
                "agent_name": action.get("agent_name", ""),
                "platform": action.get("platform", ""),
                "action": action_name,
                "action_type": action_name,
                "content": content,
                "arguments": args,
                "timestamp": action.get("_ts"),
            })

        elif action_type == "simulation_end":
            final_rounds = action.get("rounds_completed", rounds_completed)
            rounds_completed = max(rounds_completed, final_rounds)
            status = "completed"

        elif action_type == "simulation_error":
            status = "failed"

    # Compute progress.
    if max_rounds > 0:
        progress = min(1.0, rounds_completed / max_rounds)
    else:
        progress = 1.0

    if status == "running" and rounds_completed >= max_rounds:
        status = "completed"

    # Recent actions (last 20).
    recent = agent_actions[-20:] if agent_actions else []

    return {
        "current_round": current_round,
        "total_rounds": max_rounds,
        "progress": round(progress, 3),
        "action_counts": action_counts,
        "agent_action_count": len(agent_actions),
        "recent_actions": recent,
        "status": status,
        "rounds_completed": rounds_completed,
    }


# ======================================================================
# Recent actions
# ======================================================================

def get_recent_actions(
    sim_dir: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Return the most recent agent actions from ``actions.jsonl``.

    Args:
        sim_dir: Path to the simulation directory.
        limit: Maximum number of actions to return.

    Returns:
        List of recent action dicts (most recent last).
    """
    actions = parse_actions_jsonl(sim_dir)

    agent_actions = [
        a for a in actions if a.get("type") == "agent_action"
    ]

    return agent_actions[-limit:]


# ======================================================================
# SQLite post readers
# ======================================================================

def get_posts_from_db(
    sim_dir: str,
    platform: str,
    round_num: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Read posts from a platform's SQLite database.

    Args:
        sim_dir: Path to the simulation directory.
        platform: Platform name (``"twitter"``, ``"reddit"``, ``"polymarket"``).
        round_num: If provided, try to filter posts created during this round.
            (Approximate -- based on post_id ordering.)
        limit: Maximum number of posts to return.

    Returns:
        List of post dicts with ``post_id``, ``user_id``, ``user_name``,
        ``content``, ``created_at``, ``num_likes``, ``num_dislikes``.
    """
    db_path = os.path.join(sim_dir, f"{platform}.db")
    if not os.path.exists(db_path):
        return []

    posts: List[Dict[str, Any]] = []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Check which tables exist.
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "post" in tables:
            query = (
                "SELECT p.post_id, p.user_id, p.content, p.created_at, "
                "p.num_likes, p.num_dislikes"
            )

            if "user" in tables:
                query += ", u.user_name, u.name "
                query += "FROM post p LEFT JOIN user u ON p.user_id = u.user_id "
            else:
                query += " FROM post p "

            query += "ORDER BY p.post_id DESC LIMIT ?"
            rows = conn.execute(query, (limit,)).fetchall()

            for row in rows:
                post = {
                    "post_id": row["post_id"],
                    "user_id": row["user_id"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                    "num_likes": row["num_likes"],
                    "num_dislikes": row["num_dislikes"],
                }
                if "user" in tables:
                    post["user_name"] = row["user_name"] if "user_name" in row.keys() else ""
                    post["name"] = row["name"] if "name" in row.keys() else ""
                posts.append(post)

        elif platform == "polymarket" and "market" in tables:
            # For Polymarket, return market info instead.
            rows = conn.execute(
                "SELECT market_id, question, outcome_a, outcome_b, "
                "reserve_a, reserve_b, created_at "
                "FROM market ORDER BY market_id"
            ).fetchall()

            for row in rows:
                total = row["reserve_a"] + row["reserve_b"]
                price_yes = row["reserve_b"] / total if total > 0 else 0.5
                posts.append({
                    "market_id": row["market_id"],
                    "question": row["question"],
                    "outcome_a": row["outcome_a"],
                    "outcome_b": row["outcome_b"],
                    "price_yes": round(price_yes, 4),
                    "price_no": round(1 - price_yes, 4),
                    "created_at": row["created_at"],
                })

        conn.close()

    except Exception:
        logger.exception("Failed to read posts from %s", db_path)

    return posts


# ======================================================================
# Trade readers (Polymarket specific)
# ======================================================================

def get_trades_from_db(
    sim_dir: str,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Read recent trades from the Polymarket SQLite database.

    Args:
        sim_dir: Path to the simulation directory.
        limit: Maximum number of trades to return.

    Returns:
        List of trade dicts.
    """
    db_path = os.path.join(sim_dir, "polymarket.db")
    if not os.path.exists(db_path):
        return []

    trades: List[Dict[str, Any]] = []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        if "trade" in tables:
            query = (
                "SELECT t.*, u.user_name, u.name "
                "FROM trade t "
                "LEFT JOIN user u ON t.user_id = u.user_id "
                "ORDER BY t.trade_id DESC LIMIT ?"
                if "user" in tables
                else "SELECT * FROM trade ORDER BY trade_id DESC LIMIT ?"
            )
            rows = conn.execute(query, (limit,)).fetchall()

            for row in rows:
                trade = dict(row)
                trades.append(trade)

        conn.close()

    except Exception:
        logger.exception("Failed to read trades from %s", db_path)

    return trades


# ======================================================================
# Divergence history
# ======================================================================

def get_divergence_from_actions(sim_dir: str) -> List[Dict[str, Any]]:
    """Extract divergence records from actions.jsonl.

    Returns:
        List of divergence dicts with ``round``, ``market_id``,
        ``internal_price``, ``real_price``, ``gap``.
    """
    actions = parse_actions_jsonl(sim_dir)
    return [
        {
            "round": a.get("_round", 0),
            "market_id": a.get("market_id"),
            "internal_price": a.get("internal_price"),
            "real_price": a.get("real_price"),
            "gap": a.get("gap"),
        }
        for a in actions
        if a.get("type") == "divergence"
    ]
