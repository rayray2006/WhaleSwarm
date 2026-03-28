"""Per-round analysis helpers for feeding the belief-state system.

After each simulation round, the runner calls ``analyze_round`` to:
1. Extract the posts each agent saw (from the recommendation matrix).
2. Compute engagement metrics for each agent's own posts.
3. Feed results into ``BeliefState.update_from_round``.
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from simulation_engine.social_platform.database import Database
from simulation_engine.social_agent.belief_state import BeliefState

logger = logging.getLogger(__name__)


# ======================================================================
# Post extraction
# ======================================================================

def get_posts_seen_by_agent(
    db: Database,
    agent_user_id: int,
    rec_post_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Retrieve the posts an agent was shown during a round.

    Args:
        db: The platform's SQLite database.
        agent_user_id: The ``user_id`` of the agent in the DB.
        rec_post_ids: If the recommendation system provided a list of
            post ids for this agent, pass them here.  Otherwise all
            posts from the latest round are returned.

    Returns:
        List of dicts with keys ``content``, ``author_id``, ``num_likes``,
        ``num_dislikes``, ``post_id``, ``created_at``.
    """
    if rec_post_ids:
        placeholders = ",".join("?" for _ in rec_post_ids)
        rows = db.fetchall(
            f"SELECT post_id, user_id, content, num_likes, num_dislikes, created_at "
            f"FROM post WHERE post_id IN ({placeholders})",
            tuple(rec_post_ids),
        )
    else:
        # Fallback: get the most recent posts (last 50).
        rows = db.fetchall(
            "SELECT post_id, user_id, content, num_likes, num_dislikes, created_at "
            "FROM post ORDER BY post_id DESC LIMIT 50",
        )

    posts: List[Dict[str, Any]] = []
    for row in rows:
        # Skip agent's own posts — they should not influence their own beliefs.
        if row["user_id"] == agent_user_id:
            continue
        posts.append({
            "post_id": row["post_id"],
            "author_id": row["user_id"],
            "content": row["content"] or "",
            "num_likes": row["num_likes"],
            "num_dislikes": row["num_dislikes"],
            "created_at": row["created_at"],
        })

    return posts


# ======================================================================
# Engagement metrics
# ======================================================================

def get_own_engagement(
    db: Database,
    agent_user_id: int,
    round_post_ids: Optional[List[int]] = None,
) -> Dict[str, int]:
    """Compute likes/dislikes received on an agent's own posts this round.

    Args:
        db: Platform database.
        agent_user_id: The agent's ``user_id``.
        round_post_ids: If known, restrict counting to these post ids.

    Returns:
        ``{"likes_received": int, "dislikes_received": int}``.
    """
    # Get this agent's post ids.
    if round_post_ids:
        placeholders = ",".join("?" for _ in round_post_ids)
        own_rows = db.fetchall(
            f"SELECT post_id FROM post WHERE user_id = ? AND post_id IN ({placeholders})",
            (agent_user_id, *round_post_ids),
        )
    else:
        own_rows = db.fetchall(
            "SELECT post_id FROM post WHERE user_id = ? ORDER BY post_id DESC LIMIT 20",
            (agent_user_id,),
        )

    if not own_rows:
        return {"likes_received": 0, "dislikes_received": 0}

    own_ids = [r["post_id"] for r in own_rows]
    placeholders = ",".join("?" for _ in own_ids)

    # Count likes.
    like_row = db.fetchone(
        f'SELECT COUNT(*) as cnt FROM "like" WHERE post_id IN ({placeholders})',
        tuple(own_ids),
    )
    likes = like_row["cnt"] if like_row else 0

    # Count dislikes (table may not exist on all platforms).
    try:
        dislike_row = db.fetchone(
            f"SELECT COUNT(*) as cnt FROM dislike WHERE post_id IN ({placeholders})",
            tuple(own_ids),
        )
        dislikes = dislike_row["cnt"] if dislike_row else 0
    except Exception:
        dislikes = 0

    return {"likes_received": likes, "dislikes_received": dislikes}


# ======================================================================
# Trust-updating helpers
# ======================================================================

def extract_trust_actions(
    db: Database,
    agent_user_id: int,
    since_trace_id: int = 0,
) -> List[Tuple[int, str]]:
    """Extract social actions from traces that should update trust.

    Returns a list of ``(other_agent_id, action_type)`` tuples.
    """
    trust_actions: List[Tuple[int, str]] = []

    # Likes given by this agent.
    like_rows = db.fetchall(
        'SELECT post_id FROM "like" WHERE user_id = ?',
        (agent_user_id,),
    )
    if like_rows:
        post_ids = [r["post_id"] for r in like_rows]
        placeholders = ",".join("?" for _ in post_ids)
        author_rows = db.fetchall(
            f"SELECT DISTINCT user_id FROM post WHERE post_id IN ({placeholders})",
            tuple(post_ids),
        )
        for r in author_rows:
            if r["user_id"] != agent_user_id:
                trust_actions.append((r["user_id"], "like"))

    # Dislikes given by this agent.
    try:
        dislike_rows = db.fetchall(
            "SELECT post_id FROM dislike WHERE user_id = ?",
            (agent_user_id,),
        )
        if dislike_rows:
            post_ids = [r["post_id"] for r in dislike_rows]
            placeholders = ",".join("?" for _ in post_ids)
            author_rows = db.fetchall(
                f"SELECT DISTINCT user_id FROM post WHERE post_id IN ({placeholders})",
                tuple(post_ids),
            )
            for r in author_rows:
                if r["user_id"] != agent_user_id:
                    trust_actions.append((r["user_id"], "dislike"))
    except Exception:
        pass

    # Follows by this agent.
    follow_rows = db.fetchall(
        "SELECT followee_id FROM follow WHERE follower_id = ?",
        (agent_user_id,),
    )
    for r in follow_rows:
        trust_actions.append((r["followee_id"], "follow"))

    # Mutes by this agent.
    try:
        mute_rows = db.fetchall(
            "SELECT muted_id FROM mute WHERE user_id = ?",
            (agent_user_id,),
        )
        for r in mute_rows:
            trust_actions.append((r["muted_id"], "mute"))
    except Exception:
        pass

    return trust_actions


# ======================================================================
# High-level round analysis
# ======================================================================

def analyze_round(
    db: Database,
    agents_with_beliefs: List[Tuple[int, "BeliefState"]],
    round_num: int,
    rec_matrix: Optional[Dict[int, List[int]]] = None,
) -> None:
    """Run the full per-round belief update for every agent.

    Args:
        db: The platform's SQLite database.
        agents_with_beliefs: List of ``(user_id, BeliefState)`` pairs.
        round_num: The current round number.
        rec_matrix: Optional mapping of ``user_id`` -> list of recommended
            ``post_id``s.  If ``None``, falls back to recent posts.
    """
    for user_id, belief in agents_with_beliefs:
        try:
            rec_ids = rec_matrix.get(user_id) if rec_matrix else None

            posts_seen = get_posts_seen_by_agent(db, user_id, rec_ids)
            engagement = get_own_engagement(db, user_id)

            belief.update_from_round(posts_seen, engagement, round_num)

            # Trust updates from social actions.
            trust_actions = extract_trust_actions(db, user_id)
            for other_id, action_type in trust_actions:
                belief.update_trust(other_id, action_type)

        except Exception:
            logger.exception(
                "Error analysing round %d for agent %d", round_num, user_id,
            )
