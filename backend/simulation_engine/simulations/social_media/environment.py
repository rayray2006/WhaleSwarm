"""Social-media observation environment for Twitter and Reddit.

Converts the current platform state visible to an agent into a text
prompt that the LLM can reason about.  Includes the agent's feed,
notifications, and any cross-platform context injected by the bridge.
"""

from __future__ import annotations

from typing import Any, List

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
    """

    def __init__(self, db: Database, platform_name: str = "Twitter") -> None:
        super().__init__()
        self.db = db
        self.platform_name = platform_name

    async def to_text_prompt(self, agent_id: int) -> str:
        """Build the observation prompt for *agent_id*.

        Sections:
        1. YOUR FEED -- recent posts from the recommendation engine
        2. YOUR NOTIFICATIONS -- likes/follows received
        3. CROSS-PLATFORM CONTEXT -- injected observations (if any)
        4. Call to action
        """
        sections: list[str] = []

        # ---- 1. Feed --------------------------------------------------------
        # Get recent posts (most recent 20).
        posts = self.db.fetchall(
            "SELECT p.post_id, p.user_id, p.content, p.created_at, "
            "p.num_likes, p.num_dislikes, u.user_name, u.name "
            "FROM post p "
            "LEFT JOIN user u ON p.user_id = u.user_id "
            "ORDER BY p.post_id DESC LIMIT 20",
        )

        if posts:
            feed_lines: list[str] = []
            for p in posts:
                who = p["user_name"] or p["name"] or f"user_{p['user_id']}"
                likes = p["num_likes"] or 0
                dislikes = p["num_dislikes"] or 0
                content = (p["content"] or "")[:300]
                line = (
                    f"  [Post #{p['post_id']}] @{who}: {content}\n"
                    f"    Likes: {likes}  Dislikes: {dislikes}"
                )
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

        # ---- 2. Notifications -----------------------------------------------
        # Check for recent likes on agent's own posts.
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
