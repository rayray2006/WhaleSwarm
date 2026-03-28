"""Heuristic belief-state system for simulation agents.

Each agent maintains a ``BeliefState`` that tracks evolving opinions
across simulation rounds using cheap keyword heuristics (no LLM calls).
See PRD section 11 for the full design rationale.
"""

import hashlib
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ======================================================================
# Constants
# ======================================================================

MAX_EXPOSURE_HISTORY = 2000
_EVICT_COUNT = 500

# ------------------------------------------------------------------
# Stance-estimation keyword lists
# ------------------------------------------------------------------

_PRIMARY_POSITIVE = {
    "support", "agree", "great", "excellent", "beneficial", "important",
    "necessary", "progress", "opportunity", "innovative", "promising",
    "approve", "endorse", "welcome", "positive", "good news", "well done",
    "proud", "celebrate", "achievement",
}

_PRIMARY_NEGATIVE = {
    "oppose", "disagree", "terrible", "harmful", "dangerous", "threat",
    "unacceptable", "disastrous", "catastrophe", "fail", "wrong",
    "corrupt", "scandal", "outrage", "incompetent", "reckless", "protest",
    "condemn", "reject", "concerned", "worried",
}

_BROAD_POSITIVE = {
    "love", "like", "happy", "hope", "excited", "better", "best",
    "awesome", "amazing", "cool", "nice", "interesting", "helpful",
    "thank", "thanks", "appreciate", "win", "success", "improve",
    "trust", "confident", "optimis", "encourage", "empower", "brilliant",
    "fantastic", "incredible", "wonderful", "recommend", "favor",
    "advantage", "benefit", "gain",
}

_BROAD_NEGATIVE = {
    "hate", "bad", "sad", "fear", "angry", "worse", "worst", "awful",
    "horrible", "stupid", "ugly", "annoying", "disappoint", "frustrat",
    "problem", "issue", "risk", "lose", "loss", "damage", "distrust",
    "pessimis", "discourage", "alarm", "ridiculous", "absurd", "pathetic",
    "disaster", "blame", "against", "unfair", "disadvantage", "cost",
}

# ------------------------------------------------------------------
# Stance-from-config mapping
# ------------------------------------------------------------------

_STANCE_MAP: Dict[str, float] = {
    "supportive": 0.6,
    "strongly_supportive": 0.9,
    "opposing": -0.6,
    "strongly_opposing": -0.9,
    "neutral": 0.0,
    "observer": 0.0,
}

# Trust adjustment deltas
_TRUST_ADJUSTMENTS: Dict[str, float] = {
    "like": 0.05,
    "dislike": -0.05,
    "follow": 0.10,
    "unfollow": -0.10,
    "mute": -0.20,
}


# ======================================================================
# Helper functions
# ======================================================================

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _content_hash(content: str) -> str:
    """Return the first 12 hex chars of the MD5 of *content*."""
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]


def _estimate_stance(content: str) -> float:
    """Estimate the stance of *content* using keyword heuristics.

    Returns a float in ``[-1.0, 1.0]``.  ``0.0`` is the fallback for
    content that matches neither positive nor negative keywords.
    """
    if not content:
        return 0.0

    lower = content.lower()

    # Primary signals.
    pos_primary = sum(1 for kw in _PRIMARY_POSITIVE if kw in lower)
    neg_primary = sum(1 for kw in _PRIMARY_NEGATIVE if kw in lower)

    if pos_primary or neg_primary:
        total = pos_primary + neg_primary
        score = (pos_primary - neg_primary) / total
        return _clamp(score, -1.0, 1.0)

    # Broad fallback (attenuated by 0.6x).
    pos_broad = sum(1 for kw in _BROAD_POSITIVE if kw in lower)
    neg_broad = sum(1 for kw in _BROAD_NEGATIVE if kw in lower)

    if pos_broad or neg_broad:
        total = pos_broad + neg_broad
        score = (pos_broad - neg_broad) / total * 0.6
        return _clamp(score, -1.0, 1.0)

    # Final fallback: mild neutral.
    return 0.0


def _content_relates_to_topic(content: str, topic: str) -> bool:
    """Check whether *content* is relevant to *topic*.

    Uses a deliberately low bar: direct substring match OR word-level
    overlap (any keyword from the topic found in the content).
    """
    if not content or not topic:
        return False

    lower_content = content.lower()
    lower_topic = topic.lower()

    # Direct substring match.
    if lower_topic in lower_content:
        return True

    # Word-level overlap: any single keyword from the topic in the content.
    topic_words = set(re.findall(r"\w+", lower_topic))
    # Filter out very short / stop words.
    topic_words = {w for w in topic_words if len(w) > 2}
    if not topic_words:
        return False

    content_words = set(re.findall(r"\w+", lower_content))
    return bool(topic_words & content_words)


def extract_topics_from_requirement(
    requirement: str,
    llm_client: Any = None,
) -> List[str]:
    """Extract 2-4 debate topics from a simulation requirement string.

    If an ``llm_client`` is provided, uses the LLM.  Otherwise falls back
    to a regex heuristic that splits on common delimiters and returns
    up to 4 noun-phrase-like chunks.

    Args:
        requirement: Free-text simulation requirement / scenario description.
        llm_client: Optional ``LLMClient`` for higher-quality extraction.

    Returns:
        A list of 2-4 topic strings.
    """
    if llm_client is not None:
        try:
            return _extract_topics_via_llm(requirement, llm_client)
        except Exception:
            logger.warning(
                "LLM topic extraction failed; falling back to regex",
                exc_info=True,
            )

    return _extract_topics_regex(requirement)


def _extract_topics_via_llm(requirement: str, llm_client: Any) -> List[str]:
    """Use the LLM to extract debate topics."""
    import json as _json

    prompt = (
        "Extract 2-4 distinct debate topics from the following simulation "
        "requirement. Return ONLY a JSON array of short topic strings "
        "(each 2-6 words). No explanation.\n\n"
        f"Requirement:\n{requirement}"
    )
    raw = llm_client.complete(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=256,
    )
    # Strip markdown fences if present.
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        raw = "\n".join(lines)
    topics = _json.loads(raw)
    if isinstance(topics, list) and 2 <= len(topics) <= 6:
        return [str(t).strip() for t in topics[:4]]
    raise ValueError(f"Unexpected LLM output: {topics!r}")


def _extract_topics_regex(requirement: str) -> List[str]:
    """Regex fallback for topic extraction.

    Splits on common delimiters and returns up to 4 chunks.
    """
    # Try bullet / numbered lists first.
    bullets = re.findall(r"(?:^|\n)\s*[\-\*\d]+[.)]\s*(.+)", requirement)
    if len(bullets) >= 2:
        return [b.strip().rstrip(".") for b in bullets[:4]]

    # Split on commas / semicolons / "and" / "vs".
    parts = re.split(r"[,;]|\band\b|\bvs\.?\b|\bversus\b", requirement, flags=re.IGNORECASE)
    parts = [p.strip().rstrip(".") for p in parts if len(p.strip()) > 5]
    if len(parts) >= 2:
        return parts[:4]

    # Last resort: split on sentences and take first 3.
    sentences = re.split(r"[.!?]+", requirement)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if sentences:
        return sentences[:3]

    return [requirement.strip()[:80]]


# ======================================================================
# BeliefState dataclass
# ======================================================================

@dataclass
class BeliefState:
    """Tracks an agent's evolving opinions across simulation rounds.

    All updates are heuristic (no LLM calls).

    Attributes:
        positions: Mapping of topic string to stance ``[-1.0, 1.0]``.
        confidence: Mapping of topic string to certainty ``[0.0, 1.0]``.
        trust: Mapping of ``agent_id`` to trust level ``[0.0, 1.0]``.
        exposure_history: Set of MD5 hashes (first 12 hex chars) of
            content the agent has seen — used for novelty detection.
    """

    positions: Dict[str, float] = field(default_factory=dict)
    confidence: Dict[str, float] = field(default_factory=dict)
    trust: Dict[int, float] = field(default_factory=dict)
    exposure_history: Set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Construction from agent config
    # ------------------------------------------------------------------

    @classmethod
    def from_profile(
        cls,
        agent_config: Dict[str, Any],
        topics: List[str],
    ) -> "BeliefState":
        """Initialise a BeliefState from an agent's activity config.

        Args:
            agent_config: Dict with keys ``stance`` (str) and optionally
                ``sentiment_bias`` (float).
            topics: The debate topics extracted from the simulation
                requirement.

        Returns:
            A new ``BeliefState`` with per-topic positions and confidences.
        """
        stance_str = str(agent_config.get("stance", "neutral")).lower()
        sentiment_bias = float(agent_config.get("sentiment_bias", 0.0))

        base_position = _STANCE_MAP.get(stance_str, 0.0)
        base_confidence = _clamp(0.4 + abs(sentiment_bias) * 0.4, 0.1, 1.0)

        positions: Dict[str, float] = {}
        confidences: Dict[str, float] = {}

        for topic in topics:
            # Gaussian noise so identical-stance agents still diverge.
            pos_noise = random.gauss(0, 0.15)
            conf_noise = random.gauss(0, 0.05)
            positions[topic] = _clamp(base_position + pos_noise, -1.0, 1.0)
            confidences[topic] = _clamp(base_confidence + conf_noise, 0.1, 1.0)

        return cls(
            positions=positions,
            confidence=confidences,
            trust={},
            exposure_history=set(),
        )

    # ------------------------------------------------------------------
    # Round update
    # ------------------------------------------------------------------

    def update_from_round(
        self,
        posts_seen: List[Dict[str, Any]],
        own_engagement: Dict[str, Any],
        round_num: int,
    ) -> None:
        """Update beliefs based on one round of activity.

        Args:
            posts_seen: List of post dicts, each with at least ``content``
                (str), ``author_id`` (int), and ``num_likes`` (int).
            own_engagement: Dict with ``likes_received`` and
                ``dislikes_received`` counts for the agent's own posts
                this round.
            round_num: Current round number (unused for now but available
                for future decay logic).
        """
        # --- Exposure / opinion updates from posts seen ---
        for post in posts_seen:
            content = str(post.get("content", ""))
            if not content:
                continue

            chash = _content_hash(content)
            is_novel = chash not in self.exposure_history
            self.exposure_history.add(chash)

            # Evict oldest entries when the set grows too large.
            # Sets in Python 3.7+ maintain insertion order in CPython,
            # but this is not guaranteed.  We convert to list, trim, re-set.
            if len(self.exposure_history) > MAX_EXPOSURE_HISTORY:
                as_list = list(self.exposure_history)
                self.exposure_history = set(as_list[_EVICT_COUNT:])

            post_stance = _estimate_stance(content)
            author_id = post.get("author_id")
            author_trust = self.trust.get(author_id, 0.5) if author_id is not None else 0.5
            num_likes = int(post.get("num_likes", 0))
            social_weight = min(1.0, 0.3 + num_likes * 0.07)
            novelty_mult = 1.5 if is_novel else 0.5

            for topic in list(self.positions.keys()):
                if not _content_relates_to_topic(content, topic):
                    continue

                current_pos = self.positions[topic]
                current_conf = self.confidence[topic]
                resistance = 0.3 + current_conf * 0.7  # 0.3 to 1.0

                nudge = (
                    (post_stance - current_pos)
                    * author_trust
                    * social_weight
                    * novelty_mult
                    * 0.08  # base learning rate
                    / resistance
                )

                self.positions[topic] = _clamp(current_pos + nudge, -1.0, 1.0)

        # --- Social reinforcement from own engagement ---
        likes = int(own_engagement.get("likes_received", 0))
        dislikes = int(own_engagement.get("dislikes_received", 0))

        if likes > dislikes:
            boost = min(0.15, (likes - dislikes) * 0.03)
            for topic in self.confidence:
                self.confidence[topic] = _clamp(
                    self.confidence[topic] + boost, 0.0, 1.0,
                )
        elif dislikes > likes:
            drop = min(0.15, (dislikes - likes) * 0.03)
            for topic in self.confidence:
                self.confidence[topic] = _clamp(
                    self.confidence[topic] - drop, 0.0, 1.0,
                )

    # ------------------------------------------------------------------
    # Trust updates
    # ------------------------------------------------------------------

    def update_trust(self, other_agent_id: int, action: str) -> None:
        """Adjust trust toward *other_agent_id* based on a social action.

        Supported *action* values: ``"like"``, ``"dislike"``, ``"follow"``,
        ``"unfollow"``, ``"mute"``.
        """
        delta = _TRUST_ADJUSTMENTS.get(action.lower(), 0.0)
        if delta == 0.0:
            return
        current = self.trust.get(other_agent_id, 0.5)
        self.trust[other_agent_id] = _clamp(current + delta, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Prompt generation
    # ------------------------------------------------------------------

    def to_prompt_text(self) -> str:
        """Generate a text block for injection into the agent's system prompt.

        Returns:
            Multi-line string describing the agent's current beliefs,
            confidence levels, and most-trusted / least-trusted peers.
        """
        lines = [
            "# YOUR CURRENT BELIEFS AND STANCE",
            "These reflect your evolving understanding based on what you have "
            "seen and experienced in the simulation so far.",
            "",
        ]

        for topic, position in self.positions.items():
            conf = self.confidence.get(topic, 0.5)
            stance_label = _position_to_label(position)
            conf_label = _confidence_to_label(conf)
            lines.append(
                f"- On **{topic}**: You are {stance_label} "
                f"(confidence: {conf_label})"
            )

        # Top-5 trusted agents.
        if self.trust:
            sorted_trust = sorted(
                self.trust.items(), key=lambda kv: kv[1], reverse=True,
            )
            trusted = [(aid, t) for aid, t in sorted_trust[:5] if t > 0.6]
            distrusted = [(aid, t) for aid, t in sorted_trust[-5:] if t < 0.4]

            if trusted:
                lines.append("")
                lines.append("**People you tend to trust:**")
                for aid, t in trusted:
                    lines.append(f"  - Agent {aid} (trust: {t:.2f})")

            if distrusted:
                lines.append("")
                lines.append("**People you are skeptical of:**")
                for aid, t in distrusted:
                    lines.append(f"  - Agent {aid} (trust: {t:.2f})")

        return "\n".join(lines)


# ======================================================================
# Label helpers
# ======================================================================

def _position_to_label(position: float) -> str:
    if position >= 0.7:
        return "strongly supportive"
    if position >= 0.3:
        return "supportive"
    if position >= 0.1:
        return "leaning supportive"
    if position > -0.1:
        return "neutral"
    if position > -0.3:
        return "leaning opposed"
    if position > -0.7:
        return "opposed"
    return "strongly opposed"


def _confidence_to_label(confidence: float) -> str:
    if confidence >= 0.8:
        return "very high"
    if confidence >= 0.6:
        return "high"
    if confidence >= 0.4:
        return "moderate"
    if confidence >= 0.2:
        return "low"
    return "very low"
