"""OasisEnv -- Main simulation orchestrator.

This is the heart of the WhaleSwarm simulation.  It initialises three
platforms (Twitter, Reddit, Polymarket), wires them together via
cross-platform context injection and belief-state updates, and drives
the round loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from simulation_engine.clock.clock import Clock
from simulation_engine.environment.cross_platform_log import CrossPlatformLog
from simulation_engine.environment.market_media_bridge import MarketMediaBridge
from simulation_engine.environment.round_memory import RoundMemory
from simulation_engine.simulations.base import (
    BaseAction,
    BaseEnvironment,
    BasePlatform,
    BasePromptBuilder,
    SimulationConfig,
)
from simulation_engine.simulations.polymarket.amm import anchor_to_real_price, get_price
from simulation_engine.simulations.polymarket.platform import (
    DivergenceTracker,
    PolymarketPlatform,
)
from simulation_engine.simulations.polymarket.volume_tracker import VolumeTracker
from simulation_engine.simulations.polymarket.whale_trader import WhaleTrader, WHALE_USER_ID
from simulation_engine.social_agent.agent import SocialAgent
from simulation_engine.social_agent.agent_graph import AgentGraph
from simulation_engine.social_agent.belief_state import BeliefState, extract_topics_from_requirement
from simulation_engine.social_agent.round_analyzer import analyze_round
from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.database import Database
from simulation_engine.social_platform.platform import Platform as SocialPlatform

logger = logging.getLogger(__name__)

_CROSS_PLATFORM_MARKER = "\n\n# CROSS-PLATFORM CONTEXT"
_BELIEF_STATE_MARKER = "\n\n# YOUR CURRENT BELIEFS AND STANCE"


# ======================================================================
# PlatformBundle -- groups platform + channel + db + agents
# ======================================================================

@dataclass
class PlatformBundle:
    """Groups all objects associated with one simulated platform."""

    name: str
    platform: BasePlatform
    channel: Channel
    db: Database
    env: BaseEnvironment
    agents: List[SocialAgent] = field(default_factory=list)
    belief_states: Dict[int, BeliefState] = field(default_factory=dict)
    platform_task: Optional[asyncio.Task] = None


# ======================================================================
# OasisEnv
# ======================================================================

class OasisEnv:
    """Main simulation orchestrator.

    Manages three platforms (twitter, reddit, polymarket), cross-platform
    context injection, belief-state updates, and the round loop.
    """

    def __init__(
        self,
        platforms: Dict[str, PlatformBundle],
        agent_graph: AgentGraph,
        sim_config: Dict[str, Any],
        sim_dir: str,
        clock: Clock,
        llm_client: Any = None,
        topics: Optional[List[str]] = None,
    ) -> None:
        self.platforms = platforms
        self.agent_graph = agent_graph
        self.sim_config = sim_config
        self.sim_dir = sim_dir
        self.clock = clock
        self.llm_client = llm_client
        self.topics = topics or []

        self.current_round: int = 0
        self.max_rounds: int = int(sim_config.get("max_rounds", 10))

        llm_complete = llm_client.complete if llm_client else None
        self.round_memory = RoundMemory(llm_complete_fn=llm_complete)
        self.bridge = MarketMediaBridge()
        self.cross_log = CrossPlatformLog()

        poly_bundle = self.platforms.get("polymarket")
        if poly_bundle and isinstance(poly_bundle.platform, PolymarketPlatform):
            self.divergence_tracker: DivergenceTracker = poly_bundle.platform.divergence_tracker
        else:
            self.divergence_tracker = DivergenceTracker()

        self.time_config: Dict[str, Any] = sim_config.get("time", {})
        self.event_config: Dict[str, Any] = sim_config.get("events", {})
        self.agent_configs: Dict[str, Any] = sim_config.get("agents", {})

        self._actions_path = os.path.join(sim_dir, "actions.jsonl")
        self._platform_logs: Dict[str, str] = {}
        for pname in platforms:
            plog = os.path.join(sim_dir, f"{pname}_actions.jsonl")
            self._platform_logs[pname] = plog

        self.real_price_fetcher: Optional[Any] = None
        self.real_volume_fetcher: Optional[Any] = None
        self.whale_trader: Optional[WhaleTrader] = None
        self.volume_trackers: Dict[int, VolumeTracker] = {}

        self._stopped = False
        self._paused = False
        self._pause_event: Optional[asyncio.Event] = None

    # ------------------------------------------------------------------
    # Action logging
    # ------------------------------------------------------------------

    def _log_action(self, action: Dict[str, Any]) -> None:
        """Append one action record to the unified and per-platform logs."""
        action["_ts"] = time.time()
        action["_round"] = self.current_round

        # Enrich agent_action entries with human-readable context.
        if action.get("type") == "agent_action":
            self._enrich_action(action)

        line = json.dumps(action, default=str) + "\n"
        try:
            with open(self._actions_path, "a") as f:
                f.write(line)
        except Exception:
            logger.exception("Failed to write action log")

        # Per-platform log.
        platform = action.get("platform")
        if platform and platform in self._platform_logs:
            try:
                with open(self._platform_logs[platform], "a") as f:
                    f.write(line)
            except Exception:
                pass

        # Feed cross-platform log for agent awareness.
        if action.get("type") == "agent_action":
            agent_id = action.get("agent_id")
            if agent_id is not None and platform:
                self.cross_log.record(agent_id, platform, action)

    def _enrich_action(self, action: Dict[str, Any]) -> None:
        """Attach human-readable context to an action (post content for likes, etc.)."""
        act = action.get("action", "")
        args = action.get("arguments", {})
        platform = action.get("platform")
        bundle = self.platforms.get(platform) if platform else None
        if bundle is None:
            return

        try:
            if act in ("like_post", "dislike_post", "repost") and "post_id" in args:
                row = bundle.db.fetchone(
                    "SELECT p.content, u.user_name FROM post p "
                    "LEFT JOIN user u ON p.user_id = u.user_id "
                    "WHERE p.post_id = ?",
                    (args["post_id"],),
                )
                if row:
                    action["_post_content"] = (row["content"] or "")[:150]
                    action["_post_author"] = row["user_name"] or ""

            elif act == "follow" and "followee_id" in args:
                row = bundle.db.fetchone(
                    "SELECT user_name, name FROM user WHERE user_id = ?",
                    (args["followee_id"],),
                )
                if row:
                    action["_target_name"] = row["user_name"] or row["name"] or ""
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Cross-platform context injection
    # ------------------------------------------------------------------

    @staticmethod
    def inject_cross_platform_context(agent: SocialAgent, context_text: str) -> None:
        """Inject cross-platform context into an agent's system message.

        Replaces any existing cross-platform block, or appends a new one.
        """
        if not context_text:
            agent.inject_cross_platform_context("")
            return

        full_block = f"{_CROSS_PLATFORM_MARKER}\n{context_text}"
        agent.inject_cross_platform_context(full_block)

    @staticmethod
    def inject_belief_context(agent: SocialAgent, belief_state: BeliefState) -> None:
        """Inject belief-state text into an agent's system message."""
        belief_text = belief_state.to_prompt_text()
        if not belief_text.strip():
            agent.inject_belief_state("")
            return

        full_block = f"{_BELIEF_STATE_MARKER}\n{belief_text}"
        agent.inject_belief_state(full_block)

    # ------------------------------------------------------------------
    # Platform data readers
    # ------------------------------------------------------------------

    def _read_recent_posts(self, platform_name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Read the most recent posts from a platform's SQLite DB."""
        bundle = self.platforms.get(platform_name)
        if bundle is None:
            return []

        try:
            rows = bundle.db.fetchall(
                "SELECT p.post_id, p.user_id, p.content, p.created_at, "
                "p.num_likes, p.num_dislikes, u.user_name, u.name "
                "FROM post p "
                "LEFT JOIN user u ON p.user_id = u.user_id "
                "ORDER BY p.post_id DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in rows]
        except Exception:
            logger.debug("No posts table yet for %s", platform_name)
            return []

    def _read_market_prices(self) -> List[Dict[str, Any]]:
        """Read current Polymarket prices."""
        bundle = self.platforms.get("polymarket")
        if bundle is None:
            return []

        try:
            markets = bundle.db.fetchall(
                "SELECT * FROM market WHERE resolved = 0 ORDER BY market_id"
            )
            results = []
            for m in markets:
                price_a, price_b = get_price(m["reserve_a"], m["reserve_b"])
                results.append({
                    "market_id": m["market_id"],
                    "question": m["question"],
                    "outcome_a": m["outcome_a"],
                    "outcome_b": m["outcome_b"],
                    "price_yes": round(price_a, 4),
                    "price_no": round(price_b, 4),
                })
            return results
        except Exception:
            logger.debug("No market table yet for polymarket")
            return []

    # ------------------------------------------------------------------
    # Context summarisation
    # ------------------------------------------------------------------

    def _summarise_social_context(
        self,
        twitter_posts: List[Dict[str, Any]],
        reddit_posts: List[Dict[str, Any]],
    ) -> str:
        """Summarise Twitter and Reddit posts into a compact context string."""
        lines: List[str] = []

        if twitter_posts:
            lines.append("Recent Twitter discussion:")
            for p in twitter_posts[:10]:
                who = p.get("user_name") or p.get("name") or "anon"
                content = (p.get("content") or "")[:200]
                likes = p.get("num_likes", 0)
                lines.append(f"  @{who}: {content} [{likes} likes]")

        if reddit_posts:
            lines.append("Recent Reddit discussion:")
            for p in reddit_posts[:10]:
                who = p.get("user_name") or p.get("name") or "anon"
                content = (p.get("content") or "")[:200]
                likes = p.get("num_likes", 0)
                dislikes = p.get("num_dislikes", 0)
                lines.append(f"  u/{who}: {content} [{likes} up / {dislikes} down]")

        return "\n".join(lines)

    def _summarise_market_context(self, market_prices: List[Dict[str, Any]]) -> str:
        """Summarise Polymarket prices for social-media agents."""
        if not market_prices:
            return ""

        lines = ["Current prediction market prices:"]
        for m in market_prices:
            lines.append(
                f"  {m['question']}: "
                f"{m['outcome_a']}=${m['price_yes']:.2f}, "
                f"{m['outcome_b']}=${m['price_no']:.2f}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Agent selection for a round
    # ------------------------------------------------------------------

    def _select_active_agents(self, round_num: int) -> Dict[str, List[SocialAgent]]:
        """Select which agents are active this round based on time config.

        Returns a dict mapping platform name to list of active agents.
        """
        time_cfg = self.time_config
        minutes_per_round = time_cfg.get("minutes_per_round", 30)
        total_hours = time_cfg.get("total_simulation_hours", 24)
        agents_per_hour = time_cfg.get("agents_per_hour", 10)

        peak_hours = set(time_cfg.get("peak_hours", [19, 20, 21, 22]))
        off_peak_hours = set(time_cfg.get("off_peak_hours", [0, 1, 2, 3, 4, 5]))
        peak_mult = time_cfg.get("peak_multiplier", 1.5)
        off_peak_mult = time_cfg.get("off_peak_multiplier", 0.05)

        # Compute simulated hour of day.
        if total_hours > 0 and minutes_per_round > 0:
            sim_minute = round_num * minutes_per_round
            sim_hour = (sim_minute // 60) % 24
        else:
            sim_hour = 12  # default to midday

        # Determine activity multiplier.
        if sim_hour in peak_hours:
            multiplier = peak_mult
        elif sim_hour in off_peak_hours:
            multiplier = off_peak_mult
        else:
            multiplier = time_cfg.get("work_hour_multiplier", 0.7)
            if 17 <= sim_hour <= 23:
                multiplier = time_cfg.get("evening_multiplier", 1.2)

        target_count = max(1, int(agents_per_hour * multiplier))

        result: Dict[str, List[SocialAgent]] = {}

        for pname, bundle in self.platforms.items():
            if not bundle.agents:
                continue

            # Each agent has an activity_level from config.
            weighted_agents: List[Tuple[SocialAgent, float]] = []
            for agent in bundle.agents:
                # Look up per-agent config.
                agent_cfg = self._get_agent_config(agent.agent_id)
                activity = float(agent_cfg.get("activity_level", 0.5))
                # Weight by activity level + small random jitter.
                weight = activity + random.uniform(0, 0.3)
                weighted_agents.append((agent, weight))

            # Sort by weight descending and pick top target_count.
            weighted_agents.sort(key=lambda x: x[1], reverse=True)
            count = min(target_count, len(weighted_agents))
            result[pname] = [a for a, _ in weighted_agents[:count]]

        return result

    def _get_agent_config(self, agent_id: int) -> Dict[str, Any]:
        """Look up the per-agent config from simulation config."""
        if isinstance(self.agent_configs, dict):
            return self.agent_configs.get(str(agent_id), {})
        if isinstance(self.agent_configs, list):
            for cfg in self.agent_configs:
                if cfg.get("agent_id") == agent_id or cfg.get("user_id") == agent_id:
                    return cfg
        return {}

    # ------------------------------------------------------------------
    # Real-price fetching (stub -- real implementation injects fetcher)
    # ------------------------------------------------------------------

    async def _fetch_real_price(self, market_id: int) -> Optional[float]:
        """Fetch the real Polymarket CLOB price for a market.

        Returns the YES price in (0, 1) or None if not configured.
        """
        if self.real_price_fetcher is None:
            return None

        try:
            if asyncio.iscoroutinefunction(self.real_price_fetcher):
                return await self.real_price_fetcher(market_id)
            # Run sync HTTP fetcher in a thread to avoid blocking the event loop.
            return await asyncio.to_thread(self.real_price_fetcher, market_id)
        except Exception:
            logger.warning("Failed to fetch real price for market %d", market_id, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # AMM anchoring / pegging
    # ------------------------------------------------------------------

    def _anchor_amm_to_real(self, market_id: int, real_price_yes: float) -> None:
        """Anchor the internal AMM reserves to a real price (legacy path)."""
        bundle = self.platforms.get("polymarket")
        if bundle is None:
            return

        market = bundle.db.fetchone(
            "SELECT * FROM market WHERE market_id = ? AND resolved = 0",
            (market_id,),
        )
        if market is None:
            return

        try:
            new_ra, new_rb = anchor_to_real_price(
                market["reserve_a"], market["reserve_b"], real_price_yes,
            )
            bundle.db.execute(
                "UPDATE market SET reserve_a = ?, reserve_b = ? WHERE market_id = ?",
                (new_ra, new_rb, market_id),
            )
            logger.info(
                "Anchored market %d to real price %.4f (reserves: %.2f / %.2f)",
                market_id, real_price_yes, new_ra, new_rb,
            )
        except ValueError:
            logger.warning(
                "Could not anchor market %d to price %.4f", market_id, real_price_yes,
            )

    async def _fetch_real_volume(self, market_id: int) -> Optional[float]:
        """Fetch the cumulative real Polymarket volume for a market."""
        if self.real_volume_fetcher is None:
            return None

        try:
            if asyncio.iscoroutinefunction(self.real_volume_fetcher):
                return await self.real_volume_fetcher(market_id)
            return await asyncio.to_thread(self.real_volume_fetcher, market_id)
        except Exception:
            logger.warning("Failed to fetch real volume for market %d", market_id, exc_info=True)
            return None

    async def _peg_amm_to_real(self, market_id: int, round_num: int) -> None:
        """Peg the AMM to the real Polymarket price using whale trades.

        Only applies the update if real volume exceeds the threshold
        relative to simulated volume (or the absolute $10k floor).
        """
        bundle = self.platforms.get("polymarket")
        if bundle is None or self.whale_trader is None:
            return

        real_price = await self._fetch_real_price(market_id)
        if real_price is None:
            return

        # Get or create volume tracker for this market.
        if market_id not in self.volume_trackers:
            self.volume_trackers[market_id] = VolumeTracker()
        tracker = self.volume_trackers[market_id]

        # Fetch real cumulative volume.
        real_volume = await self._fetch_real_volume(market_id)
        if real_volume is None:
            real_volume = 0.0

        # Accumulate simulated volume from trades since last anchor.
        # Sum absolute cost of all non-whale trades in this window.
        sim_vol_row = bundle.db.fetchone(
            "SELECT COALESCE(SUM(ABS(cost)), 0) AS vol FROM trade "
            "WHERE market_id = ? AND user_id != ? AND rowid > ("
            "  SELECT COALESCE(MAX(rowid), 0) FROM trade "
            "  WHERE market_id = ? AND user_id = ?)",
            (market_id, WHALE_USER_ID, market_id, WHALE_USER_ID),
        )
        if sim_vol_row:
            tracker.simulated_volume_since_anchor = float(sim_vol_row["vol"])

        if not tracker.should_anchor(real_volume):
            logger.debug(
                "Volume threshold not met for market %d — skipping peg", market_id,
            )
            return

        # Execute the whale trade.
        summary = self.whale_trader.execute_peg(bundle.db, market_id, real_price)
        if summary:
            self._log_action({
                "type": "whale_trade",
                "market_id": market_id,
                "round": round_num,
                **summary,
            })

        tracker.reset(round_num, real_volume)

    # ------------------------------------------------------------------
    # Event injection
    # ------------------------------------------------------------------

    def _inject_scheduled_events(self, round_num: int) -> None:
        """Inject any scheduled events for this round.

        Supports two trigger modes:
        - ``"round": N`` — fires at exact round N (preferred for fictional events)
        - ``"hour": H``  — fires when simulated hour equals H (legacy)
        """
        events = self.event_config.get("scheduled_events", [])
        minutes_per_round = self.time_config.get("minutes_per_round", 30)

        for event in events:
            # Round-based trigger (preferred)
            trigger_round = event.get("round")
            if trigger_round is not None:
                if round_num != trigger_round:
                    continue
            else:
                # Hour-based trigger (legacy)
                trigger_hour = event.get("hour")
                if trigger_hour is None:
                    continue
                sim_minute = round_num * minutes_per_round
                sim_hour = sim_minute // 60
                if sim_hour != trigger_hour:
                    continue

            # Support both "description" and "event" keys (config generator uses both)
            event_text = event.get("description") or event.get("event", "")
            if not event_text:
                continue

            target_platforms = event.get("platforms", list(self.platforms.keys()))

            logger.info(
                "Injecting event at round %d: %s", round_num, event_text[:80],
            )

            for pname in target_platforms:
                bundle = self.platforms.get(pname)
                if bundle is None:
                    continue
                for agent in bundle.agents:
                    agent.env.set_extra_context(
                        agent.env.extra_observation_context + f"\n\nBREAKING: {event_text}"
                    )

            self._log_action({
                "type": "event_injection",
                "round": round_num,
                "description": event_text,
                "platforms": target_platforms,
            })

    # ------------------------------------------------------------------
    # Run a single agent
    # ------------------------------------------------------------------

    async def _run_agent(
        self,
        agent: SocialAgent,
        platform_name: str,
    ) -> Dict[str, Any]:
        """Run one agent for one round and return the action summary."""
        try:
            result = await agent.perform_action_by_llm()

            # Log each tool call as an action.
            for i, tc in enumerate(result.get("tool_calls", [])):
                self._log_action({
                    "type": "agent_action",
                    "platform": platform_name,
                    "agent_id": agent.agent_id,
                    "agent_name": agent.user_info.name,
                    "action": tc.get("name", "unknown"),
                    "arguments": tc.get("arguments", {}),
                    "response": result["responses"][i] if i < len(result.get("responses", [])) else None,
                })

            if not result.get("tool_calls"):
                self._log_action({
                    "type": "agent_action",
                    "platform": platform_name,
                    "agent_id": agent.agent_id,
                    "agent_name": agent.user_info.name,
                    "action": "do_nothing",
                    "arguments": {},
                    "response": None,
                })

            return result

        except Exception:
            logger.exception(
                "Error running agent %d on %s", agent.agent_id, platform_name,
            )
            self._log_action({
                "type": "agent_error",
                "platform": platform_name,
                "agent_id": agent.agent_id,
                "error": "agent execution failed",
            })
            return {"tool_calls": [], "responses": []}

    # ------------------------------------------------------------------
    # Run one round
    # ------------------------------------------------------------------

    async def _run_round(self, round_num: int) -> str:
        """Execute a single simulation round.  Returns a round summary string."""
        self.current_round = round_num
        logger.info("===== ROUND %d / %d =====", round_num + 1, self.max_rounds)

        self._log_action({
            "type": "round_start",
            "round": round_num,
            "max_rounds": self.max_rounds,
        })

        # 1. Peg AMM to real Polymarket prices (whale trades with volume threshold).
        poly_bundle = self.platforms.get("polymarket")
        if poly_bundle is not None:
            try:
                markets = poly_bundle.db.fetchall(
                    "SELECT market_id FROM market WHERE resolved = 0"
                )
                for m in (markets or []):
                    mid = m["market_id"]
                    if self.whale_trader is not None:
                        await self._peg_amm_to_real(mid, round_num)
                    else:
                        # Legacy path: direct reserve reset.
                        real_price = await self._fetch_real_price(mid)
                        if real_price is not None:
                            self._anchor_amm_to_real(mid, real_price)
            except Exception:
                logger.debug("No markets to anchor yet")

        # 3. Update bridge with latest prices and sentiment.
        if poly_bundle is not None:
            self.bridge.update_prices(poly_bundle.db, round_num)

        twitter_posts = self._read_recent_posts("twitter", limit=15)
        reddit_posts = self._read_recent_posts("reddit", limit=15)

        for pname in ("twitter", "reddit"):
            bundle = self.platforms.get(pname)
            if bundle and bundle.belief_states:
                posts = twitter_posts if pname == "twitter" else reddit_posts
                self.bridge.update_sentiment(bundle.belief_states, pname, round_num, posts)

        # 4. Inject market prompt into social agents, sentiment into polymarket agents.
        market_prompt = self.bridge.get_market_prompt()
        sentiment_prompt = self.bridge.get_sentiment_prompt()

        for pname in ("twitter", "reddit"):
            bundle = self.platforms.get(pname)
            if bundle is None:
                continue
            for agent in bundle.agents:
                ctx_parts = []
                if market_prompt:
                    ctx_parts.append(market_prompt)
                digest = self.cross_log.get_digest(agent.agent_id, pname)
                if digest:
                    ctx_parts.append(digest)
                if ctx_parts:
                    self.inject_cross_platform_context(agent, "\n\n".join(ctx_parts))

        if poly_bundle:
            social_ctx = self._summarise_social_context(twitter_posts, reddit_posts)
            combined = ""
            if social_ctx:
                combined += social_ctx
            if sentiment_prompt:
                combined += "\n\n" + sentiment_prompt
            for agent in poly_bundle.agents:
                ctx_parts = [combined] if combined else []
                digest = self.cross_log.get_digest(agent.agent_id, "polymarket")
                if digest:
                    ctx_parts.append(digest)
                agent.env.set_extra_context("\n\n".join(ctx_parts))

        # 5. Inject round memory context into all agents.
        memory_ctx = self.round_memory.build_context()
        if memory_ctx:
            for bundle in self.platforms.values():
                for agent in bundle.agents:
                    current = getattr(agent, '_round_memory_ctx', '')
                    if current != memory_ctx:
                        agent._round_memory_ctx = memory_ctx

        # 6. Inject belief states.
        for pname, bundle in self.platforms.items():
            for agent in bundle.agents:
                belief = bundle.belief_states.get(agent.agent_id)
                if belief is not None:
                    self.inject_belief_context(agent, belief)

        # 7. Inject scheduled events.
        self._inject_scheduled_events(round_num)

        if round_num == 0:
            await self._inject_initial_posts()
            self._inject_initial_subreddits()

        # 8. Select active agents and run them concurrently.
        active_agents = self._select_active_agents(round_num)

        all_tasks = []
        task_meta: List[Tuple[str, SocialAgent]] = []

        for pname, agents in active_agents.items():
            for agent in agents:
                all_tasks.append(self._run_agent(agent, pname))
                task_meta.append((pname, agent))

        logger.info("Dispatching %d agent tasks via asyncio.gather ...", len(all_tasks))
        if all_tasks:
            results = await asyncio.gather(*all_tasks, return_exceptions=True)
        else:
            results = []

        # Log any exceptions from the gather.
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                pname, agent = task_meta[i]
                logger.error(
                    "Agent %d (%s) on %s raised: %s",
                    agent.agent_id, agent.user_info.name, pname, res,
                )

        logger.info("All %d agent tasks completed for round %d", len(all_tasks), round_num)

        # Build round summary.
        action_counts: Dict[str, int] = {}
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                continue
            if isinstance(res, dict):
                for tc in res.get("tool_calls", []):
                    action_name = tc.get("name", "unknown")
                    action_counts[action_name] = action_counts.get(action_name, 0) + 1

        summary_parts = [f"Round {round_num + 1}: {len(all_tasks)} agents active"]
        for action_name, count in sorted(action_counts.items()):
            summary_parts.append(f"  {action_name}: {count}")

        round_summary = "\n".join(summary_parts)
        round_detail = round_summary

        market_snap = self.bridge.latest_market
        if market_snap:
            round_detail += f"\nMarket: YES=${market_snap.yes_price:.2f} ({market_snap.mood})"

        # 9. Update belief states via round_analyzer.
        for pname, bundle in self.platforms.items():
            if not bundle.belief_states:
                continue
            agents_with_beliefs = [
                (agent.agent_id, bundle.belief_states[agent.agent_id])
                for agent in bundle.agents
                if agent.agent_id in bundle.belief_states
            ]
            if agents_with_beliefs:
                try:
                    # Refresh rec matrix for social platforms.
                    if isinstance(bundle.platform, SocialPlatform):
                        bundle.platform.refresh_rec_matrix()

                    analyze_round(
                        db=bundle.db,
                        agents_with_beliefs=agents_with_beliefs,
                        round_num=round_num,
                        rec_matrix=getattr(bundle.platform, "rec_matrix", None),
                    )
                except Exception:
                    logger.exception("Error in round analysis for %s", pname)

        logger.info("Belief states updated. Recording divergence ...")
        if poly_bundle is not None:
            try:
                markets = poly_bundle.db.fetchall(
                    "SELECT market_id, reserve_a, reserve_b FROM market WHERE resolved = 0"
                )
                for m in (markets or []):
                    mid = m["market_id"]
                    internal_price, _ = get_price(m["reserve_a"], m["reserve_b"])
                    real_price = await self._fetch_real_price(mid)
                    if real_price is not None:
                        gap = self.divergence_tracker.record(
                            mid, round_num, internal_price, real_price,
                        )
                        self._log_action({
                            "type": "divergence",
                            "market_id": mid,
                            "internal_price": round(internal_price, 4),
                            "real_price": round(real_price, 4),
                            "gap": round(gap, 4),
                        })
            except Exception:
                logger.debug("No divergence to record")

        # Record round memory.
        self.round_memory.record(round_num, round_summary, round_detail)

        # 11. Log round completion.
        self._log_action({
            "type": "round_end",
            "round": round_num,
            "agents_active": len(all_tasks),
            "action_counts": action_counts,
        })

        logger.info("Round %d complete: %s", round_num + 1, round_summary)
        return round_summary

    # ------------------------------------------------------------------
    # Initial post injection
    # ------------------------------------------------------------------

    def _inject_initial_subreddits(self) -> None:
        """Seed subreddits from simulation topics and auto-subscribe agents."""
        bundle = self.platforms.get("reddit")
        if bundle is None or not isinstance(bundle.platform, SocialPlatform):
            return

        subreddit_names = []
        for topic in self.topics[:10]:
            name = topic.lower().replace(" ", "_").replace("-", "_")[:30]
            name = "".join(c for c in name if c.isalnum() or c == "_")
            if not name:
                continue
            bundle.platform.create_subreddit(0, {
                "name": name,
                "description": f"Discussion about {topic}",
                "similar_to": [],
            })
            subreddit_names.append(name)

        # Also create a general discussion subreddit
        general_name = "general_discussion"
        bundle.platform.create_subreddit(0, {
            "name": general_name,
            "description": "General discussion and off-topic conversation",
            "similar_to": [],
        })
        subreddit_names.append(general_name)

        # Auto-subscribe all Reddit agents to all seeded subreddits so their
        # feeds are populated from round 1.
        for agent in bundle.agents:
            for sname in subreddit_names:
                try:
                    bundle.platform.follow_subreddit(agent.agent_id, {"subreddit_name": sname})
                except Exception:
                    pass  # already following or subreddit doesn't exist

        if subreddit_names:
            logger.info(
                "Seeded %d subreddits, auto-subscribed %d agents",
                len(subreddit_names), len(bundle.agents),
            )

    async def _inject_initial_posts(self) -> None:
        """Inject seed posts from event config into social platforms."""
        initial_posts = self.event_config.get("initial_posts", [])
        if not initial_posts:
            return

        # For Reddit, find seeded subreddit IDs so posts land in communities.
        reddit_subreddit_ids = []
        reddit_bundle = self.platforms.get("reddit")
        if reddit_bundle:
            try:
                rows = reddit_bundle.db.fetchall("SELECT subreddit_id FROM subreddit")
                reddit_subreddit_ids = [r["subreddit_id"] for r in (rows or [])]
            except Exception:
                pass

        for pname in ("twitter", "reddit"):
            bundle = self.platforms.get(pname)
            if bundle is None or not bundle.agents:
                continue

            for i, post_text in enumerate(initial_posts):
                agent = random.choice(bundle.agents)
                try:
                    if pname == "reddit" and reddit_subreddit_ids:
                        # Assign posts to subreddits round-robin
                        sub_id = reddit_subreddit_ids[i % len(reddit_subreddit_ids)]
                        bundle.db.execute(
                            "INSERT INTO post (user_id, content, subreddit_id, created_at) VALUES (?, ?, ?, ?)",
                            (agent.agent_id, post_text, sub_id, datetime.utcnow().isoformat()),
                        )
                    else:
                        bundle.db.execute(
                            "INSERT INTO post (user_id, content, created_at) VALUES (?, ?, ?)",
                            (agent.agent_id, post_text, datetime.utcnow().isoformat()),
                        )
                    self._log_action({
                        "type": "initial_post",
                        "platform": pname,
                        "agent_id": agent.agent_id,
                        "content": post_text[:200],
                    })
                except Exception:
                    logger.debug("Could not inject initial post on %s", pname)

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    async def run(self, start_round: int = 0) -> None:
        """Run the simulation from *start_round* through *max_rounds*.

        Args:
            start_round: Round to begin at (0-indexed).  Set >0 to resume
                a previously interrupted simulation.
        """
        total_agents = sum(len(b.agents) for b in self.platforms.values())
        logger.info(
            "Starting simulation: rounds %d-%d, %d platforms, %d total agents",
            start_round, self.max_rounds - 1,
            len(self.platforms), total_agents,
        )

        self._log_action({
            "type": "simulation_start",
            "max_rounds": self.max_rounds,
            "start_round": start_round,
            "platforms": list(self.platforms.keys()),
            "total_agents": total_agents,
        })

        for pname, bundle in self.platforms.items():
            bundle.platform_task = asyncio.create_task(
                bundle.platform.run(),
                name=f"platform-{pname}",
            )
            logger.info("Started platform loop for %s", pname)

        await asyncio.sleep(0.1)

        try:
            for round_num in range(start_round, self.max_rounds):
                if self._stopped:
                    logger.info("Simulation stopped at round %d", round_num)
                    break
                if self._paused and self._pause_event is not None:
                    self._log_action({"type": "simulation_paused", "round": round_num})
                    logger.info("Simulation paused before round %d", round_num)
                    await self._pause_event.wait()
                    if self._stopped:
                        break
                    self._log_action({"type": "simulation_resumed", "round": round_num})
                await self._run_round(round_num)
        except Exception:
            logger.exception("Simulation failed")
            self._log_action({"type": "simulation_error", "error": "unhandled exception"})
            raise
        finally:
            for pname, bundle in self.platforms.items():
                bundle.platform.stop()
                bundle.channel.close()
                if bundle.platform_task and not bundle.platform_task.done():
                    bundle.platform_task.cancel()
                    try:
                        await bundle.platform_task
                    except (asyncio.CancelledError, Exception):
                        pass
                bundle.platform.close()

            self.round_memory.shutdown()

            self._log_action({
                "type": "simulation_end",
                "rounds_completed": self.current_round + 1 if not self._stopped else self.current_round,
            })

            logger.info("Simulation complete.")

    def stop(self) -> None:
        """Signal the simulation to stop after the current round."""
        self._stopped = True
        # Unpause so the loop can exit cleanly.
        if self._pause_event and not self._pause_event.is_set():
            self._pause_event.set()

    def pause(self) -> None:
        """Pause the simulation between rounds."""
        self._paused = True
        if self._pause_event is None:
            self._pause_event = asyncio.Event()
        self._pause_event.clear()
        logger.info("Simulation paused")

    def resume(self) -> None:
        """Resume a paused simulation."""
        self._paused = False
        if self._pause_event is not None:
            self._pause_event.set()
        logger.info("Simulation resumed")
