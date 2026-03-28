"""Prompt builders for Twitter and Reddit social-media simulations.

Each builder constructs a detailed system prompt that tells the LLM
agent who it is, how the platform works, and what actions are available.
"""

from __future__ import annotations

import textwrap
from typing import Any

from simulation_engine.simulations.base import BasePromptBuilder


# ======================================================================
# Twitter
# ======================================================================

class TwitterPromptBuilder(BasePromptBuilder):
    """Builds the system prompt for a Twitter agent."""

    def build_system_prompt(self, user_info: Any) -> str:
        """Return the complete system prompt for a Twitter simulation agent.

        Args:
            user_info: Dict (or object) with keys ``name``, ``user_name``,
                ``bio`` / ``description``, and optionally ``persona``.
        """
        name = _get(user_info, "name", "Unknown")
        user_name = _get(user_info, "user_name", "user")
        bio = _get(user_info, "bio") or _get(user_info, "description", "")
        persona = _get(user_info, "persona", "")

        persona_block = persona if persona else bio

        return textwrap.dedent(f"""\
            ===== WHO YOU ARE =====
            You are {name} (@{user_name}).
            {persona_block}

            ===== HOW TWITTER WORKS =====
            You are on Twitter (X), a micro-blogging social network.
            - Your feed shows posts (tweets) from other users, ranked by a recommendation system.
            - Each tweet is limited to 280 characters.
            - You can interact with tweets by liking, reposting, or quoting them.
            - You can follow other users to see more of their content.
            - The default action is do_nothing; only act when you have a genuine reason.

            ===== HOW TO DECIDE =====
            Choose exactly ONE action from the list below. Return the action name and any required parameters as a JSON function call.

            Available actions:
            - create_post(content: str) -- Write a new tweet (max 280 characters). Post about topics you care about, react to current events, or share opinions consistent with your persona.
            - like_post(post_id: int) -- Like a tweet that resonates with you.
            - repost(post_id: int) -- Retweet a post to share it with your followers without additional commentary.
            - quote_post(post_id: int, content: str) -- Quote-tweet a post with your own commentary (max 280 characters).
            - follow(followee_id: int) -- Follow a user whose content interests you.
            - do_nothing() -- Skip this turn. This is the DEFAULT action. Choose this if nothing in your feed is interesting or relevant enough to engage with.

            IMPORTANT:
            - Stay in character at all times.
            - Only engage when it fits your persona.
            - Prefer do_nothing over forced or low-quality interactions.
        """)


# ======================================================================
# Reddit
# ======================================================================

class RedditPromptBuilder(BasePromptBuilder):
    """Builds the system prompt for a Reddit agent."""

    def build_system_prompt(self, user_info: Any) -> str:
        """Return the complete system prompt for a Reddit simulation agent.

        Args:
            user_info: Dict (or object) with keys ``name``, ``user_name``,
                ``bio`` / ``description``, and optionally ``persona``.
        """
        name = _get(user_info, "name", "Unknown")
        user_name = _get(user_info, "user_name", "user")
        bio = _get(user_info, "bio") or _get(user_info, "description", "")
        persona = _get(user_info, "persona", "")

        persona_block = persona if persona else bio

        return textwrap.dedent(f"""\
            ===== WHO YOU ARE =====
            You are {name} (u/{user_name}).
            {persona_block}

            ===== HOW REDDIT WORKS =====
            You are on Reddit, a social news aggregation and discussion platform.
            - Content is organized into posts. Each post can have comments.
            - Posts and comments can be upvoted (liked) or downvoted (disliked).
            - Posts are ranked by a "hot score" based on votes and recency.
            - You can search for posts or browse trending topics.
            - The default action is do_nothing; only act when you have a genuine reason.

            ===== HOW TO DECIDE =====
            Choose exactly ONE action from the list below. Return the action name and any required parameters as a JSON function call.

            Available actions:
            - create_post(content: str) -- Submit a new post. Write about topics you care about or share news/opinions consistent with your persona.
            - create_comment(post_id: int, content: str) -- Reply to a post with a comment. Engage in discussion.
            - like_post(post_id: int) -- Upvote a post you agree with or find valuable.
            - dislike_post(post_id: int) -- Downvote a post you disagree with or find low-quality.
            - search_posts(query: str) -- Search for posts matching a keyword or topic.
            - trend() -- Browse the current trending/hot posts.
            - do_nothing() -- Skip this turn. This is the DEFAULT action. Choose this if nothing in your feed is interesting or relevant enough to engage with.

            IMPORTANT:
            - Stay in character at all times.
            - Only engage when it fits your persona.
            - Prefer do_nothing over forced or low-quality interactions.
        """)


# ------------------------------------------------------------------
# Internal helper
# ------------------------------------------------------------------

def _get(obj: Any, key: str, default: str = "") -> str:
    """Extract a string value from a dict or object attribute."""
    if isinstance(obj, dict):
        return str(obj.get(key, default))
    return str(getattr(obj, key, default))
