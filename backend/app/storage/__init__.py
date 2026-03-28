"""Graph storage interface."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class GraphStorage(ABC):
    """Abstract interface for graph storage backends."""

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def close(self):
        pass

    @abstractmethod
    def ping(self) -> bool:
        pass

    @abstractmethod
    def add_graph(self, graph_id: str, name: str, ontology: Dict) -> None:
        pass

    @abstractmethod
    def add_entities_batch(
        self, entities: List[Dict], graph_id: str
    ) -> None:
        pass

    @abstractmethod
    def add_edges_batch(
        self, edges: List[Dict], graph_id: str
    ) -> None:
        pass

    @abstractmethod
    def get_entities(self, graph_id: str) -> List[Dict]:
        pass

    @abstractmethod
    def get_graph_data(self, graph_id: str) -> Dict:
        pass

    @abstractmethod
    def search_by_embedding(
        self, embedding: List[float], graph_id: str, top_k: int = 10
    ) -> List[Dict]:
        pass
