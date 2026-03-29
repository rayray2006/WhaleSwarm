"""Concrete social-media Platform for Twitter and Reddit simulations.

Extends :class:`BasePlatform` with handler methods for every social-media
action type (create_post, like_post, repost, follow, etc.) plus the
sign_up action for agent registration.

Each handler writes to the SQLite database via ``self.db`` and returns a
result dict to the calling agent through the channel.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from simulation_engine.simulations.base import BasePlatform
from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.platform_utils import (
    now_iso,
    sanitize_content,
    truncate,
)
from simulation_engine.social_platform.recsys import (
    random_recsys,
    reddit_hot_score_recsys,
    reddit_subreddit_recsys,
    twitter_recsys,
    twhin_recsys,
)
from simulation_engine.social_platform.typing import ActionType, RecsysType

logger = logging.getLogger(__name__)

# Additional schema directory for social-media-specific tables (repost,
# quote_post) that live alongside the simulation, not the core platform.
_SOCIAL_MEDIA_SCHEMA_DIR = (
    Path(__file__).resolve().parent.parent
    / "simulations"
    / "social_media"
    / "schema"
)


class Platform(BasePlatform):
    """Social-media platform supporting both Twitter and Reddit actions.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    channel:
        The async channel connecting agents to this platform.
    recsys_type:
        Which recommendation engine to use for building per-agent feeds.
    max_rec_post_len:
        Maximum number of posts in a single agent's recommended feed.
    """

    # Core schemas loaded by BasePlatform.__init__ + our extras.
    required_schemas: List[str] = [
        "post",
        "like",
        "dislike",
        "follow",
        "mute",
        "comment",
        "report",
    ]

    def __init__(
        self,
        db_path: str,
        channel: Channel,
        *,
        recsys_type: RecsysType = RecsysType.RANDOM,
        max_rec_post_len: int = 20,
    ) -> None:
        super().__init__(db_path, channel)

        self.recsys_type = recsys_type
        self.max_rec_post_len = max_rec_post_len

        # Recommendation matrix: user_id -> [post_id, ...]
        self.rec_matrix: Dict[int, List[int]] = {}

        # Track registered agent count for random recsys.
        self._agent_count: int = 0

        # Load social-media-specific schemas (repost, quote_post).
        self._load_extra_schemas()

    # ------------------------------------------------------------------
    # Extra schema loading
    # ------------------------------------------------------------------

    def _load_extra_schemas(self) -> None:
        """Load extra schemas from the social_media dir."""
        for name in (
            "repost", "quote_post",
            "subreddit", "subreddit_follow", "subreddit_similarity",
        ):
            sql_path = _SOCIAL_MEDIA_SCHEMA_DIR / f"{name}.sql"
            if sql_path.exists():
                sql = sql_path.read_text(encoding="utf-8")
                self.db.conn.executescript(sql)
                logger.debug("Loaded extra schema '%s' from %s", name, sql_path)
            else:
                logger.warning("Extra schema file not found: %s", sql_path)

        # Add subreddit_id column to post table (nullable, for Reddit posts).
        try:
            self.db.conn.execute(
                "ALTER TABLE post ADD COLUMN subreddit_id INTEGER DEFAULT NULL"
            )
        except Exception:
            pass  # Column already exists

    # ------------------------------------------------------------------
    # Recommendation system
    # ------------------------------------------------------------------

    def refresh_rec_matrix(self) -> None:
        """Rebuild the recommendation matrix using the configured recsys."""
        all_posts = self._fetch_all_posts()
        if not all_posts:
            self.rec_matrix = {}
            return

        if self.recsys_type == RecsysType.RANDOM:
            self.rec_matrix = random_recsys(
                self._agent_count, self.max_rec_post_len, all_posts
            )
        elif self.recsys_type == RecsysType.REDDIT:
            self.rec_matrix = reddit_subreddit_recsys(
                all_posts, self.max_rec_post_len, self.db, self._agent_count
            )
        elif self.recsys_type in (RecsysType.TWITTER, RecsysType.TWHIN):
            user_profiles = self._fetch_user_profiles()
            func = (
                twitter_recsys
                if self.recsys_type == RecsysType.TWITTER
                else twhin_recsys
            )
            self.rec_matrix = func(
                user_profiles, all_posts, self.max_rec_post_len
            )
        else:
            self.rec_matrix = random_recsys(
                self._agent_count, self.max_rec_post_len, all_posts
            )

    def _fetch_all_posts(self) -> List[Dict[str, Any]]:
        """Return all posts as a list of dicts."""
        rows = self.db.fetchall(
            "SELECT post_id, user_id, content, created_at, num_likes, num_dislikes, subreddit_id "
            "FROM post ORDER BY post_id"
        )
        return [dict(r) for r in rows]

    def _fetch_user_profiles(self) -> List[Dict[str, Any]]:
        """Return user profiles augmented with recent posts for embedding."""
        users = self.db.fetchall(
            "SELECT user_id, user_name, name, bio FROM user ORDER BY user_id"
        )
        profiles: List[Dict[str, Any]] = []
        for u in users:
            recent_rows = self.db.fetchall(
                "SELECT content FROM post WHERE user_id = ? ORDER BY post_id DESC LIMIT 5",
                (u["user_id"],),
            )
            profiles.append(
                {
                    "user_id": u["user_id"],
                    "name": u["name"] or u["user_name"],
                    "bio": u["bio"] or "",
                    "recent_posts": [r["content"] for r in recent_rows],
                }
            )
        return profiles

    # ------------------------------------------------------------------
    # sign_up
    # ------------------------------------------------------------------

    def sign_up(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Register an agent as a user on the platform.

        Expected *message* keys: ``user_name``, ``name``, ``bio``.
        """
        user_name = message.get("user_name", f"user_{agent_id}")
        name = message.get("name", user_name)
        bio = message.get("bio", "")
        created_at = now_iso()

        # Use agent_id as user_id for simplicity.
        user_id = agent_id
        self.db.execute(
            "INSERT OR IGNORE INTO user "
            "(user_id, agent_id, user_name, name, bio, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, agent_id, user_name, name, bio, created_at),
        )
        self._agent_count = max(self._agent_count, user_id + 1)
        self.log_trace(user_id, "sign_up", json.dumps({"user_name": user_name}), created_at)

        return {
            "success": True,
            "user_id": user_id,
            "user_name": user_name,
        }

    # ------------------------------------------------------------------
    # Twitter actions
    # ------------------------------------------------------------------

    def create_post(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Create a new post (tweet / Reddit submission).

        Expected *message* keys: ``content``, optionally ``subreddit_name``.
        """
        content = sanitize_content(message.get("content", ""))
        if not content:
            return {"success": False, "error": "empty content"}

        subreddit_name = message.get("subreddit_name", "")
        subreddit_id = None
        if subreddit_name:
            subreddit_name = subreddit_name.strip().lower().lstrip("r/")
            row = self.db.fetchone(
                "SELECT subreddit_id FROM subreddit WHERE name = ?",
                (subreddit_name,),
            )
            if not row:
                return {"success": False, "error": f"subreddit '{subreddit_name}' does not exist"}
            subreddit_id = row["subreddit_id"]

        created_at = now_iso()
        cursor = self.db.execute(
            "INSERT INTO post (user_id, content, created_at, subreddit_id) VALUES (?, ?, ?, ?)",
            (agent_id, content, created_at, subreddit_id),
        )
        post_id = cursor.lastrowid
        self.log_trace(
            agent_id, "create_post",
            json.dumps({"post_id": post_id, "subreddit_name": subreddit_name or None}),
            created_at,
        )

        return {"success": True, "post_id": post_id}

    def like_post(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Like a post.

        Expected *message* keys: ``post_id``.
        """
        post_id = message.get("post_id")
        if post_id is None:
            return {"success": False, "error": "missing post_id"}

        post = self.db.fetchone("SELECT user_id FROM post WHERE post_id = ?", (post_id,))
        if post and post["user_id"] == agent_id:
            return {"success": False, "error": "cannot like your own post"}

        created_at = now_iso()
        try:
            self.db.execute(
                'INSERT OR IGNORE INTO "like" (user_id, post_id, created_at) VALUES (?, ?, ?)',
                (agent_id, post_id, created_at),
            )
            self.db.execute(
                "UPDATE post SET num_likes = num_likes + 1 WHERE post_id = ?",
                (post_id,),
            )
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        self.log_trace(agent_id, "like_post", json.dumps({"post_id": post_id}), created_at)
        return {"success": True, "post_id": post_id}

    def unlike_post(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Remove a like from a post.

        Expected *message* keys: ``post_id``.
        """
        post_id = message.get("post_id")
        if post_id is None:
            return {"success": False, "error": "missing post_id"}

        created_at = now_iso()
        cursor = self.db.execute(
            'DELETE FROM "like" WHERE user_id = ? AND post_id = ?',
            (agent_id, post_id),
        )
        if cursor.rowcount > 0:
            self.db.execute(
                "UPDATE post SET num_likes = MAX(num_likes - 1, 0) WHERE post_id = ?",
                (post_id,),
            )
        self.log_trace(agent_id, "unlike_post", json.dumps({"post_id": post_id}), created_at)
        return {"success": True, "post_id": post_id}

    def repost(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Repost (retweet) an existing post.

        Expected *message* keys: ``post_id``.
        """
        post_id = message.get("post_id")
        if post_id is None:
            return {"success": False, "error": "missing post_id"}

        created_at = now_iso()
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO repost (user_id, post_id, created_at) VALUES (?, ?, ?)",
                (agent_id, post_id, created_at),
            )
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        self.log_trace(agent_id, "repost", json.dumps({"post_id": post_id}), created_at)
        return {"success": True, "post_id": post_id}

    def quote_post(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Quote-tweet a post with additional commentary.

        Expected *message* keys: ``post_id``, ``content``.
        """
        post_id = message.get("post_id")
        content = sanitize_content(message.get("content", ""))
        if post_id is None:
            return {"success": False, "error": "missing post_id"}
        if not content:
            return {"success": False, "error": "empty content"}

        created_at = now_iso()
        cursor = self.db.execute(
            "INSERT INTO quote_post (user_id, post_id, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (agent_id, post_id, content, created_at),
        )
        quote_id = cursor.lastrowid
        self.log_trace(
            agent_id,
            "quote_post",
            json.dumps({"quote_id": quote_id, "post_id": post_id}),
            created_at,
        )
        return {"success": True, "quote_id": quote_id, "post_id": post_id}

    def follow(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Follow another user.

        Expected *message* keys: ``followee_id``.
        """
        followee_id = message.get("followee_id")
        if followee_id is None:
            return {"success": False, "error": "missing followee_id"}
        if followee_id == agent_id:
            return {"success": False, "error": "cannot follow yourself"}

        created_at = now_iso()
        self.db.execute(
            "INSERT OR IGNORE INTO follow (follower_id, followee_id, created_at) "
            "VALUES (?, ?, ?)",
            (agent_id, followee_id, created_at),
        )
        self.db.execute(
            "UPDATE user SET num_followings = num_followings + 1 WHERE user_id = ?",
            (agent_id,),
        )
        self.db.execute(
            "UPDATE user SET num_followers = num_followers + 1 WHERE user_id = ?",
            (followee_id,),
        )
        self.log_trace(agent_id, "follow", json.dumps({"followee_id": followee_id}), created_at)
        return {"success": True, "followee_id": followee_id}

    def unfollow(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Unfollow a user.

        Expected *message* keys: ``followee_id``.
        """
        followee_id = message.get("followee_id")
        if followee_id is None:
            return {"success": False, "error": "missing followee_id"}

        created_at = now_iso()
        cursor = self.db.execute(
            "DELETE FROM follow WHERE follower_id = ? AND followee_id = ?",
            (agent_id, followee_id),
        )
        if cursor.rowcount > 0:
            self.db.execute(
                "UPDATE user SET num_followings = MAX(num_followings - 1, 0) WHERE user_id = ?",
                (agent_id,),
            )
            self.db.execute(
                "UPDATE user SET num_followers = MAX(num_followers - 1, 0) WHERE user_id = ?",
                (followee_id,),
            )
        self.log_trace(agent_id, "unfollow", json.dumps({"followee_id": followee_id}), created_at)
        return {"success": True, "followee_id": followee_id}

    def mute(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Mute another user.

        Expected *message* keys: ``muted_id``.
        """
        muted_id = message.get("muted_id")
        if muted_id is None:
            return {"success": False, "error": "missing muted_id"}

        created_at = now_iso()
        self.db.execute(
            "INSERT OR IGNORE INTO mute (user_id, muted_id, created_at) VALUES (?, ?, ?)",
            (agent_id, muted_id, created_at),
        )
        self.log_trace(agent_id, "mute", json.dumps({"muted_id": muted_id}), created_at)
        return {"success": True, "muted_id": muted_id}

    # ------------------------------------------------------------------
    # Reddit actions
    # ------------------------------------------------------------------

    def create_comment(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Create a comment on a post.

        Expected *message* keys: ``post_id``, ``content``.
        """
        post_id = message.get("post_id")
        content = sanitize_content(message.get("content", ""))
        if post_id is None:
            return {"success": False, "error": "missing post_id"}
        if not content:
            return {"success": False, "error": "empty content"}

        created_at = now_iso()
        cursor = self.db.execute(
            "INSERT INTO comment (post_id, user_id, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (post_id, agent_id, content, created_at),
        )
        comment_id = cursor.lastrowid
        self.log_trace(
            agent_id,
            "create_comment",
            json.dumps({"comment_id": comment_id, "post_id": post_id}),
            created_at,
        )
        return {"success": True, "comment_id": comment_id, "post_id": post_id}

    def dislike_post(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Dislike (downvote) a post.

        Expected *message* keys: ``post_id``.
        """
        post_id = message.get("post_id")
        if post_id is None:
            return {"success": False, "error": "missing post_id"}

        post = self.db.fetchone("SELECT user_id FROM post WHERE post_id = ?", (post_id,))
        if post and post["user_id"] == agent_id:
            return {"success": False, "error": "cannot dislike your own post"}

        created_at = now_iso()
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO dislike (user_id, post_id, created_at) VALUES (?, ?, ?)",
                (agent_id, post_id, created_at),
            )
            self.db.execute(
                "UPDATE post SET num_dislikes = num_dislikes + 1 WHERE post_id = ?",
                (post_id,),
            )
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        self.log_trace(agent_id, "dislike_post", json.dumps({"post_id": post_id}), created_at)
        return {"success": True, "post_id": post_id}

    def dislike_comment(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Dislike a comment.

        Expected *message* keys: ``comment_id``.

        Note: comment dislike tracking is logged in the trace table.
        """
        comment_id = message.get("comment_id")
        if comment_id is None:
            return {"success": False, "error": "missing comment_id"}

        created_at = now_iso()
        self.log_trace(
            agent_id, "dislike_comment", json.dumps({"comment_id": comment_id}), created_at
        )
        return {"success": True, "comment_id": comment_id}

    def like_comment(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Like a comment.

        Expected *message* keys: ``comment_id``.
        """
        comment_id = message.get("comment_id")
        if comment_id is None:
            return {"success": False, "error": "missing comment_id"}

        created_at = now_iso()
        self.log_trace(
            agent_id, "like_comment", json.dumps({"comment_id": comment_id}), created_at
        )
        return {"success": True, "comment_id": comment_id}

    def search_posts(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Search posts by keyword.

        Expected *message* keys: ``query``.
        """
        query = message.get("query", "")
        if not query:
            return {"success": False, "error": "empty query"}

        created_at = now_iso()
        rows = self.db.fetchall(
            "SELECT post_id, user_id, content, created_at, num_likes, num_dislikes "
            "FROM post WHERE content LIKE ? ORDER BY post_id DESC LIMIT 20",
            (f"%{query}%",),
        )
        results = [dict(r) for r in rows]
        self.log_trace(
            agent_id,
            "search_posts",
            json.dumps({"query": query, "result_count": len(results)}),
            created_at,
        )
        return {"success": True, "posts": results}

    def search_user(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Search for users by name or username.

        Expected *message* keys: ``query``.
        """
        query = message.get("query", "")
        if not query:
            return {"success": False, "error": "empty query"}

        created_at = now_iso()
        rows = self.db.fetchall(
            "SELECT user_id, user_name, name, bio, num_followers, num_followings "
            "FROM user WHERE user_name LIKE ? OR name LIKE ? LIMIT 20",
            (f"%{query}%", f"%{query}%"),
        )
        results = [dict(r) for r in rows]
        self.log_trace(
            agent_id,
            "search_user",
            json.dumps({"query": query, "result_count": len(results)}),
            created_at,
        )
        return {"success": True, "users": results}

    def trend(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Return trending posts (most liked in the last period).

        No required message keys.
        """
        created_at = now_iso()
        rows = self.db.fetchall(
            "SELECT post_id, user_id, content, created_at, num_likes, num_dislikes "
            "FROM post ORDER BY num_likes DESC LIMIT 10"
        )
        results = [dict(r) for r in rows]
        self.log_trace(agent_id, "trend", json.dumps({"count": len(results)}), created_at)
        return {"success": True, "posts": results}

    def refresh(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Refresh the agent's feed from the recommendation matrix.

        Returns the recommended posts for this agent.
        """
        created_at = now_iso()
        rec_post_ids = self.rec_matrix.get(agent_id, [])
        if not rec_post_ids:
            self.log_trace(agent_id, "refresh", json.dumps({"count": 0}), created_at)
            return {"success": True, "posts": []}

        placeholders = ",".join("?" for _ in rec_post_ids)
        rows = self.db.fetchall(
            f"SELECT post_id, user_id, content, created_at, num_likes, num_dislikes "
            f"FROM post WHERE post_id IN ({placeholders}) ORDER BY post_id DESC",
            tuple(rec_post_ids),
        )
        results = [dict(r) for r in rows]
        self.log_trace(agent_id, "refresh", json.dumps({"count": len(results)}), created_at)
        return {"success": True, "posts": results}

    def report(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Report a post for moderation.

        Expected *message* keys: ``post_id``, optionally ``reason``.
        """
        post_id = message.get("post_id")
        reason = message.get("reason", "")
        if post_id is None:
            return {"success": False, "error": "missing post_id"}

        created_at = now_iso()
        self.db.execute(
            "INSERT INTO report (user_id, post_id, reason, created_at) VALUES (?, ?, ?, ?)",
            (agent_id, post_id, reason, created_at),
        )
        self.log_trace(
            agent_id, "report", json.dumps({"post_id": post_id, "reason": reason}), created_at
        )
        return {"success": True, "post_id": post_id}

    # ------------------------------------------------------------------
    # Subreddit actions
    # ------------------------------------------------------------------

    def create_subreddit(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Create a new subreddit community.

        Expected *message* keys: ``name``, optionally ``description``,
        ``similar_to`` (list of subreddit name strings).
        """
        raw_name = message.get("name", "")
        if not raw_name:
            return {"success": False, "error": "missing subreddit name"}

        name = raw_name.strip().lower().replace(" ", "_").lstrip("r/")[:30]
        if not name:
            return {"success": False, "error": "invalid subreddit name"}

        # Check uniqueness.
        existing = self.db.fetchone(
            "SELECT subreddit_id FROM subreddit WHERE name = ?", (name,)
        )
        if existing:
            return {"success": False, "error": f"subreddit '{name}' already exists"}

        description = message.get("description", "")
        similar_to = message.get("similar_to", [])
        if isinstance(similar_to, str):
            similar_to = [s.strip() for s in similar_to.split(",") if s.strip()]

        created_at = now_iso()
        cursor = self.db.execute(
            "INSERT INTO subreddit (name, description, creator_id, num_followers, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (name, description, agent_id, created_at),
        )
        subreddit_id = cursor.lastrowid

        # Auto-follow the creator.
        self.db.execute(
            "INSERT OR IGNORE INTO subreddit_follow (user_id, subreddit_id, created_at) "
            "VALUES (?, ?, ?)",
            (agent_id, subreddit_id, created_at),
        )

        # Insert bidirectional similarity edges.
        for sim_name in similar_to:
            sim_name = sim_name.strip().lower().lstrip("r/")
            sim_row = self.db.fetchone(
                "SELECT subreddit_id FROM subreddit WHERE name = ?", (sim_name,)
            )
            if sim_row:
                sim_id = sim_row["subreddit_id"]
                self.db.execute(
                    "INSERT OR IGNORE INTO subreddit_similarity "
                    "(subreddit_id, similar_subreddit_id, created_at) VALUES (?, ?, ?)",
                    (subreddit_id, sim_id, created_at),
                )
                self.db.execute(
                    "INSERT OR IGNORE INTO subreddit_similarity "
                    "(subreddit_id, similar_subreddit_id, created_at) VALUES (?, ?, ?)",
                    (sim_id, subreddit_id, created_at),
                )

        self.log_trace(
            agent_id, "create_subreddit",
            json.dumps({"subreddit_id": subreddit_id, "name": name, "similar_to": similar_to}),
            created_at,
        )
        return {"success": True, "subreddit_id": subreddit_id, "name": name}

    def follow_subreddit(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Follow a subreddit.

        Expected *message* keys: ``subreddit_name``.
        """
        raw_name = message.get("subreddit_name", "")
        if not raw_name:
            return {"success": False, "error": "missing subreddit_name"}

        name = raw_name.strip().lower().lstrip("r/")
        row = self.db.fetchone(
            "SELECT subreddit_id FROM subreddit WHERE name = ?", (name,)
        )
        if not row:
            return {"success": False, "error": f"subreddit '{name}' does not exist"}

        subreddit_id = row["subreddit_id"]
        created_at = now_iso()

        # Check if already following.
        existing = self.db.fetchone(
            "SELECT 1 FROM subreddit_follow WHERE user_id = ? AND subreddit_id = ?",
            (agent_id, subreddit_id),
        )
        if not existing:
            self.db.execute(
                "INSERT INTO subreddit_follow (user_id, subreddit_id, created_at) "
                "VALUES (?, ?, ?)",
                (agent_id, subreddit_id, created_at),
            )
            self.db.execute(
                "UPDATE subreddit SET num_followers = num_followers + 1 "
                "WHERE subreddit_id = ?",
                (subreddit_id,),
            )

        self.log_trace(
            agent_id, "follow_subreddit",
            json.dumps({"subreddit_name": name}), created_at,
        )
        return {"success": True, "subreddit_name": name}

    def unfollow_subreddit(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Unfollow a subreddit.

        Expected *message* keys: ``subreddit_name``.
        """
        raw_name = message.get("subreddit_name", "")
        if not raw_name:
            return {"success": False, "error": "missing subreddit_name"}

        name = raw_name.strip().lower().lstrip("r/")
        row = self.db.fetchone(
            "SELECT subreddit_id FROM subreddit WHERE name = ?", (name,)
        )
        if not row:
            return {"success": False, "error": f"subreddit '{name}' does not exist"}

        subreddit_id = row["subreddit_id"]
        created_at = now_iso()

        cursor = self.db.execute(
            "DELETE FROM subreddit_follow WHERE user_id = ? AND subreddit_id = ?",
            (agent_id, subreddit_id),
        )
        if cursor.rowcount > 0:
            self.db.execute(
                "UPDATE subreddit SET num_followers = MAX(num_followers - 1, 0) "
                "WHERE subreddit_id = ?",
                (subreddit_id,),
            )

        self.log_trace(
            agent_id, "unfollow_subreddit",
            json.dumps({"subreddit_name": name}), created_at,
        )
        return {"success": True, "subreddit_name": name}

    def browse_subreddit(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """Browse posts in a subreddit or the agent's combined followed feed.

        Expected *message* keys: optionally ``subreddit_name``.
        If omitted, returns posts from all followed subreddits.
        """
        subreddit_name = (message.get("subreddit_name") or "").strip().lower().lstrip("r/")
        created_at = now_iso()

        if subreddit_name:
            # Browse a specific subreddit.
            row = self.db.fetchone(
                "SELECT subreddit_id FROM subreddit WHERE name = ?",
                (subreddit_name,),
            )
            if not row:
                return {"success": False, "error": f"subreddit '{subreddit_name}' does not exist"}

            posts = self.db.fetchall(
                "SELECT p.post_id, p.user_id, p.content, p.created_at, "
                "p.num_likes, p.num_dislikes, u.user_name, u.name "
                "FROM post p "
                "LEFT JOIN user u ON p.user_id = u.user_id "
                "WHERE p.subreddit_id = ? "
                "ORDER BY p.num_likes - p.num_dislikes DESC, p.post_id DESC "
                "LIMIT 10",
                (row["subreddit_id"],),
            )
        else:
            # Browse combined followed subreddits.
            followed_ids = self.db.fetchall(
                "SELECT subreddit_id FROM subreddit_follow WHERE user_id = ?",
                (agent_id,),
            )
            if not followed_ids:
                return {
                    "success": True,
                    "posts": [],
                    "subreddits_followed": [],
                    "message": "You don't follow any subreddits yet.",
                }

            sub_ids = [r["subreddit_id"] for r in followed_ids]
            placeholders = ",".join("?" for _ in sub_ids)
            posts = self.db.fetchall(
                f"SELECT p.post_id, p.user_id, p.content, p.created_at, "
                f"p.num_likes, p.num_dislikes, u.user_name, u.name "
                f"FROM post p "
                f"LEFT JOIN user u ON p.user_id = u.user_id "
                f"WHERE p.subreddit_id IN ({placeholders}) "
                f"ORDER BY p.num_likes - p.num_dislikes DESC, p.post_id DESC "
                f"LIMIT 10",
                tuple(sub_ids),
            )

        # Get list of followed subreddits for context.
        followed_subs = self.db.fetchall(
            "SELECT s.name FROM subreddit s "
            "JOIN subreddit_follow sf ON s.subreddit_id = sf.subreddit_id "
            "WHERE sf.user_id = ?",
            (agent_id,),
        )
        followed_names = [r["name"] for r in followed_subs]

        results = [dict(r) for r in posts]
        self.log_trace(
            agent_id, "browse_subreddit",
            json.dumps({
                "subreddit_name": subreddit_name or "(home)",
                "count": len(results),
            }),
            created_at,
        )
        return {
            "success": True,
            "posts": results,
            "subreddits_followed": followed_names,
        }

    # ------------------------------------------------------------------
    # Shared / no-op actions
    # ------------------------------------------------------------------

    def do_nothing(self, agent_id: int, message: Any) -> Dict[str, Any]:
        """No-op action. The agent chose to do nothing this turn."""
        self.log_trace(agent_id, "do_nothing", "{}", now_iso())
        return {"success": True}
