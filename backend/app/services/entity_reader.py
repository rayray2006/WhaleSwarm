"""Read filtered entities from the knowledge graph."""
import logging
from typing import Dict, List

from app.storage.neo4j_storage import Neo4jStorage

logger = logging.getLogger(__name__)


class EntityReader:
    def __init__(self, storage: Neo4jStorage):
        self.storage = storage

    def get_entities(self, graph_id: str) -> List[Dict]:
        """Get all entities with meaningful types (not bare Entity nodes)."""
        entities = self.storage.get_entities(graph_id)
        # Filter out entities that only have the base "Entity" label
        filtered = [e for e in entities if e.get("type") and e["type"] != "Entity"]
        logger.info(f"Read {len(filtered)} typed entities from graph {graph_id}")
        return filtered

    def get_entity_with_edges(self, entity_uuid: str, graph_id: str) -> Dict:
        """Get a single entity with all its relationships."""
        entities = self.storage.get_entities(graph_id)
        entity = next((e for e in entities if e["uuid"] == entity_uuid), None)
        if not entity:
            return None

        edges = self.storage.get_entity_edges(entity_uuid, graph_id)
        degree = len(edges)

        return {
            **entity,
            "edges": edges,
            "degree": degree,
        }
