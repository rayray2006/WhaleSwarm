"""Graph retrieval tools with increasing power for report generation.

Three retrieval strategies:
- QuickSearch: fast cosine similarity against entity embeddings
- PanoramaSearch: breadth-first, fetches nodes + all relationships
- InsightForge: deep multi-step with LLM-generated sub-questions
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import Config
from app.storage.neo4j_storage import Neo4jStorage
from app.utils.embedding_service import EmbeddingService
from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


@dataclass
class InsightForgeResult:
    """Aggregated result from deep InsightForge retrieval."""

    query: str
    simulation_requirement: str
    sub_queries: List[str]
    semantic_facts: List[str]
    entity_insights: List[Dict]
    relationship_chains: List[str]


class GraphToolsService:
    """Provides three tiers of graph retrieval for the report agent."""

    def __init__(
        self,
        storage: Neo4jStorage,
        llm: LLMClient,
        embedder: EmbeddingService,
        config: Config,
    ):
        self.storage = storage
        self.llm = llm
        self.embedder = embedder
        self.config = config

    # ------------------------------------------------------------------
    # QuickSearch -- fastest, embedding similarity only
    # ------------------------------------------------------------------

    def quick_search(
        self,
        query: str,
        graph_id: str,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Embed *query*, cosine-similarity against entity embeddings, return top-K.

        Each result dict contains: uuid, name, summary, type, score.
        """
        logger.info("QuickSearch: query=%r graph_id=%s top_k=%d", query, graph_id, top_k)
        embedding = self.embedder.embed(query)
        results = self.storage.search_by_embedding(embedding, graph_id, top_k=top_k)
        logger.info("QuickSearch: returned %d results", len(results))
        return results

    # ------------------------------------------------------------------
    # PanoramaSearch -- breadth: nodes + all relationships
    # ------------------------------------------------------------------

    def panorama_search(
        self,
        query: str,
        graph_id: str,
        top_k: int = 8,
    ) -> List[Dict[str, Any]]:
        """Get a comprehensive view of a topic: matching nodes with all relationships.

        Returns a list of enriched node dicts, each containing:
        - uuid, name, summary, type, score  (from embedding search)
        - relationships: list of relationship dicts  (from graph traversal)
        - relationship_chains: human-readable strings like "A --rel--> B"
        """
        logger.info("PanoramaSearch: query=%r graph_id=%s", query, graph_id)
        embedding = self.embedder.embed(query)
        nodes = self.storage.search_by_embedding(embedding, graph_id, top_k=top_k)

        enriched = []
        for node in nodes:
            edges = self.storage.get_entity_edges(node["uuid"], graph_id)
            chains = []
            for edge in edges:
                source_name = node["name"]
                target_name = edge.get("other_name", "?")
                rel_name = edge.get("name", "related_to")
                fact = edge.get("fact", "")
                # Determine direction
                if edge.get("source") == node["uuid"]:
                    chain = f"{source_name} --[{rel_name}]--> {target_name}"
                else:
                    chain = f"{target_name} --[{rel_name}]--> {source_name}"
                if fact:
                    chain += f" | {fact}"
                chains.append(chain)

            enriched.append({
                **node,
                "relationships": edges,
                "relationship_chains": chains,
            })

        logger.info(
            "PanoramaSearch: returned %d enriched nodes, %d total chains",
            len(enriched),
            sum(len(n["relationship_chains"]) for n in enriched),
        )
        return enriched

    # ------------------------------------------------------------------
    # InsightForge -- deepest: LLM sub-questions + multi-hop traversal
    # ------------------------------------------------------------------

    def insight_forge(
        self,
        query: str,
        graph_id: str,
        simulation_requirement: str = "",
        top_k_per_sub: int = 5,
    ) -> InsightForgeResult:
        """Deep retrieval: LLM generates sub-questions, each searched + traversed.

        Steps:
        1. Smart LLM generates 3-5 sub-questions from the main query.
        2. For each sub-question: semantic search + graph traversal.
        3. Collect semantic_facts, entity_insights, relationship_chains.
        4. Return InsightForgeResult dataclass.
        """
        logger.info("InsightForge: query=%r graph_id=%s", query, graph_id)

        # Step 1: Generate sub-questions
        sub_queries = self._generate_sub_questions(query, simulation_requirement)
        logger.info("InsightForge: generated %d sub-queries", len(sub_queries))

        # Step 2: For each sub-question, search + traverse
        all_semantic_facts: List[str] = []
        all_entity_insights: List[Dict] = []
        all_relationship_chains: List[str] = []
        seen_entity_uuids: set = set()

        for sq in sub_queries:
            embedding = self.embedder.embed(sq)
            nodes = self.storage.search_by_embedding(
                embedding, graph_id, top_k=top_k_per_sub
            )

            for node in nodes:
                # Semantic fact from the node summary
                if node.get("summary") and node["summary"] not in all_semantic_facts:
                    all_semantic_facts.append(node["summary"])

                # Entity insight (deduplicated by uuid)
                if node["uuid"] not in seen_entity_uuids:
                    seen_entity_uuids.add(node["uuid"])
                    all_entity_insights.append({
                        "uuid": node["uuid"],
                        "name": node["name"],
                        "type": node.get("type", "Entity"),
                        "summary": node.get("summary", ""),
                        "score": node.get("score", 0.0),
                        "matched_sub_query": sq,
                    })

                # Graph traversal for relationship chains
                edges = self.storage.get_entity_edges(node["uuid"], graph_id)
                for edge in edges:
                    source_name = node["name"]
                    target_name = edge.get("other_name", "?")
                    rel_name = edge.get("name", "related_to")
                    fact = edge.get("fact", "")

                    if edge.get("source") == node["uuid"]:
                        chain = f"{source_name} --[{rel_name}]--> {target_name}"
                    else:
                        chain = f"{target_name} --[{rel_name}]--> {source_name}"
                    if fact:
                        chain += f" | {fact}"

                    if chain not in all_relationship_chains:
                        all_relationship_chains.append(chain)

        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=sub_queries,
            semantic_facts=all_semantic_facts,
            entity_insights=all_entity_insights,
            relationship_chains=all_relationship_chains,
        )
        logger.info(
            "InsightForge: %d facts, %d entities, %d chains",
            len(result.semantic_facts),
            len(result.entity_insights),
            len(result.relationship_chains),
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_sub_questions(
        self, query: str, simulation_requirement: str
    ) -> List[str]:
        """Use the smart LLM to decompose *query* into 3-5 sub-questions."""
        context = ""
        if simulation_requirement:
            context = f"\nSimulation context: {simulation_requirement}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a research analyst. Given a query about a topic, "
                    "generate 3-5 focused sub-questions that together would "
                    "comprehensively answer the main query. Return a JSON object "
                    'with key "sub_questions" containing a list of strings.'
                ),
            },
            {
                "role": "user",
                "content": f"Main query: {query}{context}",
            },
        ]

        try:
            result = self.llm.complete_json(messages, smart=True, temperature=0.4)
            if isinstance(result, list):
                result = result[0] if result and isinstance(result[0], dict) else {}
            sub_qs = result.get("sub_questions", []) if isinstance(result, dict) else []
            if isinstance(sub_qs, list) and len(sub_qs) >= 2:
                return sub_qs[:5]
        except Exception:
            logger.exception("Failed to generate sub-questions, using fallbacks")

        # Fallback: return the original query plus two reformulations
        return [
            query,
            f"What are the key entities related to: {query}",
            f"What relationships and dynamics are relevant to: {query}",
        ]

    # ------------------------------------------------------------------
    # Graph structure analysis
    # ------------------------------------------------------------------

    def analyze_graph_structure(self, graph_id: str) -> Dict[str, Any]:
        """Compute structural metrics: degree centrality, clusters, bridges."""
        entities = self.storage.get_all_entities(graph_id)
        if not entities:
            return {"entity_count": 0, "hubs": [], "bridges": [], "clusters": []}

        degree_map: Dict[str, int] = {}
        edge_list: List[tuple] = []

        for ent in entities:
            edges = self.storage.get_entity_edges(ent["uuid"], graph_id)
            degree_map[ent["name"]] = len(edges)
            for edge in edges:
                other = edge.get("other_name", "")
                if other:
                    edge_list.append((ent["name"], other))

        sorted_by_degree = sorted(degree_map.items(), key=lambda x: x[1], reverse=True)
        hubs = [{"name": n, "connections": d} for n, d in sorted_by_degree[:10]]

        neighbors: Dict[str, set] = {}
        for a, b in edge_list:
            neighbors.setdefault(a, set()).add(b)
            neighbors.setdefault(b, set()).add(a)

        bridges = []
        for name, conns in sorted_by_degree:
            if conns < 2:
                continue
            nbrs = neighbors.get(name, set())
            connected_pairs = 0
            total_pairs = 0
            nbr_list = list(nbrs)
            for i in range(len(nbr_list)):
                for j in range(i + 1, len(nbr_list)):
                    total_pairs += 1
                    if nbr_list[j] in neighbors.get(nbr_list[i], set()):
                        connected_pairs += 1
            if total_pairs > 0 and connected_pairs / total_pairs < 0.3:
                bridges.append({"name": name, "connections": conns})
            if len(bridges) >= 5:
                break

        return {
            "entity_count": len(entities),
            "hubs": hubs,
            "bridges": bridges,
        }

    # ------------------------------------------------------------------
    # Causal path finder
    # ------------------------------------------------------------------

    def find_causal_path(
        self, source_name: str, target_name: str, graph_id: str, max_depth: int = 4,
    ) -> List[str]:
        """Find the shortest relationship path between two named entities."""
        entities = self.storage.get_all_entities(graph_id)
        name_to_uuid = {e["name"].lower(): e["uuid"] for e in entities}
        uuid_to_name = {e["uuid"]: e["name"] for e in entities}

        src_uuid = name_to_uuid.get(source_name.lower())
        tgt_uuid = name_to_uuid.get(target_name.lower())
        if not src_uuid or not tgt_uuid:
            return []

        from collections import deque
        visited = {src_uuid}
        queue = deque([(src_uuid, [])])

        while queue:
            current, path = queue.popleft()
            if len(path) >= max_depth:
                continue

            edges = self.storage.get_entity_edges(current, graph_id)
            for edge in edges:
                other_uuid = edge.get("target") if edge.get("source") == current else edge.get("source")
                if not other_uuid or other_uuid in visited:
                    continue

                rel = edge.get("name", "related_to")
                fact = edge.get("fact", "")
                cur_name = uuid_to_name.get(current, "?")
                other_name = uuid_to_name.get(other_uuid, "?")
                step = f"{cur_name} --[{rel}]--> {other_name}"
                if fact:
                    step += f" ({fact})"
                new_path = path + [step]

                if other_uuid == tgt_uuid:
                    return new_path

                visited.add(other_uuid)
                queue.append((other_uuid, new_path))

        return []

    # ------------------------------------------------------------------
    # Contradiction detector
    # ------------------------------------------------------------------

    def detect_contradictions(self, graph_id: str) -> List[Dict[str, Any]]:
        """Find entity pairs connected by edges with opposing sentiments."""
        entities = self.storage.get_all_entities(graph_id)
        positive_rels = {"supports", "allies_with", "endorses", "funds", "collaborates_with", "assists"}
        negative_rels = {"opposes", "conflicts_with", "sanctions", "attacks", "criticizes", "blocks"}

        pair_rels: Dict[tuple, List[Dict]] = {}
        for ent in entities:
            edges = self.storage.get_entity_edges(ent["uuid"], graph_id)
            for edge in edges:
                other = edge.get("other_name", "")
                if not other:
                    continue
                key = tuple(sorted([ent["name"], other]))
                pair_rels.setdefault(key, []).append({
                    "type": edge.get("name", ""),
                    "fact": edge.get("fact", ""),
                    "source": ent["name"],
                    "target": other,
                })

        contradictions = []
        for (a, b), rels in pair_rels.items():
            rel_types = {r["type"].lower() for r in rels}
            has_positive = bool(rel_types & positive_rels)
            has_negative = bool(rel_types & negative_rels)
            if has_positive and has_negative:
                contradictions.append({
                    "entity_a": a,
                    "entity_b": b,
                    "relationships": rels,
                })

        return contradictions

    # ------------------------------------------------------------------
    # Simulation feed query
    # ------------------------------------------------------------------

    def query_simulation_feed(
        self,
        sim_dir: str,
        platform: str = None,
        round_num: int = None,
        keyword: str = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Read and filter simulation actions from the action log."""
        import json as _json
        import os

        actions_path = os.path.join(sim_dir, "actions.jsonl")
        if not os.path.exists(actions_path):
            return {"actions": [], "counts": {}}

        actions = []
        counts: Dict[str, int] = {}
        with open(actions_path) as f:
            for line in f:
                try:
                    a = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if a.get("type") != "agent_action":
                    continue
                if platform and a.get("platform") != platform:
                    continue
                if round_num is not None and a.get("_round") != round_num:
                    continue

                act_name = a.get("action", "unknown")
                counts[act_name] = counts.get(act_name, 0) + 1

                content = ""
                args = a.get("arguments", {})
                content = args.get("content", args.get("text", ""))

                if keyword and keyword.lower() not in (content or "").lower():
                    continue

                actions.append({
                    "round": a.get("_round"),
                    "platform": a.get("platform"),
                    "agent": a.get("agent_name", ""),
                    "action": act_name,
                    "content": (content or "")[:300],
                })

        return {"actions": actions[-limit:], "counts": counts, "total": len(actions)}

    # ------------------------------------------------------------------
    # Belief trajectory analysis
    # ------------------------------------------------------------------

    def analyze_belief_trajectories(
        self, sim_dir: str,
    ) -> Dict[str, Any]:
        """Analyze how agent beliefs evolved across rounds from action data."""
        import json as _json
        import os

        actions_path = os.path.join(sim_dir, "actions.jsonl")
        if not os.path.exists(actions_path):
            return {"rounds": 0, "agents": []}

        round_actions: Dict[int, Dict[str, List[str]]] = {}
        with open(actions_path) as f:
            for line in f:
                try:
                    a = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if a.get("type") != "agent_action":
                    continue
                rn = a.get("_round", 0)
                name = a.get("agent_name", "unknown")
                act = a.get("action", "")
                round_actions.setdefault(rn, {}).setdefault(name, []).append(act)

        agent_summaries = {}
        for rn in sorted(round_actions.keys()):
            for name, acts in round_actions[rn].items():
                if name not in agent_summaries:
                    agent_summaries[name] = {"name": name, "rounds_active": 0, "actions": {}}
                agent_summaries[name]["rounds_active"] += 1
                for act in acts:
                    agent_summaries[name]["actions"][act] = agent_summaries[name]["actions"].get(act, 0) + 1

        polymarket_path = os.path.join(sim_dir, "polymarket.db")
        price_trajectory = []
        if os.path.exists(polymarket_path):
            import sqlite3
            conn = sqlite3.connect(polymarket_path)
            conn.row_factory = sqlite3.Row
            markets = conn.execute(
                "SELECT reserve_a, reserve_b FROM market WHERE resolved = 0"
            ).fetchall()
            if markets:
                m = markets[0]
                total = (m["reserve_a"] or 0) + (m["reserve_b"] or 0)
                if total > 0:
                    price_trajectory.append({
                        "yes_price": round(m["reserve_b"] / total, 4),
                    })

            trades = conn.execute(
                "SELECT side, outcome, COUNT(*) as cnt, SUM(cost) as vol FROM trade GROUP BY side, outcome"
            ).fetchall()
            trade_summary = [dict(t) for t in trades]
            conn.close()
        else:
            trade_summary = []

        return {
            "rounds": len(round_actions),
            "agent_count": len(agent_summaries),
            "agents": sorted(agent_summaries.values(), key=lambda x: x["rounds_active"], reverse=True)[:20],
            "price_trajectory": price_trajectory,
            "trade_summary": trade_summary,
        }
