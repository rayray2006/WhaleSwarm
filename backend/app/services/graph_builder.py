"""Knowledge graph builder: chunks -> parallel NER -> batch Neo4j insert."""
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from app.config import Config
from app.models.task import TaskManager
from app.services.text_processor import chunk_text
from app.storage.neo4j_storage import Neo4jStorage
from app.utils.embedding_service import EmbeddingService
from app.utils.llm_client import LLMClient
from app.utils.ner_extractor import NERExtractor

logger = logging.getLogger(__name__)


class GraphBuilder:
    def __init__(
        self,
        config: Config,
        storage: Neo4jStorage,
        llm_client: LLMClient,
        embedding_service: EmbeddingService,
    ):
        self.config = config
        self.storage = storage
        self.llm = llm_client
        self.ner = NERExtractor(llm_client)
        self.embedding = embedding_service

    def build(
        self,
        text: str,
        graph_id: str,
        graph_name: str,
        ontology: Dict,
        task_id: str = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        batch_size: int = 5,
        market_question: Optional[str] = None,
    ):
        """Build knowledge graph from text. Runs in a background thread.

        Args:
            market_question: If provided, entities are filtered by relevance
                to this prediction market question after NER extraction.
        """
        entity_types = ontology.get("entity_types", [])
        edge_types = ontology.get("edge_types", [])

        # Create graph node
        self.storage.add_graph(graph_id, graph_name, ontology)

        # Chunk text
        chunks = chunk_text(text, chunk_size, chunk_overlap)
        total_chunks = len(chunks)
        logger.info(f"Building graph from {total_chunks} chunks (batch_size={batch_size})")

        if task_id:
            TaskManager.update(task_id, status="processing", progress=5)

        # Process chunks in parallel batches
        all_entities = {}  # name -> entity dict (dedup by name)
        all_edges = []
        processed = 0

        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = {}
            for i, chunk in enumerate(chunks):
                future = executor.submit(
                    self._process_chunk, chunk, entity_types, edge_types
                )
                futures[future] = i

            for future in as_completed(futures):
                try:
                    result = future.result()
                    entities = result["entities"]
                    relations = result["relations"]

                    # Deduplicate entities by name
                    for ent in entities:
                        name = ent["name"].strip()
                        if name not in all_entities:
                            ent_uuid = str(uuid.uuid4())
                            all_entities[name] = {
                                "uuid": ent_uuid,
                                "name": name,
                                "type": ent.get("type", "Entity"),
                                "summary": ent.get("summary", ""),
                                "_summary_parts": [ent.get("summary", "")],
                                "attributes": str(ent.get("attributes", {})),
                                "embedding": None,
                            }
                        else:
                            # Merge: collect unique summary sentences,
                            # capped at 5 to prevent bloat.
                            existing = all_entities[name]
                            new_summary = ent.get("summary", "").strip()
                            parts = existing.get("_summary_parts", [])
                            if (
                                new_summary
                                and len(parts) < 5
                                and new_summary not in parts
                            ):
                                parts.append(new_summary)
                                existing["_summary_parts"] = parts
                                existing["summary"] = " ".join(parts)

                    # Collect edges
                    for rel in relations:
                        all_edges.append({
                            "uuid": str(uuid.uuid4()),
                            "name": rel.get("type", "RELATED_TO"),
                            "fact": rel.get("fact", ""),
                            "source_name": rel.get("source", ""),
                            "target_name": rel.get("target", ""),
                        })

                except Exception as e:
                    logger.warning(f"Chunk processing failed: {e}")

                processed += 1
                if task_id:
                    progress = int(5 + (processed / total_chunks) * 70)
                    TaskManager.update(task_id, progress=progress)

        logger.info(f"NER complete: {len(all_entities)} entities, {len(all_edges)} edges")

        # Fuzzy dedup pass: merge entities that refer to the same real-world
        # actor (e.g. "USA" / "United States", "Lloyd Austin" / "Secretary Austin").
        all_entities, all_edges = self._fuzzy_dedup(all_entities, all_edges)
        logger.info(f"After fuzzy dedup: {len(all_entities)} entities")

        # Relevance filter: remove entities that don't directly influence
        # the market outcome.
        if market_question and len(all_entities) > 5:
            all_entities = self._filter_by_relevance(
                all_entities, market_question,
            )
            # Also prune edges whose source/target was removed.
            surviving_names = set(all_entities.keys())
            all_edges = [
                e for e in all_edges
                if e["source_name"] in surviving_names
                and e["target_name"] in surviving_names
            ]
            logger.info(
                f"After relevance filter: {len(all_entities)} entities, "
                f"{len(all_edges)} edges"
            )

        if task_id:
            TaskManager.update(task_id, progress=80)

        # Generate embeddings for all entities
        entity_list = list(all_entities.values())
        if entity_list:
            texts = [f"{e['name']}: {e['summary']}" for e in entity_list]
            try:
                embeddings = self.embedding.embed_batch(texts)
                for i, ent in enumerate(entity_list):
                    ent["embedding"] = embeddings[i]
            except Exception as e:
                logger.warning(f"Batch embedding failed, falling back to individual: {e}")
                for ent in entity_list:
                    try:
                        ent["embedding"] = self.embedding.embed(
                            f"{ent['name']}: {ent['summary']}"
                        )
                    except Exception:
                        ent["embedding"] = [0.0] * self.embedding.dimensions

        if task_id:
            TaskManager.update(task_id, progress=90)

        # Batch insert entities into Neo4j
        self.storage.add_entities_batch(entity_list, graph_id)

        # Resolve edge references with fuzzy name matching.
        name_to_uuid = {e["name"]: e["uuid"] for e in entity_list}
        name_lower_map = {e["name"].lower(): e["name"] for e in entity_list}

        def _resolve_name(raw: str) -> Optional[str]:
            if raw in name_to_uuid:
                return raw
            canonical = name_lower_map.get(raw.lower())
            if canonical:
                return canonical
            cleaned = raw.replace(".", "").replace("'", "").strip()
            canonical = name_lower_map.get(cleaned.lower())
            if canonical:
                return canonical
            for entity_name in name_to_uuid:
                if (raw.lower() in entity_name.lower()
                        or entity_name.lower() in raw.lower()):
                    return entity_name
            return None

        resolved_edges = []
        seen_pairs: set = set()
        for edge in all_edges:
            src = _resolve_name(edge["source_name"])
            tgt = _resolve_name(edge["target_name"])
            if src and tgt and src != tgt:
                pair_key = (name_to_uuid[src], name_to_uuid[tgt], edge["name"])
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    resolved_edges.append({
                        "uuid": edge["uuid"],
                        "name": edge["name"],
                        "fact": edge["fact"],
                        "source_node_uuid": name_to_uuid[src],
                        "target_node_uuid": name_to_uuid[tgt],
                    })

        # Infer missing relationships between entities that were never
        # mentioned together in the same chunk.
        if len(entity_list) <= 60:
            inferred = self._infer_missing_edges(entity_list, resolved_edges)
            resolved_edges.extend(inferred)

        logger.info(
            "Edge resolution: %d from NER, %d after dedup+inference",
            len(all_edges), len(resolved_edges),
        )

        self.storage.add_edges_batch(resolved_edges, graph_id)

        if task_id:
            TaskManager.update(
                task_id,
                status="completed",
                progress=100,
                result={
                    "graph_id": graph_id,
                    "entity_count": len(entity_list),
                    "edge_count": len(resolved_edges),
                },
            )

        logger.info(
            f"Graph built: {len(entity_list)} entities, {len(resolved_edges)} edges"
        )
        return {
            "graph_id": graph_id,
            "entity_count": len(entity_list),
            "edge_count": len(resolved_edges),
        }

    def _infer_missing_edges(
        self,
        entity_list: List[Dict],
        existing_edges: List[Dict],
    ) -> List[Dict]:
        """Use the LLM to infer relationships between entities that were
        never co-mentioned in the same text chunk."""
        existing_pairs = set()
        for e in existing_edges:
            existing_pairs.add((e["source_node_uuid"], e["target_node_uuid"]))
            existing_pairs.add((e["target_node_uuid"], e["source_node_uuid"]))

        entity_names = [f"{e['name']} ({e.get('type', 'Entity')})" for e in entity_list]
        entity_block = "\n".join(f"  {i+1}. {n}" for i, n in enumerate(entity_names))

        messages = [
            {"role": "system", "content": (
                "You are a knowledge graph analyst. Given a list of entities, "
                "identify pairs that clearly have a direct real-world "
                "relationship but are NOT yet connected. Only include "
                "relationships you are confident about. Return JSON."
            )},
            {"role": "user", "content": (
                f"These entities exist in a knowledge graph:\n\n{entity_block}\n\n"
                f"Identify missing relationships. For each, provide:\n"
                f"- source: exact entity name from the list\n"
                f"- target: exact entity name from the list\n"
                f"- type: relationship type (e.g., PART_OF, ADVISES, WORKS_FOR, "
                f"REPRESENTS, OPPOSES, OVERSEES, FUNDS)\n"
                f"- fact: one-sentence description of the relationship\n\n"
                f'Return: {{"relations": [{{"source": "...", "target": "...", '
                f'"type": "...", "fact": "..."}}]}}'
            )},
        ]

        try:
            result = self.llm.complete_json(
                messages, smart=False, temperature=0.3, max_tokens=4096,
            )
            if isinstance(result, list):
                result = result[0] if result else {}
            relations = result.get("relations", []) if isinstance(result, dict) else []
        except Exception:
            logger.debug("Edge inference failed, skipping")
            return []

        name_to_uuid = {e["name"]: e["uuid"] for e in entity_list}
        name_lower = {e["name"].lower(): e["name"] for e in entity_list}

        inferred = []
        for rel in relations:
            src_raw = rel.get("source", "")
            tgt_raw = rel.get("target", "")
            src = name_to_uuid.get(src_raw) or name_to_uuid.get(name_lower.get(src_raw.lower(), ""))
            tgt = name_to_uuid.get(tgt_raw) or name_to_uuid.get(name_lower.get(tgt_raw.lower(), ""))

            if not src or not tgt or src == tgt:
                continue
            if (src, tgt) in existing_pairs:
                continue

            existing_pairs.add((src, tgt))
            existing_pairs.add((tgt, src))
            inferred.append({
                "uuid": str(uuid.uuid4()),
                "name": rel.get("type", "RELATED_TO"),
                "fact": rel.get("fact", ""),
                "source_node_uuid": src,
                "target_node_uuid": tgt,
            })

        logger.info("Inferred %d missing edges", len(inferred))
        return inferred

    def _fuzzy_dedup(
        self,
        entities: Dict[str, Dict],
        edges: List[Dict],
    ) -> tuple:
        """Merge entities that refer to the same real-world actor.

        Uses an LLM call to identify duplicates, then merges them by keeping
        the longest/most specific name and combining summaries.
        """
        if len(entities) <= 3:
            return entities, edges

        names = list(entities.keys())
        numbered = "\n".join(f"{i+1}. {n} ({entities[n].get('type', '?')})" for i, n in enumerate(names))

        messages = [
            {"role": "system", "content": (
                "You are a deduplication expert. Given a list of entities from a "
                "knowledge graph, identify groups that refer to the SAME real-world "
                "person or organization. Common patterns:\n"
                "- Full name vs title+lastname: 'Lloyd Austin' = 'Secretary Austin'\n"
                "- Country name vs abbreviation: 'United States' = 'USA' = 'US'\n"
                "- Org abbreviation vs full: 'NATO' = 'North Atlantic Treaty Organization'\n"
                "- First name vs full name: 'Biden' = 'Joe Biden'\n\n"
                "Only group entities you are CERTAIN refer to the same actor. "
                "Return JSON."
            )},
            {"role": "user", "content": (
                f"Find duplicate entities in this list:\n\n{numbered}\n\n"
                f"Return a JSON object with:\n"
                f'{{"groups": [["name1", "name2", ...], ["name3", "name4", ...], ...]}}\n\n'
                f"Each inner array is a set of names that all refer to the same "
                f"entity. Only include groups with 2+ names. If no duplicates, "
                f'return {{"groups": []}}.'
            )},
        ]

        try:
            result = self.llm.complete_json(
                messages, smart=False, temperature=0.1, max_tokens=4096,
            )
            if isinstance(result, list):
                result = result[0] if result else {}
            groups = result.get("groups", []) if isinstance(result, dict) else []
        except Exception:
            logger.debug("Fuzzy dedup LLM call failed, skipping")
            return entities, edges

        if not groups:
            return entities, edges

        # Build merge map: short/alternate name -> canonical (longest) name
        merge_map = {}  # old_name -> canonical_name
        for group in groups:
            valid = [n for n in group if n in entities]
            if len(valid) < 2:
                continue
            # Keep the longest name as canonical (most specific)
            canonical = max(valid, key=len)
            for name in valid:
                if name != canonical:
                    merge_map[name] = canonical

        if not merge_map:
            return entities, edges

        logger.info("Fuzzy dedup merging %d entities: %s", len(merge_map), merge_map)

        # Merge summaries into canonical
        for old_name, canonical in merge_map.items():
            old_ent = entities[old_name]
            canon_ent = entities[canonical]
            old_summary = old_ent.get("summary", "").strip()
            parts = canon_ent.get("_summary_parts", [])
            if old_summary and old_summary not in parts and len(parts) < 5:
                parts.append(old_summary)
                canon_ent["_summary_parts"] = parts
                canon_ent["summary"] = " ".join(parts)
            del entities[old_name]

        # Rewrite edge references
        for edge in edges:
            src = edge.get("source_name", "")
            tgt = edge.get("target_name", "")
            if src in merge_map:
                edge["source_name"] = merge_map[src]
            if tgt in merge_map:
                edge["target_name"] = merge_map[tgt]

        return entities, edges

    def _process_chunk(
        self, chunk: str, entity_types: List[str], edge_types: List[str]
    ) -> Dict:
        """Process a single chunk: NER extraction."""
        return self.ner.extract(chunk, entity_types, edge_types)

    def _filter_by_relevance(
        self,
        entities: Dict[str, Dict],
        market_question: str,
    ) -> Dict[str, Dict]:
        """Score entities by relevance to the market question and remove
        low-relevance ones.  One LLM call with all entity names."""
        entity_names = list(entities.keys())

        # Batch into groups of 40 to stay within token limits
        batch_size = 40
        keep_names: set = set()

        for i in range(0, len(entity_names), batch_size):
            batch = entity_names[i : i + batch_size]
            numbered = "\n".join(f"{j+1}. {name}" for j, name in enumerate(batch))

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a prediction-market analyst. Given a market "
                        "question and a list of entities, rate each entity's "
                        "relevance to the market outcome on a scale of 1-5:\n"
                        "  5 = direct decision maker or primary factor\n"
                        "  4 = significant influence on outcome\n"
                        "  3 = moderate relevance\n"
                        "  2 = peripheral / background context only\n"
                        "  1 = irrelevant to this prediction\n\n"
                        "Return JSON: a list of objects with "
                        '{"name": "...", "score": N} for each entity. '
                        "Keep ONLY entities scoring 3 or above."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Market question: {market_question}\n\n"
                        f"Entities to evaluate:\n{numbered}"
                    ),
                },
            ]

            try:
                result = self.llm.complete_json(
                    messages, smart=False, temperature=0.2, max_tokens=4096,
                )
                if isinstance(result, dict):
                    result = result.get("entities", result.get("results", []))
                if isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict):
                            name = item.get("name", "")
                            score = item.get("score", 0)
                            if score >= 3 and name in entities:
                                keep_names.add(name)
                            elif score >= 3:
                                # Fuzzy match: LLM might return slightly different name
                                for ename in batch:
                                    if ename.lower() == name.lower():
                                        keep_names.add(ename)
                                        break
            except Exception:
                logger.exception("Relevance filter batch failed, keeping all")
                keep_names.update(batch)

        if not keep_names:
            logger.warning("Relevance filter removed all entities, keeping originals")
            return entities

        logger.info(
            "Relevance filter: %d/%d entities kept",
            len(keep_names), len(entities),
        )
        return {name: ent for name, ent in entities.items() if name in keep_names}
