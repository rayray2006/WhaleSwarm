"""Factory functions for creating a fully configured OasisEnv.

``create_environment()`` is the main entry point.  It loads profiles,
creates platform bundles (Twitter, Reddit, Polymarket) with their own
Channel + SQLite databases, generates agents, wires up belief states,
and returns a ready-to-run ``OasisEnv``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from simulation_engine.clock.clock import Clock
from simulation_engine.environment.env import OasisEnv, PlatformBundle
from simulation_engine.simulations.base import (
    BaseAction,
    BaseEnvironment,
    BasePlatform,
)
from simulation_engine.simulations.polymarket.actions import PolymarketAction
from simulation_engine.simulations.polymarket.environment import PolymarketEnvironment
from simulation_engine.simulations.polymarket.platform import PolymarketPlatform
from simulation_engine.simulations.polymarket.prompts import PolymarketPromptBuilder
from simulation_engine.simulations.social_media.actions import RedditAction, TwitterAction
from simulation_engine.simulations.social_media.environment import SocialMediaEnvironment
from simulation_engine.simulations.social_media.prompts import (
    RedditPromptBuilder,
    TwitterPromptBuilder,
)
from simulation_engine.social_agent.agent import SocialAgent
from simulation_engine.social_agent.agent_graph import AgentGraph
from simulation_engine.social_agent.agents_generator import generate_agents
from simulation_engine.social_agent.belief_state import (
    BeliefState,
    extract_topics_from_requirement,
)
from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.database import Database
from simulation_engine.social_platform.platform import Platform as SocialPlatform
from simulation_engine.social_platform.typing import ActionType, RecsysType

logger = logging.getLogger(__name__)


# ======================================================================
# Profile loaders
# ======================================================================

def _load_profiles(sim_dir: str, platform: str) -> List[Dict[str, Any]]:
    """Load agent profiles for *platform* from the simulation directory."""
    path = os.path.join(sim_dir, f"{platform}_profiles.json")
    if not os.path.exists(path):
        logger.warning("No profiles found at %s", path)
        return []
    with open(path) as f:
        profiles = json.load(f)
    logger.info("Loaded %d profiles for %s from %s", len(profiles), platform, path)
    return profiles


# ======================================================================
# Platform bundle builders
# ======================================================================

def _create_social_platform_bundle(
    platform_name: str,
    profiles: List[Dict[str, Any]],
    sim_dir: str,
    sim_config: Dict[str, Any],
    llm_client: Any,
    topics: List[str],
    agent_configs: Any,
    recsys_type: RecsysType = RecsysType.RANDOM,
) -> Optional[PlatformBundle]:
    """Create a social-media (Twitter or Reddit) PlatformBundle."""
    if not profiles:
        logger.info("No profiles for %s -- skipping platform", platform_name)
        return None

    # Database.
    db_path = os.path.join(sim_dir, f"{platform_name}.db")
    channel = Channel()
    db = Database(db_path)

    # Platform server.
    platform = SocialPlatform(
        db_path=db_path,
        channel=channel,
        recsys_type=recsys_type,
        max_rec_post_len=20,
    )

    # Environment.
    env = SocialMediaEnvironment(db=platform.db, platform_name=platform_name.capitalize())

    # Prompt builder and action class.
    if platform_name == "twitter":
        prompt_builder = TwitterPromptBuilder()
        action_cls = TwitterAction
    else:
        prompt_builder = RedditPromptBuilder()
        action_cls = RedditAction

    # Generate agents.
    agents = generate_agents(
        profiles=profiles,
        channel=channel,
        env=env,
        action_cls=action_cls,
        prompt_builder=prompt_builder,
        llm_client=llm_client,
        max_iterations=1,
    )

    # Register agents on the platform (sign_up).
    for agent in agents:
        profile = agent.user_info.profile or {}
        platform.sign_up(agent.agent_id, {
            "user_name": profile.get("user_name", agent.user_info.name.lower().replace(" ", "_")),
            "name": agent.user_info.name,
            "bio": agent.user_info.description[:500],
        })

    # Build belief states.
    belief_states: Dict[int, BeliefState] = {}
    for agent in agents:
        agent_cfg = _get_agent_config(agent.agent_id, agent_configs)
        belief_states[agent.agent_id] = BeliefState.from_profile(agent_cfg, topics)

    logger.info(
        "Created %s bundle: %d agents, db=%s",
        platform_name, len(agents), db_path,
    )

    return PlatformBundle(
        name=platform_name,
        platform=platform,
        channel=channel,
        db=platform.db,
        env=env,
        agents=agents,
        belief_states=belief_states,
    )


def _create_polymarket_bundle(
    profiles: List[Dict[str, Any]],
    sim_dir: str,
    sim_config: Dict[str, Any],
    llm_client: Any,
    topics: List[str],
    agent_configs: Any,
) -> Optional[PlatformBundle]:
    """Create the Polymarket PlatformBundle."""
    if not profiles:
        logger.info("No profiles for polymarket -- skipping platform")
        return None

    db_path = os.path.join(sim_dir, "polymarket.db")
    channel = Channel()

    platform_cfg = sim_config.get("platform", {})
    initial_balance = float(platform_cfg.get("initial_balance", 1000.0))

    platform = PolymarketPlatform(
        db_path=db_path,
        channel=channel,
        initial_balance=initial_balance,
    )

    env = PolymarketEnvironment(db=platform.db)
    prompt_builder = PolymarketPromptBuilder()

    agents = generate_agents(
        profiles=profiles,
        channel=channel,
        env=env,
        action_cls=PolymarketAction,
        prompt_builder=prompt_builder,
        llm_client=llm_client,
        max_iterations=1,
    )

    # Sign up agents and create portfolios.
    for agent in agents:
        profile = agent.user_info.profile or {}
        platform.sign_up(agent.agent_id, {
            "user_name": profile.get("user_name", f"trader_{agent.agent_id}"),
            "name": agent.user_info.name,
            "bio": agent.user_info.description[:500],
        })

    # Create initial market(s) from config.
    markets_config = sim_config.get("platform", {}).get("markets", [])
    if not markets_config:
        # Fallback: create a default market from the simulation requirement.
        requirement = sim_config.get("simulation_requirement", "")
        if requirement:
            markets_config = [{
                "question": requirement[:200],
                "outcome_a": "YES",
                "outcome_b": "NO",
                "initial_probability": 0.5,
            }]

    for market_cfg in markets_config:
        platform.create_market(0, {
            "question": market_cfg.get("question", "Will the event happen?"),
            "outcome_a": market_cfg.get("outcome_a", "YES"),
            "outcome_b": market_cfg.get("outcome_b", "NO"),
            "initial_probability": float(market_cfg.get("initial_probability", 0.5)),
        })

    # Build belief states.
    belief_states: Dict[int, BeliefState] = {}
    for agent in agents:
        agent_cfg = _get_agent_config(agent.agent_id, agent_configs)
        belief_states[agent.agent_id] = BeliefState.from_profile(agent_cfg, topics)

    logger.info(
        "Created polymarket bundle: %d agents, %d markets, db=%s",
        len(agents), len(markets_config), db_path,
    )

    return PlatformBundle(
        name="polymarket",
        platform=platform,
        channel=channel,
        db=platform.db,
        env=env,
        agents=agents,
        belief_states=belief_states,
    )


# ======================================================================
# Helpers
# ======================================================================

def _get_agent_config(agent_id: int, agent_configs: Any) -> Dict[str, Any]:
    """Look up per-agent config from the agents section of sim_config."""
    if isinstance(agent_configs, dict):
        return agent_configs.get(str(agent_id), {})
    if isinstance(agent_configs, list):
        for cfg in agent_configs:
            if cfg.get("agent_id") == agent_id or cfg.get("user_id") == agent_id:
                return cfg
    return {}


# ======================================================================
# Main factory
# ======================================================================

def create_environment(
    sim_config_data: Dict[str, Any],
    sim_dir: str,
    config: Any,
) -> OasisEnv:
    """Create a fully configured OasisEnv from simulation config.

    Args:
        sim_config_data: The simulation config dict (from simulation_config.json).
        sim_dir: Path to the simulation directory on disk.
        config: The app Config object (for LLM keys, etc.).

    Returns:
        A ready-to-run ``OasisEnv`` instance.
    """
    from app.utils.llm_client import LLMClient

    llm_client = LLMClient(config)

    # Extract topics from the simulation requirement.
    requirement = sim_config_data.get("simulation_requirement", "")
    topics = extract_topics_from_requirement(requirement, llm_client=None)
    logger.info("Extracted topics: %s", topics)

    agent_configs = sim_config_data.get("agents", {})

    # Load profiles for each platform.
    twitter_profiles = _load_profiles(sim_dir, "twitter")
    reddit_profiles = _load_profiles(sim_dir, "reddit")
    polymarket_profiles = _load_profiles(sim_dir, "polymarket")

    # If no per-platform profiles exist, try a combined profiles file.
    if not twitter_profiles and not reddit_profiles and not polymarket_profiles:
        combined_path = os.path.join(sim_dir, "profiles.json")
        if os.path.exists(combined_path):
            with open(combined_path) as f:
                all_profiles = json.load(f)
            logger.info("Loaded %d combined profiles", len(all_profiles))
            # Distribute profiles across platforms based on their config.
            twitter_profiles = all_profiles
            reddit_profiles = all_profiles
            polymarket_profiles = all_profiles

    # Determine recsys type.
    platform_cfg = sim_config_data.get("platform", {})
    recsys_name = platform_cfg.get("recsys", "random").upper()
    try:
        recsys_type = RecsysType[recsys_name]
    except KeyError:
        recsys_type = RecsysType.RANDOM

    # Build platform bundles.
    platforms: Dict[str, PlatformBundle] = {}

    twitter_bundle = _create_social_platform_bundle(
        "twitter", twitter_profiles, sim_dir, sim_config_data,
        llm_client, topics, agent_configs, recsys_type,
    )
    if twitter_bundle:
        platforms["twitter"] = twitter_bundle

    reddit_bundle = _create_social_platform_bundle(
        "reddit", reddit_profiles, sim_dir, sim_config_data,
        llm_client, topics, agent_configs, RecsysType.REDDIT,
    )
    if reddit_bundle:
        platforms["reddit"] = reddit_bundle

    poly_bundle = _create_polymarket_bundle(
        polymarket_profiles, sim_dir, sim_config_data,
        llm_client, topics, agent_configs,
    )
    if poly_bundle:
        platforms["polymarket"] = poly_bundle

    # Build the agent graph (all agents across all platforms).
    agent_graph = AgentGraph()
    for bundle in platforms.values():
        for agent in bundle.agents:
            agent_graph.add_agent(agent)

    # Clock.
    time_cfg = sim_config_data.get("time", {})
    time_acceleration = time_cfg.get("time_acceleration", 60)
    clock = Clock(time_acceleration=max(1, int(time_acceleration)))

    env = OasisEnv(
        platforms=platforms,
        agent_graph=agent_graph,
        sim_config=sim_config_data,
        sim_dir=sim_dir,
        clock=clock,
        llm_client=llm_client,
        topics=topics,
    )

    # Wire up Polymarket real-price anchoring if enabled
    polymarket_enabled = getattr(config, "polymarket_anchoring_enabled", False)
    if polymarket_enabled:
        try:
            from app.services.polymarket_client import PolymarketClient

            clob_url = getattr(config, "polymarket_clob_url", "https://clob.polymarket.com")
            pm_client = PolymarketClient(base_url=clob_url)

            # The market question is used to search for a matching Polymarket market
            market_question = sim_config_data.get("events", {}).get("market_question", "")

            def real_price_fetcher(market_id: int) -> float | None:
                result = pm_client.get_market_prices_for_question(market_question)
                if result:
                    return result[0]  # yes_price
                return None

            env.real_price_fetcher = real_price_fetcher
            logger.info("Polymarket real-price anchoring enabled for: %s", market_question[:60])
        except Exception as e:
            logger.warning("Failed to set up Polymarket anchoring: %s", e)

    logger.info(
        "OasisEnv created: %d platforms, %d total agents, %d rounds",
        len(platforms),
        agent_graph.get_num_nodes(),
        env.max_rounds,
    )

    return env
