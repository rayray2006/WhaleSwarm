"""Utility helpers for the social-media platform layer.

Formatting, truncation, and display helpers used by ``Platform`` and
environment renderers.
"""

from __future__ import annotations

import textwrap
from datetime import datetime
from typing import Any, Dict, List, Optional


# ------------------------------------------------------------------
# Content helpers
# ------------------------------------------------------------------

def truncate(text: str, max_length: int = 280) -> str:
    """Truncate *text* to *max_length* characters, appending '...' if cut."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def sanitize_content(text: str) -> str:
    """Strip leading/trailing whitespace and collapse internal runs of
    whitespace to a single space.
    """
    return " ".join(text.split())


# ------------------------------------------------------------------
# Post / comment formatting
# ------------------------------------------------------------------

def format_post(
    post_id: int,
    user_name: str,
    content: str,
    created_at: str,
    num_likes: int = 0,
    num_dislikes: int = 0,
    *,
    max_content_len: int = 0,
) -> str:
    """Return a human-readable single-line summary of a post.

    If *max_content_len* > 0 the content body is truncated.
    """
    body = truncate(content, max_content_len) if max_content_len > 0 else content
    parts = [
        f"[Post {post_id}]",
        f"@{user_name}:",
        f'"{body}"',
        f"({num_likes} likes, {num_dislikes} dislikes)",
        f"at {created_at}",
    ]
    return " ".join(parts)


def format_comment(
    comment_id: int,
    post_id: int,
    user_name: str,
    content: str,
    created_at: str,
    *,
    max_content_len: int = 0,
) -> str:
    """Return a human-readable single-line summary of a comment."""
    body = truncate(content, max_content_len) if max_content_len > 0 else content
    return (
        f"[Comment {comment_id} on Post {post_id}] "
        f"@{user_name}: \"{body}\" at {created_at}"
    )


def format_user(
    user_id: int,
    user_name: str,
    name: str,
    bio: str,
    num_followers: int = 0,
    num_followings: int = 0,
) -> str:
    """Return a human-readable user summary."""
    return (
        f"@{user_name} ({name}) - {bio} "
        f"[{num_followers} followers, {num_followings} following]"
    )


# ------------------------------------------------------------------
# Feed rendering
# ------------------------------------------------------------------

def render_feed(posts: List[Dict[str, Any]], *, max_content_len: int = 0) -> str:
    """Render a list of post dicts into a multi-line feed string."""
    if not posts:
        return "(empty feed)"
    lines = []
    for p in posts:
        lines.append(
            format_post(
                post_id=p["post_id"],
                user_name=p.get("user_name", "unknown"),
                content=p.get("content", ""),
                created_at=p.get("created_at", ""),
                num_likes=p.get("num_likes", 0),
                num_dislikes=p.get("num_dislikes", 0),
                max_content_len=max_content_len,
            )
        )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Timestamp helper
# ------------------------------------------------------------------

def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.utcnow().isoformat(timespec="seconds")
