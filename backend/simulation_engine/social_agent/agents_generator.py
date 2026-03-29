"""Factory for creating a list of SocialAgent instances from profiles."""

import logging
from typing import Any, Dict, List, Optional, Type

from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.config.user import UserInfo
from simulation_engine.simulations.base import (
    BaseAction,
    BaseEnvironment,
    BasePromptBuilder,
)
from simulation_engine.social_agent.agent import SocialAgent

logger = logging.getLogger(__name__)


def generate_agents(
    profiles: List[Dict[str, Any]],
    channel: Channel,
    env: BaseEnvironment,
    action_cls: Type[BaseAction],
    prompt_builder: BasePromptBuilder,
    llm_client: Any = None,
    max_iterations: int = 1,
) -> List[SocialAgent]:
    """Create one :class:`SocialAgent` per profile dict.

    Each profile dict is expected to have at least the following keys
    (matching ``OasisAgentProfile.to_*_format()`` output):

    - ``user_id`` (int or str) — used as ``agent_id``
    - ``name`` or ``realname`` — display name
    - ``bio`` or ``description`` or ``persona`` — agent persona text

    Additional keys are stored in ``UserInfo.profile`` for use by the
    prompt builder and belief-state system.

    Args:
        profiles: List of profile dicts (one per agent).
        channel: Shared async channel connecting agents to the platform.
        env: The platform environment (shared; each agent reads their own
            view via ``agent_id``).
        action_cls: Concrete ``BaseAction`` subclass to instantiate per
            agent.
        prompt_builder: Builds the system prompt from ``UserInfo``.
        llm_client: ``LLMClient`` instance (from ``app.utils``).
        max_iterations: Max tool-call iterations per ``perform_action_by_llm``.

    Returns:
        List of fully initialised ``SocialAgent`` instances.
    """
    agents: List[SocialAgent] = []

    for idx, profile in enumerate(profiles):
        # Always use sequential integer IDs for the simulation.
        # Profile user_ids may be hex strings (e.g. "96123507") that parse
        # as huge integers, which would break _agent_count / rec_matrix sizing.
        agent_id = idx

        # Resolve display name.
        name = (
            profile.get("name")
            or profile.get("realname")
            or profile.get("user_name")
            or f"Agent-{agent_id}"
        )

        # Resolve description/persona.
        description = (
            profile.get("persona")
            or profile.get("description")
            or profile.get("bio")
            or profile.get("user_char")
            or ""
        )

        user_info = UserInfo(
            name=name,
            description=description,
            profile=profile,
            agent_id=agent_id,
        )

        # Instantiate the action handler for this agent.
        action = action_cls(agent_id=agent_id, channel=channel)

        # Build the system prompt.
        system_message = prompt_builder.build_system_prompt(user_info)

        agent = SocialAgent(
            agent_id=agent_id,
            user_info=user_info,
            channel=channel,
            env=env,
            action=action,
            system_message=system_message,
            llm_client=llm_client,
            max_iterations=max_iterations,
        )

        agents.append(agent)
        logger.debug("Created agent %d: %s", agent_id, name)

    logger.info("Generated %d agents", len(agents))
    return agents
