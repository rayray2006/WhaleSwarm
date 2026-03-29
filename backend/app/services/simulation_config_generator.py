"""Simulation configuration generation via sequential LLM calls."""
import json
import logging
from typing import Any, Dict, List, Optional

from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


def _ensure_dict(result: Any) -> Dict:
    """Unwrap list wrappers from LLM JSON output."""
    if isinstance(result, list):
        return result[0] if result and isinstance(result[0], dict) else {}
    return result if isinstance(result, dict) else {}


class SimulationConfigGenerator:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def generate(
        self,
        profiles: List[Dict],
        simulation_requirement: str,
        max_rounds: int = 10,
        polymarket_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate full simulation config via 4 sequential LLM calls.

        Args:
            polymarket_config: If provided, overrides market settings and
                injects the fictional event into the schedule.
        """
        agent_names = [p.get("name", p.get("user_name", "unknown")) for p in profiles]

        # Step 1: Time config
        time_config = self._gen_time_config(simulation_requirement, max_rounds)

        # Step 2: Event config
        event_config = self._gen_event_config(simulation_requirement, agent_names)

        # Apply polymarket overrides to event config
        if polymarket_config:
            mq = polymarket_config.get("market_question")
            if mq:
                event_config["market_question"] = mq
            mp = polymarket_config.get("yes_price")
            if mp is not None:
                event_config["market_initial_probability"] = mp

            # Inject the fictional event as a round-based scheduled event
            fictional = polymarket_config.get("fictional_event")
            event_round = polymarket_config.get("event_round", 5)
            if fictional:
                scheduled = event_config.get("scheduled_events", [])
                scheduled.append({
                    "round": event_round,
                    "description": fictional,
                    "platforms": ["twitter", "reddit", "polymarket"],
                })
                event_config["scheduled_events"] = scheduled

        # Step 3: Agent activity configs (batched)
        agent_configs = self._gen_agent_configs(profiles, simulation_requirement)

        # Step 4: Platform config
        platform_config = self._gen_platform_config(simulation_requirement, len(profiles))

        return {
            "time": time_config,
            "events": event_config,
            "agents": agent_configs,
            "platform": platform_config,
            "max_rounds": max_rounds,
        }

    def _gen_time_config(self, requirement: str, max_rounds: int) -> Dict:
        messages = [
            {"role": "system", "content": """Generate a time simulation config. Return JSON:
{
  "total_simulation_hours": <int>,
  "minutes_per_round": <int>,
  "agents_per_hour": <int>,
  "peak_hours": [<ints>],
  "off_peak_hours": [<ints>],
  "peak_multiplier": <float>,
  "off_peak_multiplier": <float>,
  "work_hour_multiplier": <float>,
  "evening_multiplier": <float>
}"""},
            {"role": "user", "content": f"Simulation: {requirement}\nMax rounds: {max_rounds}"},
        ]
        try:
            return _ensure_dict(self.llm.complete_json(messages, smart=True, temperature=0.5))
        except Exception as e:
            logger.warning(f"Time config gen failed, using defaults: {e}")
            return {
                "total_simulation_hours": 24,
                "minutes_per_round": 30,
                "agents_per_hour": 10,
                "peak_hours": [19, 20, 21, 22],
                "off_peak_hours": [0, 1, 2, 3, 4, 5],
                "peak_multiplier": 1.5,
                "off_peak_multiplier": 0.05,
                "work_hour_multiplier": 0.7,
                "evening_multiplier": 1.2,
            }

    def _gen_event_config(self, requirement: str, agent_names: List[str]) -> Dict:
        messages = [
            {"role": "system", "content": """Generate event config for a multi-platform simulation. Return JSON:
{
  "initial_posts": ["post1", "post2", ...],
  "scheduled_events": [{"hour": <int>, "event": "<str>", "platform": "<twitter|reddit|polymarket>"}],
  "hot_topic_keywords": ["keyword1", ...],
  "market_question": "<prediction market question>",
  "market_initial_probability": <float 0-1>,
  "market_outcome_a": "YES",
  "market_outcome_b": "NO"
}

Initial posts should seed conversation. The market question should be debatable and related to the simulation topic."""},
            {"role": "user", "content": f"Simulation: {requirement}\nAgents: {', '.join(agent_names[:20])}"},
        ]
        try:
            return _ensure_dict(self.llm.complete_json(messages, smart=True, temperature=0.7))
        except Exception as e:
            logger.warning(f"Event config gen failed, using defaults: {e}")
            return {
                "initial_posts": [f"What are your thoughts on: {requirement[:100]}?"],
                "scheduled_events": [],
                "hot_topic_keywords": [],
                "market_question": f"Will the outcome be favorable? ({requirement[:50]})",
                "market_initial_probability": 0.5,
                "market_outcome_a": "YES",
                "market_outcome_b": "NO",
            }

    def _gen_agent_configs(self, profiles: List[Dict], requirement: str) -> List[Dict]:
        agent_configs = []
        batch_size = 10

        for i in range(0, len(profiles), batch_size):
            batch = profiles[i:i + batch_size]
            batch_info = [
                f"- {p.get('name', 'unknown')} ({p.get('profession', 'unknown')})"
                for p in batch
            ]

            messages = [
                {"role": "system", "content": """Generate activity config for each agent. Return JSON array:
[{
  "agent_id": "<user_id>",
  "activity_level": "<high|medium|low|lurker>",
  "posts_per_hour": <float>,
  "comments_per_hour": <float>,
  "active_hours": [<ints>],
  "response_delay": <int rounds>,
  "sentiment_bias": <float -1 to 1>,
  "stance": "<supportive|opposing|neutral|observer|strongly_supportive|strongly_opposing>",
  "influence_weight": <float 0-2>
}]"""},
                {"role": "user", "content": f"Simulation: {requirement}\n\nAgents:\n" + "\n".join(batch_info)},
            ]

            try:
                batch_configs = self.llm.complete_json(messages, smart=False, temperature=0.7)
                if isinstance(batch_configs, list):
                    # Match configs to profiles
                    for j, cfg in enumerate(batch_configs):
                        if j < len(batch):
                            cfg["agent_id"] = batch[j].get("user_id", str(j))
                        agent_configs.append(cfg)
                    continue
            except Exception as e:
                logger.warning(f"Agent config batch failed: {e}")

            # Fallback: generate default configs
            for p in batch:
                agent_configs.append({
                    "agent_id": p.get("user_id", ""),
                    "activity_level": "medium",
                    "posts_per_hour": 0.5,
                    "comments_per_hour": 1.0,
                    "active_hours": [9, 10, 11, 14, 15, 19, 20, 21],
                    "response_delay": 1,
                    "sentiment_bias": 0.0,
                    "stance": "neutral",
                    "influence_weight": 1.0,
                })

        return agent_configs

    def _gen_platform_config(self, requirement: str, agent_count: int) -> Dict:
        messages = [
            {"role": "system", "content": """Generate platform config. Return JSON:
{
  "viral_threshold": <int likes for viral>,
  "echo_chamber_strength": <float 0-1>,
  "recommendation_weights": {"recency": <float>, "popularity": <float>, "relevance": <float>},
  "max_rec_post_len": <int max posts shown>,
  "recsys_type": "<twitter|reddit|random>"
}"""},
            {"role": "user", "content": f"Simulation: {requirement}\nAgent count: {agent_count}"},
        ]
        try:
            return _ensure_dict(self.llm.complete_json(messages, smart=False, temperature=0.5))
        except Exception as e:
            logger.warning(f"Platform config gen failed, using defaults: {e}")
            return {
                "viral_threshold": max(3, agent_count // 5),
                "echo_chamber_strength": 0.3,
                "recommendation_weights": {"recency": 0.4, "popularity": 0.3, "relevance": 0.3},
                "max_rec_post_len": 30,
                "recsys_type": "reddit",
            }
