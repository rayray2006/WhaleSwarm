"""Post and user-profile vectorization for recommendation systems.

Provides helpers that convert raw post rows and user profile dicts into
dense vector representations via SentenceTransformer models, which are
then consumed by ``recsys.twitter_recsys`` and ``recsys.twhin_recsys``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Vectorization helpers
# ------------------------------------------------------------------

def posts_to_texts(posts: Sequence[Dict[str, Any]]) -> List[str]:
    """Extract the text content from a sequence of post dicts.

    Each post dict is expected to have at least a ``"content"`` key.
    Missing or empty content is replaced with a single space so every
    post maps to exactly one string.
    """
    return [p.get("content", " ") or " " for p in posts]


def user_profiles_to_texts(user_profiles: Sequence[Dict[str, Any]]) -> List[str]:
    """Build a textual representation of each user profile for embedding.

    Concatenates the user's ``name``, ``bio``, and (optionally) recent
    post content into a single string per user.

    Args:
        user_profiles: Each dict should contain at minimum ``"name"``
            and ``"bio"`` keys.  An optional ``"recent_posts"`` key
            (list of strings) is appended if present.

    Returns:
        A list of strings, one per user, suitable for encoding with a
        SentenceTransformer model.
    """
    texts: List[str] = []
    for profile in user_profiles:
        parts = [
            profile.get("name", ""),
            profile.get("bio", ""),
        ]
        recent = profile.get("recent_posts")
        if recent:
            parts.extend(recent[:5])  # cap to avoid excessively long inputs
        texts.append(" ".join(p for p in parts if p))
    return texts


def encode_texts(
    model: Any,
    texts: List[str],
    batch_size: int = 64,
    normalize: bool = True,
) -> "np.ndarray":
    """Encode a list of strings into a 2-D numpy array of embeddings.

    Args:
        model: A loaded ``SentenceTransformer`` instance.
        texts: Strings to encode.
        batch_size: Encoding batch size.
        normalize: If ``True`` (default), L2-normalise each vector so
            cosine similarity reduces to a dot product.

    Returns:
        ``np.ndarray`` of shape ``(len(texts), dim)``.
    """
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    if normalize:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        embeddings = embeddings / norms
    return embeddings


def compute_similarity_matrix(
    user_embeddings: "np.ndarray",
    post_embeddings: "np.ndarray",
) -> "np.ndarray":
    """Compute cosine-similarity scores between users and posts.

    Both inputs are assumed to be L2-normalised so the dot product
    equals cosine similarity.

    Args:
        user_embeddings: Shape ``(n_users, dim)``.
        post_embeddings: Shape ``(n_posts, dim)``.

    Returns:
        ``np.ndarray`` of shape ``(n_users, n_posts)`` with similarity
        scores in ``[-1, 1]``.
    """
    return user_embeddings @ post_embeddings.T


def build_rec_matrix_from_scores(
    scores: "np.ndarray",
    post_ids: List[int],
    max_rec_post_len: int,
) -> Dict[int, List[int]]:
    """Convert a user-post score matrix into a recommendation matrix.

    For each user (row), selects the top-*max_rec_post_len* posts by
    descending score.

    Args:
        scores: Shape ``(n_users, n_posts)``.
        post_ids: Mapping from column index to ``post_id``.
        max_rec_post_len: Maximum recommended posts per user.

    Returns:
        Dict mapping ``user_id`` (0-indexed) to a list of ``post_id``
        values.
    """
    rec_matrix: Dict[int, List[int]] = {}
    n_users = scores.shape[0]
    k = min(max_rec_post_len, len(post_ids))

    for uid in range(n_users):
        top_indices = np.argsort(scores[uid])[::-1][:k]
        rec_matrix[uid] = [post_ids[int(idx)] for idx in top_indices]

    return rec_matrix
