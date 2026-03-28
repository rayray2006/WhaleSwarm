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
