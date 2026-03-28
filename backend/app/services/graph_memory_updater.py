"""Background Neo4j updater -- enrich the knowledge graph with simulation findings.

Reads simulation output (actions.jsonl, platform DBs) and creates/updates
Neo4j entities for agent positions, beliefs, and notable events discovered
during a simulation run.
"""

from __future__ import annotations

import json
import logging
import os
import uuid as uuid_mod
from typing import Any, Dict, List, Optional

from app.config import Config
from app.services.simulation_ipc import (
    get_recent_actions,
    get_trades_from_db,
    parse_actions_jsonl,
)
from app.storage.neo4j_storage import Neo4jStorage
from app.utils.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)


class GraphMemoryUpdater:
    """Update Neo4j with simulation findings (agent positions, beliefs, events)."""

    def __init__(
        self,
        storage: Neo4jStorage,
        embedder: EmbeddingService,
        config: Config,
    ):
        self.storage = storage
        self.embedder = embedder
        self.config = config

    def update_from_simulation(
        self,
        graph_id: str,
        sim_dir: str,
    ) -> Dict[str, int]:
        """Read simulation outputs and push discoveries into Neo4j.

        Creates:
        - Agent entities with their final positions / belief summaries
        - Event entities for notable simulation events
        - Relationships between agents and entities they interacted with

        Returns:
            Dict with counts: entities_added, edges_added.
        """
        logger.info(
            "GraphMemoryUpdater: updating graph %s from %s", graph_id, sim_dir
        )

        entities_added = 0
        edges_added = 0

        # ------------------------------------------------------------------
        # 1. Extract agent summaries from actions
        # ------------------------------------------------------------------
        agent_summaries = self._extract_agent_summaries(sim_dir)

        if agent_summaries:
            agent_entities = []
            for agent_id, summary in agent_summaries.items():
                text = (
                    f"Agent {summary['name']}: "
                    f"{summary['action_count']} actions across platforms "
                    f"{', '.join(summary['platforms'])}. "
                    f"Primary actions: {', '.join(summary['top_actions'])}."
                )
                embedding = self.embedder.embed(text)
                agent_entities.append({
                    "uuid": f"sim-agent-{agent_id}",
                    "name": summary["name"],
                    "type": "SimulationAgent",
                    "summary": text,
                    "attributes": json.dumps({
                        "agent_id": agent_id,
                        "action_count": summary["action_count"],
                        "platforms": summary["platforms"],
                        "top_actions": summary["top_actions"],
                    }),
                    "embedding": embedding,
                })

            try:
                self.storage.add_entities_batch(agent_entities, graph_id)
                entities_added += len(agent_entities)
                logger.info("Added %d agent entities", len(agent_entities))
            except Exception:
                logger.exception("Failed to add agent entities")

        # ------------------------------------------------------------------
        # 2. Extract trading positions
        # ------------------------------------------------------------------
        trade_entities, trade_edges = self._extract_trade_positions(sim_dir, graph_id)

        if trade_entities:
            try:
                self.storage.add_entities_batch(trade_entities, graph_id)
                entities_added += len(trade_entities)
            except Exception:
                logger.exception("Failed to add trade entities")

        if trade_edges:
            try:
                self.storage.add_edges_batch(trade_edges, graph_id)
                edges_added += len(trade_edges)
            except Exception:
                logger.exception("Failed to add trade edges")

        # ------------------------------------------------------------------
        # 3. Create a simulation summary entity
        # ------------------------------------------------------------------
        try:
            actions = parse_actions_jsonl(sim_dir)
            sim_end = [a for a in actions if a.get("type") == "simulation_end"]
            rounds = 0
            if sim_end:
                rounds = sim_end[-1].get("rounds_completed", 0)
            total_actions = len([a for a in actions if a.get("type") == "agent_action"])

            summary_text = (
                f"Simulation completed {rounds} rounds with {total_actions} agent actions "
                f"and {len(agent_summaries)} active agents."
            )
            embedding = self.embedder.embed(summary_text)
            self.storage.add_entities_batch(
                [{
                    "uuid": f"sim-summary-{graph_id}",
                    "name": "Simulation Summary",
                    "type": "SimulationEvent",
                    "summary": summary_text,
                    "attributes": json.dumps({
                        "rounds": rounds,
                        "total_actions": total_actions,
                        "agent_count": len(agent_summaries),
                    }),
                    "embedding": embedding,
                }],
                graph_id,
            )
            entities_added += 1
        except Exception:
            logger.debug("Failed to create simulation summary entity", exc_info=True)

        result = {"entities_added": entities_added, "edges_added": edges_added}
        logger.info("GraphMemoryUpdater: done -- %s", result)
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_agent_summaries(self, sim_dir: str) -> Dict[str, Dict]:
        """Summarize each agent's behavior from actions.jsonl."""
        actions = parse_actions_jsonl(sim_dir)
        agents: Dict[str, Dict] = {}

        for action in actions:
            if action.get("type") != "agent_action":
                continue

            agent_id = action.get("agent_id", "unknown")
            if agent_id not in agents:
                agents[agent_id] = {
                    "name": action.get("agent_name", agent_id),
                    "action_count": 0,
                    "platforms": set(),
                    "action_types": {},
                }

            info = agents[agent_id]
            info["action_count"] += 1
            platform = action.get("platform", "unknown")
            info["platforms"].add(platform)
            action_name = action.get("action", "unknown")
            info["action_types"][action_name] = info["action_types"].get(action_name, 0) + 1

        # Convert sets and compute top actions
        for agent_id, info in agents.items():
            info["platforms"] = sorted(info["platforms"])
            sorted_actions = sorted(
                info["action_types"].items(), key=lambda x: x[1], reverse=True
            )
            info["top_actions"] = [a[0] for a in sorted_actions[:3]]

        return agents

    def _extract_trade_positions(
        self, sim_dir: str, graph_id: str
    ) -> tuple:
        """Extract notable trading positions as entities + edges."""
        entities = []
        edges = []

        trades = get_trades_from_db(sim_dir, limit=200)
        if not trades:
            return entities, edges

        # Group trades by user
        user_trades: Dict[str, List[Dict]] = {}
        for trade in trades:
            user_id = str(trade.get("user_id", "unknown"))
            user_trades.setdefault(user_id, []).append(trade)

        # Create position entities for users with significant trading activity
        for user_id, user_trade_list in user_trades.items():
            if len(user_trade_list) < 2:
                continue  # skip minor traders

            user_name = user_trade_list[0].get("user_name", user_id)
            buy_count = sum(1 for t in user_trade_list if t.get("side") == "buy")
            sell_count = sum(1 for t in user_trade_list if t.get("side") == "sell")

            summary = (
                f"Trader {user_name}: {len(user_trade_list)} trades "
                f"({buy_count} buys, {sell_count} sells)"
            )
            embedding = self.embedder.embed(summary)

            entity_uuid = f"sim-trader-{user_id}"
            entities.append({
                "uuid": entity_uuid,
                "name": f"Trader: {user_name}",
                "type": "TraderPosition",
                "summary": summary,
                "attributes": json.dumps({
                    "user_id": user_id,
                    "trade_count": len(user_trade_list),
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                }),
                "embedding": embedding,
            })

            # Link to the corresponding agent entity if it exists
            agent_uuid = f"sim-agent-{user_id}"
            edges.append({
                "uuid": str(uuid_mod.uuid4()),
                "name": "TRADED_AS",
                "fact": summary,
                "source_node_uuid": agent_uuid,
                "target_node_uuid": entity_uuid,
            })

        return entities, edges
