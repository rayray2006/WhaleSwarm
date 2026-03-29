"""Agent-side action interface for Twitter and Reddit platforms.

Defines the public async methods that agents can call on social-media
platforms.  Each method sends a message through the Channel to the
platform server.

Tool definitions are auto-generated from these method signatures and
docstrings by BaseAction.get_openai_function_list().
"""

from __future__ import annotations

from typing import Any, Dict

from simulation_engine.simulations.base import BaseAction
from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.typing import ActionType


class TwitterAction(BaseAction):
    """Agent-side Twitter action interface."""

    def __init__(self, agent_id: int, channel: Channel) -> None:
        super().__init__(agent_id, channel)

    async def create_post(self, content: str) -> Dict[str, Any]:
        """Write a new tweet (max 280 characters).

        content: The text of your tweet.
        """
        return await self.perform_action(
            {"content": content},
            ActionType.CREATE_POST,
        )

    async def like_post(self, post_id: int) -> Dict[str, Any]:
        """Like a tweet that resonates with you.

        post_id: The ID of the tweet to like.
        """
        return await self.perform_action(
            {"post_id": post_id},
            ActionType.LIKE_POST,
        )

    async def repost(self, post_id: int) -> Dict[str, Any]:
        """Retweet a post to share it with your followers.

        post_id: The ID of the tweet to retweet.
        """
        return await self.perform_action(
            {"post_id": post_id},
            ActionType.REPOST,
        )

    async def quote_post(self, post_id: int, content: str) -> Dict[str, Any]:
        """Quote-tweet a post with your own commentary.

        post_id: The ID of the tweet to quote.
        content: Your commentary text (max 280 characters).
        """
        return await self.perform_action(
            {"post_id": post_id, "content": content},
            ActionType.QUOTE_POST,
        )

    async def follow(self, followee_id: int) -> Dict[str, Any]:
        """Follow a user whose content interests you.

        followee_id: The user ID of the person to follow.
        """
        return await self.perform_action(
            {"followee_id": followee_id},
            ActionType.FOLLOW,
        )

    async def do_nothing(self) -> Dict[str, Any]:
        """Skip this turn and take no action."""
        return await self.perform_action({}, ActionType.DO_NOTHING)


class RedditAction(BaseAction):
    """Agent-side Reddit action interface."""

    def __init__(self, agent_id: int, channel: Channel) -> None:
        super().__init__(agent_id, channel)

    async def create_post(self, content: str, subreddit_name: str = "") -> Dict[str, Any]:
        """Submit a new post to a subreddit.

        content: The text of your post.
        subreddit_name: The subreddit to post in (e.g. "technology"). Leave empty for the general feed.
        """
        return await self.perform_action(
            {"content": content, "subreddit_name": subreddit_name},
            ActionType.CREATE_POST,
        )

    async def create_comment(self, post_id: int, content: str) -> Dict[str, Any]:
        """Reply to a post with a comment.

        post_id: The ID of the post to comment on.
        content: Your comment text.
        """
        return await self.perform_action(
            {"post_id": post_id, "content": content},
            ActionType.CREATE_COMMENT,
        )

    async def like_post(self, post_id: int) -> Dict[str, Any]:
        """Upvote a post you agree with or find valuable.

        post_id: The ID of the post to upvote.
        """
        return await self.perform_action(
            {"post_id": post_id},
            ActionType.LIKE_POST,
        )

    async def dislike_post(self, post_id: int) -> Dict[str, Any]:
        """Downvote a post you disagree with or find low-quality.

        post_id: The ID of the post to downvote.
        """
        return await self.perform_action(
            {"post_id": post_id},
            ActionType.DISLIKE_POST,
        )

    async def search_posts(self, query: str) -> Dict[str, Any]:
        """Search for posts matching a keyword or topic.

        query: The search query string.
        """
        return await self.perform_action(
            {"query": query},
            ActionType.SEARCH_POSTS,
        )

    async def trend(self) -> Dict[str, Any]:
        """Browse the current trending/hot posts."""
        return await self.perform_action({}, ActionType.TREND)

    async def create_subreddit(self, name: str, description: str = "", similar_to: str = "") -> Dict[str, Any]:
        """Create a new subreddit community. Only do this if no existing subreddit fits your topic.

        name: The subreddit name (e.g. "technology", "cooking"). No spaces, lowercase.
        description: A short description of what the subreddit is about.
        similar_to: Comma-separated names of existing similar subreddits for cross-promotion (e.g. "programming,webdev").
        """
        similar_list = [s.strip() for s in similar_to.split(",") if s.strip()] if similar_to else []
        return await self.perform_action(
            {"name": name, "description": description, "similar_to": similar_list},
            ActionType.CREATE_SUBREDDIT,
        )

    async def follow_subreddit(self, subreddit_name: str) -> Dict[str, Any]:
        """Join a subreddit to see its posts in your feed.

        subreddit_name: The name of the subreddit to follow (e.g. "technology").
        """
        return await self.perform_action(
            {"subreddit_name": subreddit_name},
            ActionType.FOLLOW_SUBREDDIT,
        )

    async def unfollow_subreddit(self, subreddit_name: str) -> Dict[str, Any]:
        """Leave a subreddit you no longer want in your feed.

        subreddit_name: The name of the subreddit to unfollow.
        """
        return await self.perform_action(
            {"subreddit_name": subreddit_name},
            ActionType.UNFOLLOW_SUBREDDIT,
        )

    async def browse_subreddit(self, subreddit_name: str = "") -> Dict[str, Any]:
        """Browse posts in a specific subreddit, or browse your home feed across all subreddits you follow.

        subreddit_name: The subreddit to browse (e.g. "technology"). Leave empty to browse your combined home feed.
        """
        return await self.perform_action(
            {"subreddit_name": subreddit_name},
            ActionType.BROWSE_SUBREDDIT,
        )

    async def do_nothing(self) -> Dict[str, Any]:
        """Skip this turn and take no action."""
        return await self.perform_action({}, ActionType.DO_NOTHING)
