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
