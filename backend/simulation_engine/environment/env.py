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
from simulation_engine.social_agent.agent import SocialAgent
from simulation_engine.social_agent.agent_graph import AgentGraph
from simulation_engine.social_agent.belief_state import BeliefState, extract_topics_from_requirement
from simulation_engine.social_agent.round_analyzer import analyze_round
from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.database import Database
from simulation_engine.social_platform.platform import Platform as SocialPlatform

logger = logging.getLogger(__name__)

# ======================================================================
# Constants
# ======================================================================

_CROSS_PLATFORM_MARKER = "\n\n# CROSS-PLATFORM CONTEXT"
_BELIEF_STATE_MARKER = "\n\n# YOUR CURRENT BELIEFS AND STANCE"

# RoundMemory: how many recent rounds get full detail before summarisation.
_FULL_DETAIL_WINDOW = 2
_MAX_SUMMARY_ROUNDS = 10


# ======================================================================
# RoundMemory -- sliding window of round context
# ======================================================================

@dataclass
class RoundMemory:
    """Sliding window of round-level summaries.

    The most recent ``_FULL_DETAIL_WINDOW`` rounds are kept in full detail.
    Older rounds are compressed into a short summary.
    """

    entries: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, round_num: int, summary: str, detail: str) -> None:
        """Record the output of one round."""
        self.entries.append({
            "round": round_num,
            "summary": summary,
            "detail": detail,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def build_context(self) -> str:
        """Return a combined context string with sliding-window compression."""
        if not self.entries:
            return ""

        parts: List[str] = []

        # Older rounds: summarised.
        older = self.entries[:-_FULL_DETAIL_WINDOW] if len(self.entries) > _FULL_DETAIL_WINDOW else []
        recent = self.entries[-_FULL_DETAIL_WINDOW:]

        if older:
            # Keep only the last _MAX_SUMMARY_ROUNDS of older entries.
            older = older[-_MAX_SUMMARY_ROUNDS:]
            summary_lines = [
                f"  Round {e['round']}: {e['summary']}" for e in older
            ]
            parts.append(
                "Previous rounds (summarised):\n" + "\n".join(summary_lines)
            )

        for entry in recent:
            parts.append(
                f"--- Round {entry['round']} (detail) ---\n{entry['detail']}"
            )

        return "\n\n".join(parts)


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

        # Round bookkeeping.
        self.current_round: int = 0
        self.max_rounds: int = int(sim_config.get("max_rounds", 10))
        self.round_memory = RoundMemory()

        # Divergence tracker (Polymarket AMM vs real CLOB price).
        poly_bundle = self.platforms.get("polymarket")
        if poly_bundle and isinstance(poly_bundle.platform, PolymarketPlatform):
            self.divergence_tracker: DivergenceTracker = poly_bundle.platform.divergence_tracker
        else:
            self.divergence_tracker = DivergenceTracker()

        # Time config from simulation_config.
        self.time_config: Dict[str, Any] = sim_config.get("time", {})
        self.event_config: Dict[str, Any] = sim_config.get("events", {})
        self.agent_configs: Dict[str, Any] = sim_config.get("agents", {})

        # Actions log.
        self._actions_path = os.path.join(sim_dir, "actions.jsonl")

        # Real-price fetcher (injected externally or None).
        self.real_price_fetcher: Optional[Any] = None

        self._stopped = False

    # ------------------------------------------------------------------
    # Action logging
    # ------------------------------------------------------------------

    def _log_action(self, action: Dict[str, Any]) -> None:
        """Append one action record to actions.jsonl."""
        action["_ts"] = time.time()
        action["_round"] = self.current_round
        try:
            with open(self._actions_path, "a") as f:
                f.write(json.dumps(action, default=str) + "\n")
        except Exception:
            logger.exception("Failed to write action log")

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
            return self.real_price_fetcher(market_id)
        except Exception:
            logger.warning("Failed to fetch real price for market %d", market_id, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # AMM anchoring
    # ------------------------------------------------------------------

    def _anchor_amm_to_real(self, market_id: int, real_price_yes: float) -> None:
        """Anchor the internal AMM reserves to a real price."""
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

    # ------------------------------------------------------------------
    # Event injection
    # ------------------------------------------------------------------

    def _inject_scheduled_events(self, round_num: int) -> None:
        """Inject any scheduled events for this round."""
        events = self.event_config.get("scheduled_events", [])
        minutes_per_round = self.time_config.get("minutes_per_round", 30)

        for event in events:
            trigger_hour = event.get("hour")
            if trigger_hour is None:
                continue

            # Convert round to simulated hour.
            sim_minute = round_num * minutes_per_round
            sim_hour = sim_minute // 60

            if sim_hour == trigger_hour:
                event_text = event.get("description", "")
                target_platforms = event.get("platforms", list(self.platforms.keys()))

                logger.info(
                    "Injecting event at hour %d: %s", sim_hour, event_text[:80],
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
                    "hour": sim_hour,
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

        # 1. Fetch real Polymarket CLOB prices and anchor AMM.
        poly_bundle = self.platforms.get("polymarket")
        if poly_bundle is not None:
            try:
                markets = poly_bundle.db.fetchall(
                    "SELECT market_id FROM market WHERE resolved = 0"
                )
                for m in (markets or []):
                    mid = m["market_id"]
                    real_price = await self._fetch_real_price(mid)
                    if real_price is not None:
                        # 2. Anchor internal AMM to real price.
                        self._anchor_amm_to_real(mid, real_price)
            except Exception:
                logger.debug("No markets to anchor yet")

        # 3. Read latest social-media posts.
        twitter_posts = self._read_recent_posts("twitter", limit=15)
        reddit_posts = self._read_recent_posts("reddit", limit=15)

        # 4. Summarise into social context string.
        social_context = self._summarise_social_context(twitter_posts, reddit_posts)

        # 5. Inject social context into Polymarket agent observations.
        if poly_bundle and social_context:
            for agent in poly_bundle.agents:
                agent.env.set_extra_context(social_context)

        # 6. Read latest Polymarket prices.
        market_prices = self._read_market_prices()
        market_context = self._summarise_market_context(market_prices)

        # 7. Inject market prices into Twitter/Reddit agent system messages.
        for pname in ("twitter", "reddit"):
            bundle = self.platforms.get(pname)
            if bundle is None:
                continue
            for agent in bundle.agents:
                if market_context:
                    self.inject_cross_platform_context(agent, market_context)

        # Inject belief states into all agents.
        for pname, bundle in self.platforms.items():
            for agent in bundle.agents:
                belief = bundle.belief_states.get(agent.agent_id)
                if belief is not None:
                    self.inject_belief_context(agent, belief)

        # Inject scheduled events.
        self._inject_scheduled_events(round_num)

        # Inject initial posts on round 0.
        if round_num == 0:
            await self._inject_initial_posts()

        # 8. Select active agents and run them concurrently.
        active_agents = self._select_active_agents(round_num)

        all_tasks = []
        task_meta: List[Tuple[str, SocialAgent]] = []

        for pname, agents in active_agents.items():
            for agent in agents:
                all_tasks.append(self._run_agent(agent, pname))
                task_meta.append((pname, agent))

        if all_tasks:
            results = await asyncio.gather(*all_tasks, return_exceptions=True)
        else:
            results = []

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

        if market_prices:
            price_line = " | ".join(
                f"{m['question']}: YES={m['price_yes']}" for m in market_prices[:3]
            )
            round_detail += f"\nMarket prices: {price_line}"

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

        # 10. Record divergence (internal AMM price vs real).
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

    async def _inject_initial_posts(self) -> None:
        """Inject seed posts from event config into social platforms."""
        initial_posts = self.event_config.get("initial_posts", [])
        if not initial_posts:
            return

        for pname in ("twitter", "reddit"):
            bundle = self.platforms.get(pname)
            if bundle is None or not bundle.agents:
                continue

            for i, post_text in enumerate(initial_posts):
                # Assign to a random agent on this platform.
                agent = random.choice(bundle.agents)
                try:
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

    async def run(self) -> None:
        """Run the full simulation: start platform message loops, then
        iterate through all rounds."""
        logger.info(
            "Starting simulation: %d rounds, %d platforms, %d total agents",
            self.max_rounds,
            len(self.platforms),
            sum(len(b.agents) for b in self.platforms.values()),
        )

        self._log_action({
            "type": "simulation_start",
            "max_rounds": self.max_rounds,
            "platforms": list(self.platforms.keys()),
            "total_agents": sum(len(b.agents) for b in self.platforms.values()),
        })

        # Start platform message loops as background tasks.
        for pname, bundle in self.platforms.items():
            bundle.platform_task = asyncio.create_task(
                bundle.platform.run(),
                name=f"platform-{pname}",
            )
            logger.info("Started platform loop for %s", pname)

        # Give platforms a moment to start.
        await asyncio.sleep(0.1)

        try:
            for round_num in range(self.max_rounds):
                if self._stopped:
                    logger.info("Simulation stopped at round %d", round_num)
                    break
                await self._run_round(round_num)
        except Exception:
            logger.exception("Simulation failed")
            self._log_action({"type": "simulation_error", "error": "unhandled exception"})
            raise
        finally:
            # Stop all platforms.
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

            self._log_action({
                "type": "simulation_end",
                "rounds_completed": self.current_round + 1 if not self._stopped else self.current_round,
            })

            logger.info("Simulation complete.")

    def stop(self) -> None:
        """Signal the simulation to stop after the current round."""
        self._stopped = True
