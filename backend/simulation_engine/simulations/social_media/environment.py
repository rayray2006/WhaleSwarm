"""Social-media observation environment for Twitter and Reddit.

Converts the current platform state visible to an agent into a text
prompt that the LLM can reason about.  Includes the agent's feed
(personalized via rec_matrix when available), notifications, comments
on posts, and any cross-platform context injected by the bridge.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from simulation_engine.simulations.base import BaseEnvironment
from simulation_engine.social_platform.database import Database


class SocialMediaEnvironment(BaseEnvironment):
    """Renders the social-media world state as a text observation.

    Parameters
    ----------
    db:
        The shared SQLite Database instance used by the platform.
    platform_name:
        Either ``"Twitter"`` or ``"Reddit"`` -- used for prompt labelling.
    rec_matrix:
        Optional reference to the platform's recommendation matrix
        (``{user_id: [post_id, ...]}``) for personalized feeds.
    """

    def __init__(
        self,
        db: Database,
        platform_name: str = "Twitter",
        rec_matrix: Optional[Dict[int, List[int]]] = None,
    ) -> None:
        super().__init__()
        self.db = db
        self.platform_name = platform_name
        self.rec_matrix = rec_matrix

    async def to_text_prompt(self, agent_id: int) -> str:
        """Build the observation prompt for *agent_id*.

        Sections:
        1. YOUR FEED -- personalized posts (via rec_matrix or recent)
        2. YOUR NOTIFICATIONS -- likes/follows received
        3. CROSS-PLATFORM CONTEXT -- injected observations (if any)
        4. Call to action
        """
        sections: list[str] = []

        # ---- 1. Feed --------------------------------------------------------
        posts = self._get_feed_posts(agent_id, limit=15)

        if posts:
            feed_lines: list[str] = []
            for p in posts:
                who = p["user_name"] or p["name"] or f"user_{p['user_id']}"
                likes = p["num_likes"] or 0
                dislikes = p["num_dislikes"] or 0
                content = (p["content"] or "")[:300]

                if self.platform_name.lower() == "reddit":
                    score = likes - dislikes
                    sub_label = ""
                    if p.get("subreddit_name"):
                        sub_label = f"r/{p['subreddit_name']} | "
                    line = (
                        f"  [Post #{p['post_id']}] {sub_label}u/{who} ({score:+d} pts):\n"
                        f"    {content}"
                    )
                else:
                    line = (
                        f"  [Post #{p['post_id']}] @{who}: {content}\n"
                        f"    {likes} likes"
                    )

                # Attach comments (up to 3 per post).
                comments = self.db.fetchall(
                    "SELECT c.content, u.user_name, u.name "
                    "FROM comment c "
                    "LEFT JOIN user u ON c.user_id = u.user_id "
                    "WHERE c.post_id = ? "
                    "ORDER BY c.comment_id DESC LIMIT 3",
                    (p["post_id"],),
                )
                for c in reversed(list(comments)):
                    cwho = c["user_name"] or c["name"] or "anon"
                    ctext = (c["content"] or "")[:200]
                    line += f"\n      > {cwho}: {ctext}"

                feed_lines.append(line)

            sections.append(
                f"===== YOUR {self.platform_name.upper()} FEED =====\n"
                + "\n".join(feed_lines)
            )
        else:
            sections.append(
                f"===== YOUR {self.platform_name.upper()} FEED =====\n"
                "(no posts yet)"
            )

        # ---- 1b. Subreddit info (Reddit only) ------------------------------
        if self.platform_name.lower() == "reddit":
            followed_subs = self.db.fetchall(
                "SELECT s.name, s.num_followers "
                "FROM subreddit s "
                "JOIN subreddit_follow sf ON s.subreddit_id = sf.subreddit_id "
                "WHERE sf.user_id = ? "
                "ORDER BY s.num_followers DESC",
                (agent_id,),
            )
            if followed_subs:
                sub_names = [f"r/{r['name']}" for r in followed_subs]
                sections.append(
                    f"===== YOUR SUBREDDITS =====\n"
                    f"You follow: {', '.join(sub_names)} ({len(sub_names)} subreddits)"
                )
            else:
                sections.append(
                    "===== YOUR SUBREDDITS =====\n"
                    "You don't follow any subreddits yet. "
                    "Use browse_subreddit() to discover communities or create_subreddit() to start one."
                )

            # Show popular subreddits if agent follows fewer than 3.
            if len(followed_subs) < 3:
                popular = self.db.fetchall(
                    "SELECT name, description, num_followers FROM subreddit "
                    "ORDER BY num_followers DESC LIMIT 5"
                )
                if popular:
                    pop_lines = []
                    for r in popular:
                        desc = (r["description"] or "")[:80]
                        pop_lines.append(
                            f"  r/{r['name']} ({r['num_followers']} followers)"
                            + (f": {desc}" if desc else "")
                        )
                    sections.append(
                        "===== POPULAR SUBREDDITS =====\n"
                        + "\n".join(pop_lines)
                    )

        # ---- 2. Notifications -----------------------------------------------
        own_likes = self.db.fetchall(
            'SELECT COUNT(*) as cnt FROM "like" l '
            "JOIN post p ON l.post_id = p.post_id "
            "WHERE p.user_id = ?",
            (agent_id,),
        )
        like_count = own_likes[0]["cnt"] if own_likes else 0

        own_followers = self.db.fetchall(
            "SELECT COUNT(*) as cnt FROM follow WHERE followee_id = ?",
            (agent_id,),
        )
        follower_count = own_followers[0]["cnt"] if own_followers else 0

        if like_count > 0 or follower_count > 0:
            sections.append(
                f"===== NOTIFICATIONS =====\n"
                f"Your posts have received {like_count} total likes.\n"
                f"You have {follower_count} followers."
            )

        # ---- 3. Cross-platform context (injected by the bridge) -------------
        if self.extra_observation_context:
            sections.append(
                "===== CROSS-PLATFORM CONTEXT =====\n"
                + self.extra_observation_context
            )

        # ---- 4. Call to action ----------------------------------------------
        sections.append(
            "What do you want to do? Choose one action from the available tools."
        )

        return "\n\n".join(sections)

    def _get_feed_posts(self, agent_id: int, limit: int = 15) -> list:
        """Return posts for this agent's feed.

        Uses the recommendation matrix for personalization when available,
        falling back to the most recent posts.
        """
        rec_ids = None
        if self.rec_matrix is not None:
            rec_ids = self.rec_matrix.get(agent_id)

        if rec_ids:
            # Fetch recommended posts (shuffled for variety).
            ids = list(rec_ids[:limit])
            random.shuffle(ids)
            placeholders = ",".join("?" for _ in ids)
            return self.db.fetchall(
                f"SELECT p.post_id, p.user_id, p.content, p.created_at, "
                f"p.num_likes, p.num_dislikes, p.subreddit_id, "
                f"u.user_name, u.name, "
                f"s.name as subreddit_name "
                f"FROM post p "
                f"LEFT JOIN user u ON p.user_id = u.user_id "
                f"LEFT JOIN subreddit s ON p.subreddit_id = s.subreddit_id "
                f"WHERE p.post_id IN ({placeholders}) "
                f"ORDER BY p.post_id DESC",
                tuple(ids),
            )

        # Fallback: most recent posts.
        return self.db.fetchall(
            "SELECT p.post_id, p.user_id, p.content, p.created_at, "
            "p.num_likes, p.num_dislikes, p.subreddit_id, "
            "u.user_name, u.name, "
            "s.name as subreddit_name "
            "FROM post p "
            "LEFT JOIN user u ON p.user_id = u.user_id "
            "LEFT JOIN subreddit s ON p.subreddit_id = s.subreddit_id "
            "ORDER BY p.post_id DESC LIMIT ?",
            (limit,),
        )
