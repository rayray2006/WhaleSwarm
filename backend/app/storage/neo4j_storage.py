"""Neo4j implementation of GraphStorage."""
import logging
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase

from app.config import Config
from app.storage import GraphStorage

logger = logging.getLogger(__name__)


class Neo4jStorage(GraphStorage):
    def __init__(self, config: Config):
        self.config = config
        self._driver = None
        try:
            self.connect()
        except Exception as e:
            logger.warning(f"Neo4j connection failed (non-fatal): {e}")

    def connect(self):
        self._driver = GraphDatabase.driver(
            self.config.neo4j_uri,
            auth=(self.config.neo4j_user, self.config.neo4j_password),
        )
        self._driver.verify_connectivity()
        logger.info(f"Connected to Neo4j at {self.config.neo4j_uri}")

    def close(self):
        if self._driver:
            self._driver.close()

    def ping(self) -> bool:
        try:
            if self._driver:
                self._driver.verify_connectivity()
                return True
        except Exception:
            pass
        return False

    def _session(self):
        if not self._driver:
            self.connect()
        return self._driver.session()

    def add_graph(self, graph_id: str, name: str, ontology: Dict) -> None:
        import json
        with self._session() as session:
            session.run(
                """
                MERGE (g:Graph {graph_id: $graph_id})
                SET g.name = $name,
                    g.ontology_json = $ontology_json,
                    g.created_at = datetime()
                """,
                graph_id=graph_id,
                name=name,
                ontology_json=json.dumps(ontology),
            )

    def add_entities_batch(self, entities: List[Dict], graph_id: str) -> None:
        if not entities:
            return

        # Group entities by type so we can use native Cypher labels (no APOC needed)
        by_type: Dict[str, List[Dict]] = {}
        for ent in entities:
            etype = ent.get("type", "Entity")
            # Sanitize label: only alphanumeric + underscore
            safe_label = "".join(c if c.isalnum() or c == "_" else "_" for c in etype)
            if not safe_label or safe_label[0].isdigit():
                safe_label = "Entity"
            by_type.setdefault(safe_label, []).append(ent)

        with self._session() as session:
            for label, batch in by_type.items():
                # Dynamic label via string formatting (safe — we sanitized above)
                query = f"""
                    UNWIND $entities AS entity
                    MERGE (e:Entity:`{label}` {{uuid: entity.uuid, graph_id: $graph_id}})
                    SET e.name = entity.name,
                        e.summary = entity.summary,
                        e.attributes = entity.attributes,
                        e.embedding = entity.embedding
                    RETURN count(e)
                """
                session.run(query, entities=batch, graph_id=graph_id)

    def add_edges_batch(self, edges: List[Dict], graph_id: str) -> None:
        if not edges:
            return
        with self._session() as session:
            for edge in edges:
                session.run(
                    """
                    MATCH (s:Entity {uuid: $source_uuid, graph_id: $graph_id})
                    MATCH (t:Entity {uuid: $target_uuid, graph_id: $graph_id})
                    MERGE (s)-[r:RELATIONSHIP {uuid: $uuid}]->(t)
                    SET r.name = $name,
                        r.fact = $fact,
                        r.source_node_uuid = $source_uuid,
                        r.target_node_uuid = $target_uuid,
                        r.created_at = datetime()
                    """,
                    uuid=edge["uuid"],
                    name=edge["name"],
                    fact=edge.get("fact", ""),
                    source_uuid=edge["source_node_uuid"],
                    target_uuid=edge["target_node_uuid"],
                    graph_id=graph_id,
                )

    def get_entities(self, graph_id: str) -> List[Dict]:
        with self._session() as session:
            result = session.run(
                """
                MATCH (e:Entity {graph_id: $graph_id})
                RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
                       e.attributes AS attributes, labels(e) AS labels
                """,
                graph_id=graph_id,
            )
            entities = []
            for record in result:
                labels = [l for l in record["labels"] if l != "Entity"]
                entities.append({
                    "uuid": record["uuid"],
                    "name": record["name"],
                    "summary": record["summary"],
                    "attributes": record["attributes"],
                    "type": labels[0] if labels else "Entity",
                })
            return entities

    def get_graph_data(self, graph_id: str) -> Dict:
        nodes = []
        edges = []
        with self._session() as session:
            # Get nodes
            result = session.run(
                """
                MATCH (e:Entity {graph_id: $graph_id})
                RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
                       labels(e) AS labels
                """,
                graph_id=graph_id,
            )
            for record in result:
                labels = [l for l in record["labels"] if l != "Entity"]
                nodes.append({
                    "id": record["uuid"],
                    "name": record["name"],
                    "summary": record["summary"],
                    "type": labels[0] if labels else "Entity",
                })

            # Get edges
            result = session.run(
                """
                MATCH (s:Entity {graph_id: $graph_id})-[r:RELATIONSHIP]->(t:Entity {graph_id: $graph_id})
                RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact,
                       s.uuid AS source, t.uuid AS target
                """,
                graph_id=graph_id,
            )
            for record in result:
                edges.append({
                    "id": record["uuid"],
                    "name": record["name"],
                    "fact": record["fact"],
                    "source": record["source"],
                    "target": record["target"],
                })

        return {"nodes": nodes, "edges": edges}

    def search_by_embedding(
        self, embedding: List[float], graph_id: str, top_k: int = 10
    ) -> List[Dict]:
        with self._session() as session:
            result = session.run(
                """
                MATCH (e:Entity {graph_id: $graph_id})
                WHERE e.embedding IS NOT NULL
                WITH e, gds.similarity.cosine(e.embedding, $embedding) AS score
                ORDER BY score DESC
                LIMIT $top_k
                RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
                       labels(e) AS labels, score
                """,
                embedding=embedding,
                graph_id=graph_id,
                top_k=top_k,
            )
            results = []
            for record in result:
                labels = [l for l in record["labels"] if l != "Entity"]
                results.append({
                    "uuid": record["uuid"],
                    "name": record["name"],
                    "summary": record["summary"],
                    "type": labels[0] if labels else "Entity",
                    "score": record["score"],
                })
            return results

    def get_entity_edges(self, entity_uuid: str, graph_id: str) -> List[Dict]:
        with self._session() as session:
            result = session.run(
                """
                MATCH (e:Entity {uuid: $uuid, graph_id: $graph_id})-[r:RELATIONSHIP]-(other:Entity)
                RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact,
                       r.source_node_uuid AS source, r.target_node_uuid AS target,
                       other.uuid AS other_uuid, other.name AS other_name
                """,
                uuid=entity_uuid,
                graph_id=graph_id,
            )
            return [dict(record) for record in result]

    def get_entity_degree(self, entity_uuid: str, graph_id: str) -> int:
        with self._session() as session:
            result = session.run(
                """
                MATCH (e:Entity {uuid: $uuid, graph_id: $graph_id})-[r:RELATIONSHIP]-()
                RETURN count(r) AS degree
                """,
                uuid=entity_uuid,
                graph_id=graph_id,
            )
            record = result.single()
            return record["degree"] if record else 0
