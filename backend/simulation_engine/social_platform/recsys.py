"""Recommendation system backends for the social-media simulation.

Four strategies are provided:

* **random** -- uniform-random post ordering (baseline).
* **reddit_hot_score** -- Reddit's classic "hot" ranking formula.
* **twitter** -- cosine-similarity via ``paraphrase-MiniLM-L6-v2``.
* **twhin** -- cosine-similarity via ``Twitter/twhin-bert-base``.

The two transformer-based backends lazily load their models once and
cache them at module level so subsequent calls are near-instant.  GPU
is used automatically when CUDA is available.

If ``sentence-transformers`` is not installed the transformer backends
fall back to ``random_recsys`` with a logged warning.
"""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Optional SentenceTransformer import
# ------------------------------------------------------------------

_SENTENCE_TRANSFORMERS_AVAILABLE = False
try:
    from sentence_transformers import SentenceTransformer

    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SentenceTransformer = None  # type: ignore[assignment,misc]

# ------------------------------------------------------------------
# Global model cache
# ------------------------------------------------------------------

_MODEL_CACHE: Dict[str, Any] = {}


def _get_device() -> str:
    """Return ``'cuda'`` if a GPU is available, else ``'cpu'``."""
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _get_model(model_name: str) -> Any:
    """Load (or retrieve from cache) a SentenceTransformer model."""
    if model_name not in _MODEL_CACHE:
        device = _get_device()
        logger.info("Loading SentenceTransformer '%s' on %s", model_name, device)
        _MODEL_CACHE[model_name] = SentenceTransformer(model_name, device=device)
    return _MODEL_CACHE[model_name]


# ------------------------------------------------------------------
# 1. Random recommendation
# ------------------------------------------------------------------

def random_recsys(
    agent_count: int,
    max_rec_post_len: int,
    all_posts: List[Dict[str, Any]],
) -> Dict[int, List[int]]:
    """Assign each agent a random sample of posts.

    Args:
        agent_count: Total number of agents (user ids ``0 .. agent_count-1``).
        max_rec_post_len: Maximum posts per user's feed.
        all_posts: List of post dicts (must contain ``"post_id"``).

    Returns:
        ``rec_matrix`` mapping ``user_id`` -> list of ``post_id``.
    """
    post_ids = [p["post_id"] for p in all_posts]
    rec_matrix: Dict[int, List[int]] = {}
    k = min(max_rec_post_len, len(post_ids))
    for uid in range(agent_count):
        rec_matrix[uid] = random.sample(post_ids, k) if k > 0 else []
    return rec_matrix


# ------------------------------------------------------------------
# 2. Reddit hot-score recommendation
# ------------------------------------------------------------------

_EPOCH = datetime(1970, 1, 1)


def _epoch_seconds(dt: datetime) -> float:
    """Seconds since Unix epoch for *dt*."""
    return (dt - _EPOCH).total_seconds()


def _hot_score(ups: int, downs: int, created_at: str) -> float:
    """Reddit-style hot score.

    Formula: ``sign(s) * log10(max(|s|, 1)) + epoch_seconds / 45000``
    where ``s = ups - downs``.
    """
    s = ups - downs
    sign = 1 if s > 0 else (-1 if s < 0 else 0)
    order = math.log10(max(abs(s), 1))
    try:
        dt = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        dt = datetime.utcnow()
    seconds = _epoch_seconds(dt)
    return sign * order + seconds / 45000.0


def reddit_hot_score_recsys(
    all_posts: List[Dict[str, Any]],
    max_rec_post_len: int,
) -> Dict[int, List[int]]:
    """Rank posts by Reddit hot-score and give every user the same feed.

    The returned ``rec_matrix`` maps every user that authored a post to
    the same top-N list.  Call ``random_recsys`` for users that never
    posted.

    Args:
        all_posts: Post dicts with ``post_id``, ``num_likes``,
            ``num_dislikes``, and ``created_at``.
        max_rec_post_len: Maximum posts per feed.

    Returns:
        ``rec_matrix`` mapping ``user_id`` -> list of ``post_id``.
    """
    if not all_posts:
        return {}

    scored = []
    for p in all_posts:
        score = _hot_score(
            ups=p.get("num_likes", 0),
            downs=p.get("num_dislikes", 0),
            created_at=p.get("created_at", ""),
        )
        scored.append((score, p["post_id"]))

    scored.sort(reverse=True)
    top_ids = [pid for _, pid in scored[:max_rec_post_len]]

    # Collect all user ids that appear in posts.
    user_ids = {p["user_id"] for p in all_posts}
    rec_matrix: Dict[int, List[int]] = {}
    for uid in user_ids:
        rec_matrix[uid] = list(top_ids)
    return rec_matrix


# ------------------------------------------------------------------
# 2b. Reddit subreddit-aware recommendation
# ------------------------------------------------------------------

def reddit_subreddit_recsys(
    all_posts: List[Dict[str, Any]],
    max_rec_post_len: int,
    db: Any,
    agent_count: int,
) -> Dict[int, List[int]]:
    """Subreddit-aware personalised feed for Reddit agents.

    Fills each user's feed in four stages:
      1. Followed-subreddit posts (50% of slots)
      2. Cross-promoted similar/new subreddits (15%)
      3. Popular discovery from unfollowed subreddits (20%)
      4. General posts with no subreddit (15%)

    Falls back to ``reddit_hot_score_recsys`` if no subreddits exist.

    Args:
        all_posts: Post dicts with ``post_id``, ``num_likes``,
            ``num_dislikes``, ``created_at``, and ``subreddit_id``.
        max_rec_post_len: Maximum posts per feed.
        db: Database instance for querying subreddit tables.
        agent_count: Total number of registered agents.

    Returns:
        ``rec_matrix`` mapping ``user_id`` -> list of ``post_id``.
    """
    if not all_posts:
        return {}

    # Check if subreddits exist at all.
    sub_count = db.fetchone("SELECT COUNT(*) as cnt FROM subreddit")
    if not sub_count or sub_count["cnt"] == 0:
        # No subreddits yet -- fall back to classic hot-score.
        matrix = reddit_hot_score_recsys(all_posts, max_rec_post_len)
        # Ensure all agents have an entry.
        all_post_ids = [p["post_id"] for p in all_posts][:max_rec_post_len]
        for uid in range(agent_count):
            if uid not in matrix:
                matrix[uid] = list(all_post_ids)
        return matrix

    # Pre-score all posts by hot score.
    post_scores: Dict[int, float] = {}
    for p in all_posts:
        post_scores[p["post_id"]] = _hot_score(
            ups=p.get("num_likes", 0),
            downs=p.get("num_dislikes", 0),
            created_at=p.get("created_at", ""),
        )

    # Index posts by subreddit_id.
    posts_by_sub: Dict[Optional[int], List[Dict[str, Any]]] = {}
    for p in all_posts:
        sid = p.get("subreddit_id")
        posts_by_sub.setdefault(sid, []).append(p)

    # Sort each bucket by hot score descending.
    for sid in posts_by_sub:
        posts_by_sub[sid].sort(key=lambda p: post_scores[p["post_id"]], reverse=True)

    # Fetch subreddit metadata for popularity weighting.
    sub_rows = db.fetchall("SELECT subreddit_id, num_followers, created_at FROM subreddit")
    sub_popularity: Dict[int, int] = {r["subreddit_id"]: r["num_followers"] for r in sub_rows}
    sub_created: Dict[int, str] = {r["subreddit_id"]: r["created_at"] or "" for r in sub_rows}

    # Slot allocation.
    n_followed = max(1, int(max_rec_post_len * 0.50))
    n_cross = max(1, int(max_rec_post_len * 0.15))
    n_popular = max(1, int(max_rec_post_len * 0.20))
    n_general = max(1, max_rec_post_len - n_followed - n_cross - n_popular)

    rec_matrix: Dict[int, List[int]] = {}

    for uid in range(agent_count):
        seen: set = set()
        feed: List[int] = []

        # --- Stage 1: Followed subreddits (50%) ---
        followed_rows = db.fetchall(
            "SELECT subreddit_id FROM subreddit_follow WHERE user_id = ?",
            (uid,),
        )
        followed_ids = {r["subreddit_id"] for r in followed_rows}

        if followed_ids:
            # Cap per-subreddit to enforce diversity.
            per_sub_cap = max(2, int(n_followed / len(followed_ids) * 1.5))
            remaining_slots = n_followed

            for sid in followed_ids:
                if remaining_slots <= 0:
                    break
                bucket = posts_by_sub.get(sid, [])
                added = 0
                for p in bucket:
                    if added >= per_sub_cap or remaining_slots <= 0:
                        break
                    pid = p["post_id"]
                    if pid not in seen:
                        feed.append(pid)
                        seen.add(pid)
                        added += 1
                        remaining_slots -= 1

        # --- Stage 2: Cross-promotion of similar subreddits (15%) ---
        if followed_ids:
            # Find subreddits similar to followed ones that the user doesn't follow.
            placeholders = ",".join("?" for _ in followed_ids)
            similar_rows = db.fetchall(
                f"SELECT DISTINCT similar_subreddit_id FROM subreddit_similarity "
                f"WHERE subreddit_id IN ({placeholders})",
                tuple(followed_ids),
            )
            similar_ids = {r["similar_subreddit_id"] for r in similar_rows} - followed_ids

            # Score by cold-start boost: fewer followers + newer = higher priority.
            def _cross_promo_score(sid: int) -> float:
                pop = sub_popularity.get(sid, 0)
                # Newer subs get a boost: use created_at epoch.
                try:
                    dt = datetime.fromisoformat(sub_created.get(sid, ""))
                    age_seconds = max(1, (datetime.utcnow() - dt).total_seconds())
                except (ValueError, TypeError):
                    age_seconds = 86400 * 30  # default 30 days
                # Lower followers + newer = higher score.
                return 1.0 / (1 + pop) + 3600.0 / age_seconds

            ranked_similar = sorted(similar_ids, key=_cross_promo_score, reverse=True)
            remaining = n_cross
            for sid in ranked_similar:
                if remaining <= 0:
                    break
                for p in posts_by_sub.get(sid, []):
                    if remaining <= 0:
                        break
                    pid = p["post_id"]
                    if pid not in seen:
                        feed.append(pid)
                        seen.add(pid)
                        remaining -= 1

        # --- Stage 3: Popular discovery from unfollowed subreddits (20%) ---
        unfollowed_subs = [
            sid for sid in sub_popularity
            if sid not in followed_ids and sid is not None
        ]
        # Weight by popularity.
        unfollowed_subs.sort(key=lambda sid: sub_popularity.get(sid, 0), reverse=True)
        remaining = n_popular
        for sid in unfollowed_subs:
            if remaining <= 0:
                break
            for p in posts_by_sub.get(sid, []):
                if remaining <= 0:
                    break
                pid = p["post_id"]
                if pid not in seen:
                    feed.append(pid)
                    seen.add(pid)
                    remaining -= 1

        # --- Stage 4: General posts (no subreddit) (15%) ---
        general_posts = posts_by_sub.get(None, [])
        remaining = n_general
        for p in general_posts:
            if remaining <= 0:
                break
            pid = p["post_id"]
            if pid not in seen:
                feed.append(pid)
                seen.add(pid)
                remaining -= 1

        # If any stage under-filled, backfill from all posts by hot score.
        if len(feed) < max_rec_post_len:
            all_sorted = sorted(all_posts, key=lambda p: post_scores[p["post_id"]], reverse=True)
            for p in all_sorted:
                if len(feed) >= max_rec_post_len:
                    break
                pid = p["post_id"]
                if pid not in seen:
                    feed.append(pid)
                    seen.add(pid)

        rec_matrix[uid] = feed[:max_rec_post_len]

    return rec_matrix


# ------------------------------------------------------------------
# 3. Twitter recsys (paraphrase-MiniLM-L6-v2)
# ------------------------------------------------------------------

def twitter_recsys(
    user_profiles: List[Dict[str, Any]],
    all_posts: List[Dict[str, Any]],
    max_rec_post_len: int,
) -> Dict[int, List[int]]:
    """Personalised feed via cosine similarity using MiniLM embeddings.

    Falls back to ``random_recsys`` if ``sentence-transformers`` is not
    installed.

    Args:
        user_profiles: One dict per user with ``"name"``, ``"bio"``,
            and optionally ``"recent_posts"``.
        all_posts: Post dicts with ``"post_id"`` and ``"content"``.
        max_rec_post_len: Maximum posts per user's feed.

    Returns:
        ``rec_matrix`` mapping ``user_id`` -> list of ``post_id``.
    """
    if not _SENTENCE_TRANSFORMERS_AVAILABLE:
        logger.warning(
            "sentence-transformers not installed; falling back to random recsys"
        )
        return random_recsys(len(user_profiles), max_rec_post_len, all_posts)

    return _transformer_recsys(
        model_name="paraphrase-MiniLM-L6-v2",
        user_profiles=user_profiles,
        all_posts=all_posts,
        max_rec_post_len=max_rec_post_len,
    )


# ------------------------------------------------------------------
# 4. TwHIN-BERT recsys (Twitter/twhin-bert-base)
# ------------------------------------------------------------------

def twhin_recsys(
    user_profiles: List[Dict[str, Any]],
    all_posts: List[Dict[str, Any]],
    max_rec_post_len: int,
) -> Dict[int, List[int]]:
    """Personalised feed via cosine similarity using TwHIN-BERT embeddings.

    Falls back to ``random_recsys`` if ``sentence-transformers`` is not
    installed.

    Args:
        user_profiles: One dict per user.
        all_posts: Post dicts.
        max_rec_post_len: Maximum posts per user's feed.

    Returns:
        ``rec_matrix`` mapping ``user_id`` -> list of ``post_id``.
    """
    if not _SENTENCE_TRANSFORMERS_AVAILABLE:
        logger.warning(
            "sentence-transformers not installed; falling back to random recsys"
        )
        return random_recsys(len(user_profiles), max_rec_post_len, all_posts)

    return _transformer_recsys(
        model_name="Twitter/twhin-bert-base",
        user_profiles=user_profiles,
        all_posts=all_posts,
        max_rec_post_len=max_rec_post_len,
    )


# ------------------------------------------------------------------
# Shared transformer-based implementation
# ------------------------------------------------------------------

def _transformer_recsys(
    model_name: str,
    user_profiles: List[Dict[str, Any]],
    all_posts: List[Dict[str, Any]],
    max_rec_post_len: int,
) -> Dict[int, List[int]]:
    """Core implementation shared by twitter_recsys and twhin_recsys."""
    from simulation_engine.social_platform.process_recsys_posts import (
        build_rec_matrix_from_scores,
        compute_similarity_matrix,
        encode_texts,
        posts_to_texts,
        user_profiles_to_texts,
    )

    if not all_posts:
        return {uid: [] for uid in range(len(user_profiles))}

    model = _get_model(model_name)

    # Vectorize users and posts.
    user_texts = user_profiles_to_texts(user_profiles)
    post_texts = posts_to_texts(all_posts)

    user_embeddings = encode_texts(model, user_texts)
    post_embeddings = encode_texts(model, post_texts)

    # Compute similarity and build recommendation lists.
    scores = compute_similarity_matrix(user_embeddings, post_embeddings)
    post_ids = [p["post_id"] for p in all_posts]

    return build_rec_matrix_from_scores(scores, post_ids, max_rec_post_len)
