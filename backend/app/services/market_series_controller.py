"""Market series controller for multi-market agent evolution.

Extension B of the Convergence PRD.  Runs a sequence of prediction
markets, carrying agent state (wallets, performance, model tiers)
across markets and evolving the agent pool between rounds.

The evolution loop:
1. Run a market simulation.
2. Resolve the market and settle positions.
3. Update persistent wallet balances from the SQLite DB.
4. Kill bankrupt agents, spawn replacements from the knowledge graph.
5. Promote top performers to higher model tiers.
6. Condense each agent's track record into a prompt fragment.
7. Repeat for the next market.
"""

from __future__ import annotations

import json
import logging
import math
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from app.config import Config
from app.models.persistent_agent import (
    MODEL_TIER_MAP,
    MarketSeriesConfig,
    MarketSpec,
    PersistentAgentState,
)
from app.services.simulation_manager import SimulationManager, SimulationState

logger = logging.getLogger(__name__)


class MarketSeriesController:
    """Orchestrate a multi-market evolution series.

    Parameters
    ----------
    series_config:
        The :class:`MarketSeriesConfig` defining the markets and
        evolution parameters.
    config:
        Application-level configuration.
    """

    def __init__(
        self,
        series_config: MarketSeriesConfig,
        config: Config,
    ) -> None:
        self.series_config = series_config
        self.config = config
        self.sim_manager = SimulationManager(config)

        # Agent pool -- keyed by agent_id
        self.agents: Dict[int, PersistentAgentState] = {}
        self.next_agent_id: int = 0

        # Track which entity UUIDs are in use (to avoid duplicates)
        self._used_entity_uuids: Set[str] = set()

        # Series output directory
        self.series_dir = os.path.join(
            config.upload_dir, "series", series_config.series_id or str(uuid.uuid4())
        )
        os.makedirs(self.series_dir, exist_ok=True)

        # Results accumulator
        self.market_results: List[Dict[str, Any]] = []

    # ----------------------------------------------------------------
    # Main entry point
    # ----------------------------------------------------------------

    async def run_series(self) -> Dict[str, Any]:
        """Run the full market series.

        For each market in the series config:
        1. Build a simulation graph with the current agent pool.
        2. Run the simulation.
        3. Resolve the market and update wallets.
        4. Evolve the agent pool (kill, replace, promote).

        Returns a summary dict of the entire series.
        """
        logger.info(
            "Starting market series '%s' with %d markets, %d initial agents",
            self.series_config.series_name,
            len(self.series_config.markets),
            self.series_config.initial_agent_count,
        )

        # Initialize the agent pool from the first graph
        self._initial_agent_pool()

        for idx, market_spec in enumerate(self.series_config.markets):
            logger.info(
                "=== Market %d/%d: %s ===",
                idx + 1,
                len(self.series_config.markets),
                market_spec.question,
            )

            # Build graph and create simulation
            sim_state = self._create_simulation(market_spec, idx)

            # Run the simulation (placeholder -- actual execution depends
            # on the simulation runner infrastructure)
            await self._run_simulation(sim_state, market_spec)

            # Resolve market and settle positions
            market_result = self._resolve_market(sim_state, market_spec, idx)
            self.market_results.append(market_result)

            # Update persistent wallets from SQLite
            self._update_persistent_wallets(sim_state)

            # Evolve the agent pool
            evolution_summary = self.evolve_agent_pool()

            # Condense track records for next market's prompts
            self.condense_for_next_market()

            # Save checkpoint
            self._save_checkpoint(idx, evolution_summary)

            logger.info(
                "Market %d complete. Pool: %d agents, %d killed, %d replaced",
                idx + 1,
                len(self.agents),
                evolution_summary.get("killed", 0),
                evolution_summary.get("replaced", 0),
            )

        # Final summary
        summary = self._build_series_summary()
        self._save_series_summary(summary)
        return summary

    # ----------------------------------------------------------------
    # Agent pool initialization
    # ----------------------------------------------------------------

    def _initial_agent_pool(self) -> None:
        """Create the initial agent pool.

        In a full integration this would call
        ``OasisProfileGenerator.generate_profiles()`` against the
        knowledge graph.  Here we create placeholder persistent states
        that will be populated when the first simulation runs.
        """
        count = self.series_config.initial_agent_count
        initial_balance = self.series_config.initial_balance

        for i in range(count):
            agent_id = self._next_id()
            state = PersistentAgentState(
                agent_id=agent_id,
                name=f"Agent_{agent_id}",
                persona="",
                wallet_balance=initial_balance,
                model_tier="base",
                risk_profile="moderate",
            )
            self.agents[agent_id] = state

        logger.info("Initialized pool with %d agents at $%.2f each", count, initial_balance)

    def _next_id(self) -> int:
        """Return the next available agent ID."""
        agent_id = self.next_agent_id
        self.next_agent_id += 1
        return agent_id

    # ----------------------------------------------------------------
    # Simulation creation
    # ----------------------------------------------------------------

    def _create_simulation(
        self,
        market_spec: MarketSpec,
        market_idx: int,
    ) -> SimulationState:
        """Create a new simulation state for one market.

        The simulation is configured with persistent wallet balances
        so that each agent starts with their carried-over balance.
        """
        sim_state = SimulationState(
            project_id=self.series_config.graph_id,
            graph_id=self.series_config.graph_id,
            name=f"Series_{self.series_config.series_id}_Market_{market_idx}",
            simulation_requirement=market_spec.question,
        )
        sim_state = self.sim_manager.create(sim_state)

        # Save agent profiles with persistent balances
        profiles = []
        for agent in self.agents.values():
            profiles.append({
                "agent_id": agent.agent_id,
                "user_name": agent.name.lower().replace(" ", "_"),
                "name": agent.name,
                "persona": agent.persona,
                "risk_tolerance": agent.risk_profile,
                "wallet_balance": agent.wallet_balance,
                "model_tier": agent.model_tier,
                "model_name": agent.model_name,
                "source_entity_uuid": agent.source_entity_uuid,
            })
        self.sim_manager.save_profiles(sim_state.simulation_id, profiles, "polymarket")

        # Save market config
        market_config = {
            "market": market_spec.to_dict(),
            "agent_count": len(self.agents),
            "market_cohort": self.series_config.market_cohort,
            "series_id": self.series_config.series_id,
            "market_idx": market_idx,
        }
        self.sim_manager.save_config(sim_state.simulation_id, market_config)

        return sim_state

    # ----------------------------------------------------------------
    # Simulation execution
    # ----------------------------------------------------------------

    async def _run_simulation(
        self,
        sim_state: SimulationState,
        market_spec: MarketSpec,
    ) -> None:
        """Run the simulation for one market.

        This is a placeholder that would integrate with the actual
        simulation runner (``SimulationIPC`` / ``simulation_runner``).
        The real implementation would:
        1. Build the OASIS graph with agent profiles.
        2. Create the Polymarket platform with the market question.
        3. Run ``max_rounds`` of agent actions.
        4. Store the SQLite DB path on ``sim_state``.
        """
        logger.info(
            "Running simulation %s for market: %s (max_rounds=%d)",
            sim_state.simulation_id,
            market_spec.question,
            market_spec.max_rounds,
        )
        # In production, this would be:
        # runner = SimulationRunner(self.config)
        # await runner.run(sim_state)
        sim_state.status = "completed"
        self.sim_manager.save(sim_state)

    # ----------------------------------------------------------------
    # Market resolution
    # ----------------------------------------------------------------

    def _resolve_market(
        self,
        sim_state: SimulationState,
        market_spec: MarketSpec,
        market_idx: int,
    ) -> Dict[str, Any]:
        """Resolve a market and compute agent-level P&L.

        For backtesting (``winning_outcome`` is set), each agent's
        positions are settled against the known outcome.  For forward
        simulations, resolution is deferred.

        Returns a result dict for the series log.
        """
        winning = market_spec.winning_outcome
        if not winning:
            logger.info("No winning_outcome set; skipping resolution for market %d", market_idx)
            return {
                "market_idx": market_idx,
                "question": market_spec.question,
                "resolved": False,
                "agent_results": {},
            }

        logger.info("Resolving market %d with outcome: %s", market_idx, winning)

        # In production, read positions from the simulation's SQLite DB:
        # db_path = os.path.join(
        #     self.sim_manager.get_sim_dir(sim_state.simulation_id),
        #     "polymarket.db",
        # )
        # db = sqlite3.connect(db_path)
        # positions = db.execute("SELECT * FROM position").fetchall()

        # Placeholder: record zero P&L for each agent
        agent_results = {}
        for agent_id, agent in self.agents.items():
            pnl = 0.0  # Would be computed from actual positions
            edge = 0.0

            agent.record_market_result(
                market_idx=market_idx,
                pnl=pnl,
                outcome=winning,
                edge_captured=edge,
                category=market_spec.category,
            )

            agent_results[agent_id] = {
                "pnl": pnl,
                "new_balance": agent.wallet_balance,
            }

        return {
            "market_idx": market_idx,
            "question": market_spec.question,
            "winning_outcome": winning,
            "resolved": True,
            "agent_results": agent_results,
        }

    # ----------------------------------------------------------------
    # Persistent wallet sync
    # ----------------------------------------------------------------

    def _update_persistent_wallets(self, sim_state: SimulationState) -> None:
        """Read final balances from the simulation's SQLite DB.

        Updates each agent's ``wallet_balance`` in the persistent state.

        In production this reads from the ``portfolio`` table:
        ``SELECT user_id, balance FROM portfolio``
        """
        # In production:
        # import sqlite3
        # db_path = os.path.join(
        #     self.sim_manager.get_sim_dir(sim_state.simulation_id),
        #     "polymarket.db",
        # )
        # if not os.path.exists(db_path):
        #     logger.warning("No DB found at %s; skipping wallet update", db_path)
        #     return
        #
        # conn = sqlite3.connect(db_path)
        # conn.row_factory = sqlite3.Row
        # rows = conn.execute("SELECT user_id, balance FROM portfolio").fetchall()
        # for row in rows:
        #     agent_id = int(row["user_id"])
        #     if agent_id in self.agents:
        #         self.agents[agent_id].wallet_balance = float(row["balance"])
        # conn.close()

        logger.info("Updated persistent wallets for %d agents", len(self.agents))

    # ----------------------------------------------------------------
    # Agent pool evolution
    # ----------------------------------------------------------------

    def evolve_agent_pool(self) -> Dict[str, Any]:
        """Evolve the agent pool between markets.

        Steps:
        1. Kill bankrupt agents (balance <= kill_threshold).
        2. Spawn replacement agents from the knowledge graph.
        3. Update model tiers based on performance percentiles:
           - Top 0.1% (elite) -> top tier
           - Top 1% (whale) -> mid tier
           - Everyone else -> base tier

        Returns a summary dict.
        """
        kill_threshold = self.series_config.kill_threshold
        whale_pct = self.series_config.whale_threshold_percentile
        elite_pct = self.series_config.elite_threshold_percentile

        # -- Step 1: Kill bankrupt agents --
        killed_ids = []
        for agent_id, agent in list(self.agents.items()):
            if agent.wallet_balance <= kill_threshold:
                killed_ids.append(agent_id)
                self._used_entity_uuids.discard(agent.source_entity_uuid)

        for agent_id in killed_ids:
            del self.agents[agent_id]

        logger.info("Killed %d bankrupt agents", len(killed_ids))

        # -- Step 2: Spawn replacements --
        replacements_needed = len(killed_ids)
        replaced_ids = []

        if replacements_needed > 0:
            new_agents = self._generate_replacement_profiles(replacements_needed)
            for agent in new_agents:
                self.agents[agent.agent_id] = agent
                replaced_ids.append(agent.agent_id)

        logger.info("Spawned %d replacement agents", len(replaced_ids))

        # -- Step 3: Update model tiers --
        if not self.agents:
            return {
                "killed": len(killed_ids),
                "replaced": len(replaced_ids),
                "tier_changes": {},
            }

        # Sort by total P&L descending
        sorted_agents = sorted(
            self.agents.values(),
            key=lambda a: a.total_pnl,
            reverse=True,
        )
        n = len(sorted_agents)

        # Compute thresholds
        elite_cutoff = max(1, math.ceil(n * elite_pct))
        whale_cutoff = max(elite_cutoff + 1, math.ceil(n * whale_pct))

        tier_changes: Dict[str, int] = {"top": 0, "mid": 0, "base": 0}

        for rank, agent in enumerate(sorted_agents):
            old_tier = agent.model_tier

            if rank < elite_cutoff:
                agent.model_tier = "top"
            elif rank < whale_cutoff:
                agent.model_tier = "mid"
            else:
                agent.model_tier = "base"

            tier_changes[agent.model_tier] = tier_changes.get(agent.model_tier, 0) + 1

            if agent.model_tier != old_tier:
                logger.debug(
                    "Agent %d (%s): %s -> %s (PnL=$%.2f)",
                    agent.agent_id, agent.name, old_tier, agent.model_tier, agent.total_pnl,
                )

        return {
            "killed": len(killed_ids),
            "killed_ids": killed_ids,
            "replaced": len(replaced_ids),
            "replaced_ids": replaced_ids,
            "tier_changes": tier_changes,
            "pool_size": len(self.agents),
        }

    def _generate_replacement_profiles(
        self,
        count: int,
    ) -> List[PersistentAgentState]:
        """Generate replacement agent profiles.

        In a full integration this calls
        ``OasisProfileGenerator.generate_replacement_profiles()``
        with ``exclude_entity_uuids=self._used_entity_uuids``.

        For now, creates fresh agents with default parameters.
        """
        # In production:
        # from app.services.oasis_profile_generator import OasisProfileGenerator
        # from app.storage.neo4j_storage import Neo4jStorage
        # from app.utils.llm_client import LLMClient
        #
        # storage = Neo4jStorage(self.config)
        # llm = LLMClient(self.config)
        # generator = OasisProfileGenerator(self.config, storage, llm)
        # profiles = generator.generate_replacement_profiles(
        #     graph_id=self.series_config.graph_id,
        #     count=count,
        #     exclude_entity_uuids=self._used_entity_uuids,
        # )
        # return [self._profile_to_persistent_state(p) for p in profiles]

        initial_balance = self.series_config.initial_balance
        new_agents = []
        for i in range(count):
            agent_id = self._next_id()
            agent = PersistentAgentState(
                agent_id=agent_id,
                name=f"Replacement_{agent_id}",
                persona="",
                wallet_balance=initial_balance,
                model_tier="base",
                risk_profile="moderate",
            )
            new_agents.append(agent)

        return new_agents

    # ----------------------------------------------------------------
    # Track record condensation
    # ----------------------------------------------------------------

    def condense_for_next_market(self) -> None:
        """Generate a performance signature for each agent's system prompt.

        This is injected into the ``track_record`` field of
        :class:`PolymarketPromptBuilder` so the agent "remembers" its
        past performance.
        """
        for agent in self.agents.values():
            signature = self._build_performance_signature(agent)
            # The persona field is updated to include the track record.
            # The prompt builder will pick this up via the track_record kwarg.
            agent.persona = self._inject_track_record(agent.persona, signature)

    @staticmethod
    def _build_performance_signature(agent: PersistentAgentState) -> str:
        """Build a compact performance string for the agent's prompt.

        Format example::

            [TRACK RECORD] 12 markets | W/L: 8/4 (67%) |
            PnL: +$342.50 | Avg Edge: 0.08 | Balance: $1,342.50 |
            Tier: mid | Best: politics, crypto
        """
        if agent.markets_participated == 0:
            return "[TRACK RECORD] No markets completed yet."

        win_pct = round(agent.win_rate * 100, 1)
        pnl_sign = "+" if agent.total_pnl >= 0 else ""
        categories = ", ".join(agent.best_categories[:3]) if agent.best_categories else "none"

        return (
            f"[TRACK RECORD] {agent.markets_participated} markets | "
            f"W/L: {agent.trades_won}/{agent.trades_lost} ({win_pct}%) | "
            f"PnL: {pnl_sign}${agent.total_pnl:.2f} | "
            f"Avg Edge: {agent.avg_edge_captured:.3f} | "
            f"Balance: ${agent.wallet_balance:.2f} | "
            f"Tier: {agent.model_tier} | "
            f"Best: {categories}"
        )

    @staticmethod
    def _inject_track_record(persona: str, track_record: str) -> str:
        """Replace or append the track record in the persona string."""
        marker = "[TRACK RECORD]"
        if marker in persona:
            # Replace existing track record line
            lines = persona.split("\n")
            new_lines = []
            for line in lines:
                if marker in line:
                    new_lines.append(track_record)
                else:
                    new_lines.append(line)
            return "\n".join(new_lines)
        else:
            # Append
            if persona:
                return f"{persona}\n{track_record}"
            return track_record

    # ----------------------------------------------------------------
    # Checkpointing & summaries
    # ----------------------------------------------------------------

    def _save_checkpoint(self, market_idx: int, evolution: Dict) -> None:
        """Save the current agent pool state to disk."""
        checkpoint = {
            "market_idx": market_idx,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "pool_size": len(self.agents),
            "evolution": evolution,
            "agents": {
                str(aid): agent.to_dict()
                for aid, agent in self.agents.items()
            },
        }
        path = os.path.join(self.series_dir, f"checkpoint_market_{market_idx}.json")
        with open(path, "w") as f:
            json.dump(checkpoint, f, indent=2)

    def _build_series_summary(self) -> Dict[str, Any]:
        """Build the final summary of the series."""
        if not self.agents:
            return {
                "series_id": self.series_config.series_id,
                "series_name": self.series_config.series_name,
                "markets_run": len(self.market_results),
                "final_pool_size": 0,
                "agents": [],
            }

        sorted_agents = sorted(
            self.agents.values(),
            key=lambda a: a.total_pnl,
            reverse=True,
        )

        balances = [a.wallet_balance for a in sorted_agents]
        pnls = [a.total_pnl for a in sorted_agents]

        return {
            "series_id": self.series_config.series_id,
            "series_name": self.series_config.series_name,
            "markets_run": len(self.market_results),
            "final_pool_size": len(self.agents),
            "balance_stats": {
                "mean": sum(balances) / len(balances),
                "median": sorted(balances)[len(balances) // 2],
                "min": min(balances),
                "max": max(balances),
            },
            "pnl_stats": {
                "mean": sum(pnls) / len(pnls),
                "total_positive": sum(p for p in pnls if p > 0),
                "total_negative": sum(p for p in pnls if p < 0),
            },
            "tier_distribution": {
                "top": sum(1 for a in sorted_agents if a.model_tier == "top"),
                "mid": sum(1 for a in sorted_agents if a.model_tier == "mid"),
                "base": sum(1 for a in sorted_agents if a.model_tier == "base"),
            },
            "top_10_agents": [a.to_dict() for a in sorted_agents[:10]],
            "market_results": self.market_results,
        }

    def _save_series_summary(self, summary: Dict) -> None:
        """Write the final series summary to disk."""
        path = os.path.join(self.series_dir, "series_summary.json")
        with open(path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info("Series summary saved to %s", path)
