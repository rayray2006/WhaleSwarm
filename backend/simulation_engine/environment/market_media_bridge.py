"""Bidirectional bridge between social media sentiment and prediction markets.

Aggregates social-media belief states into sentiment snapshots that
Polymarket agents see, and formats market price data for social-media
agents.  Maintains history for delta tracking.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MarketSnapshot:
    round_num: int = 0
    question: str = ""
    yes_price: float = 0.5
    no_price: float = 0.5
    trade_count: int = 0
    price_delta: float = 0.0
    mood: str = "neutral"


@dataclass
class SentimentSnapshot:
    round_num: int = 0
    platform: str = ""
    bullish_pct: float = 0.0
    bearish_pct: float = 0.0
    neutral_pct: float = 0.0
    post_count: int = 0
    dominant_mood: str = "neutral"
    hot_takes: List[str] = field(default_factory=list)


class MarketMediaBridge:
    """Manages the two-way data flow between markets and social platforms."""

    def __init__(self) -> None:
        self._market_history: List[MarketSnapshot] = []
        self._sentiment_history: Dict[str, List[SentimentSnapshot]] = {}

    @property
    def latest_market(self) -> Optional[MarketSnapshot]:
        return self._market_history[-1] if self._market_history else None

    def update_prices(self, db: Any, round_num: int) -> Optional[MarketSnapshot]:
        markets = db.fetchall(
            "SELECT market_id, question, reserve_a, reserve_b FROM market WHERE resolved = 0"
        )
        if not markets:
            return None

        m = markets[0]
        total = (m["reserve_a"] or 0) + (m["reserve_b"] or 0)
        yes_price = m["reserve_b"] / total if total > 0 else 0.5

        trade_row = db.fetchone(
            "SELECT COUNT(*) AS cnt FROM trade WHERE market_id = ?",
            (m["market_id"],),
        )
        trade_count = trade_row["cnt"] if trade_row else 0

        prev = self._market_history[-1].yes_price if self._market_history else 0.5
        delta = yes_price - prev

        if delta > 0.02:
            mood = "bullish"
        elif delta < -0.02:
            mood = "bearish"
        else:
            mood = "stable"

        snap = MarketSnapshot(
            round_num=round_num,
            question=m["question"],
            yes_price=round(yes_price, 4),
            no_price=round(1 - yes_price, 4),
            trade_count=trade_count,
            price_delta=round(delta, 4),
            mood=mood,
        )
        self._market_history.append(snap)
        return snap

    def update_sentiment(
        self,
        belief_states: Dict[int, Any],
        platform: str,
        round_num: int,
        recent_posts: List[Dict] = None,
    ) -> SentimentSnapshot:
        bullish = bearish = neutral = 0
        for bs in belief_states.values():
            positions = getattr(bs, "positions", {})
            if not positions:
                neutral += 1
                continue
            avg = sum(positions.values()) / len(positions) if positions else 0
            if avg > 0.15:
                bullish += 1
            elif avg < -0.15:
                bearish += 1
            else:
                neutral += 1

        total = bullish + bearish + neutral or 1

        hot_takes = []
        if recent_posts:
            sorted_posts = sorted(
                recent_posts,
                key=lambda p: (p.get("num_likes", 0) or 0),
                reverse=True,
            )
            for p in sorted_posts[:3]:
                content = (p.get("content") or "")[:120]
                who = p.get("user_name") or p.get("name") or "anon"
                hot_takes.append(f"@{who}: {content}")

        dominant = "bullish" if bullish > bearish and bullish > neutral else (
            "bearish" if bearish > bullish and bearish > neutral else "mixed"
        )

        snap = SentimentSnapshot(
            round_num=round_num,
            platform=platform,
            bullish_pct=round(bullish / total, 2),
            bearish_pct=round(bearish / total, 2),
            neutral_pct=round(neutral / total, 2),
            post_count=len(recent_posts) if recent_posts else 0,
            dominant_mood=dominant,
            hot_takes=hot_takes,
        )

        self._sentiment_history.setdefault(platform, []).append(snap)
        return snap

    def get_market_prompt(self) -> str:
        snap = self.latest_market
        if snap is None:
            return ""

        delta_str = f"+{snap.price_delta:.2%}" if snap.price_delta >= 0 else f"{snap.price_delta:.2%}"

        lines = [
            "===== PREDICTION MARKET =====",
            f"Q: {snap.question}",
            f"YES: ${snap.yes_price:.2f}  |  NO: ${snap.no_price:.2f}  ({delta_str} this round)",
            f"Market mood: {snap.mood.upper()}  |  {snap.trade_count} trades",
        ]

        if len(self._market_history) >= 3:
            trend = [f"${s.yes_price:.2f}" for s in self._market_history[-5:]]
            lines.append(f"Price trend: {' -> '.join(trend)}")

        return "\n".join(lines)

    def get_sentiment_prompt(self) -> str:
        parts = []
        for platform, snaps in self._sentiment_history.items():
            if not snaps:
                continue
            latest = snaps[-1]
            header = f"===== {platform.upper()} SENTIMENT ====="
            stats = (
                f"Mood: {latest.dominant_mood.upper()} "
                f"(bullish {latest.bullish_pct:.0%} / bearish {latest.bearish_pct:.0%} / "
                f"neutral {latest.neutral_pct:.0%})"
            )
            section = [header, stats]

            if latest.hot_takes:
                section.append("Hot takes:")
                for take in latest.hot_takes:
                    section.append(f"  {take}")

            parts.append("\n".join(section))

        return "\n\n".join(parts)
