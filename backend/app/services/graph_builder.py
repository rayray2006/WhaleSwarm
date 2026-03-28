"""Knowledge graph builder: chunks -> parallel NER -> batch Neo4j insert."""
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

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
        self.ner = NERExtractor(llm_client)
        self.embedding = embedding_service

    def build(
        self,
        text: str,
        graph_id: str,
        graph_name: str,
        ontology: Dict,
        task_id: str = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 5,
    ):
        """Build knowledge graph from text. Runs in a background thread."""
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
                                "attributes": str(ent.get("attributes", {})),
                                "embedding": None,
                            }
                        else:
                            # Merge: append to summary if new info
                            existing = all_entities[name]
                            new_summary = ent.get("summary", "")
                            if new_summary and new_summary not in existing["summary"]:
                                existing["summary"] += f" {new_summary}"

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

        # Resolve edge references (name -> uuid) and insert
        name_to_uuid = {e["name"]: e["uuid"] for e in entity_list}
        resolved_edges = []
        for edge in all_edges:
            src_uuid = name_to_uuid.get(edge["source_name"])
            tgt_uuid = name_to_uuid.get(edge["target_name"])
            if src_uuid and tgt_uuid:
                resolved_edges.append({
                    "uuid": edge["uuid"],
                    "name": edge["name"],
                    "fact": edge["fact"],
                    "source_node_uuid": src_uuid,
                    "target_node_uuid": tgt_uuid,
                })

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

    def _process_chunk(
        self, chunk: str, entity_types: List[str], edge_types: List[str]
    ) -> Dict:
        """Process a single chunk: NER extraction."""
        return self.ner.extract(chunk, entity_types, edge_types)
