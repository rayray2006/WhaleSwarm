"""NetworkX-backed directed graph of social agents.

The graph tracks follow/unfollow relationships that evolve during the
simulation.  Each node stores a reference to the ``SocialAgent`` object.
"""

import logging
from typing import Dict, List, Optional

try:
    import networkx as nx
except ImportError:
    raise ImportError(
        "networkx is required for AgentGraph. Install it with: pip install networkx"
    )

from simulation_engine.social_agent.agent import SocialAgent

logger = logging.getLogger(__name__)


class AgentGraph:
    """Directed graph of :class:`SocialAgent` instances.

    Nodes are keyed by ``agent_id`` (int).  Edges represent directional
    social relationships (follower -> followee).
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._agents: Dict[int, SocialAgent] = {}

    # ------------------------------------------------------------------
    # Node (agent) management
    # ------------------------------------------------------------------

    def add_agent(self, agent: SocialAgent) -> None:
        """Register an agent in the graph.

        Creates a node if one does not already exist for this ``agent_id``.
        """
        aid = agent.agent_id
        self._agents[aid] = agent
        if not self._graph.has_node(aid):
            self._graph.add_node(aid)
        logger.debug("AgentGraph: added agent %d (%s)", aid, agent.user_info.name)

    def get_agent(self, agent_id: int) -> Optional[SocialAgent]:
        """Look up an agent by id, or return ``None``."""
        return self._agents.get(agent_id)

    def get_agents(self) -> List[SocialAgent]:
        """Return all registered agents (unordered)."""
        return list(self._agents.values())

    def has_agent(self, agent_id: int) -> bool:
        return agent_id in self._agents

    # ------------------------------------------------------------------
    # Edge (relationship) management
    # ------------------------------------------------------------------

    def add_edge(self, from_id: int, to_id: int) -> None:
        """Add a directed edge (follow) from *from_id* to *to_id*."""
        if from_id == to_id:
            return
        # Ensure both nodes exist.
        for nid in (from_id, to_id):
            if not self._graph.has_node(nid):
                self._graph.add_node(nid)
        self._graph.add_edge(from_id, to_id)
        logger.debug("AgentGraph: edge %d -> %d", from_id, to_id)

    def remove_edge(self, from_id: int, to_id: int) -> None:
        """Remove a directed edge (unfollow)."""
        if self._graph.has_edge(from_id, to_id):
            self._graph.remove_edge(from_id, to_id)
            logger.debug("AgentGraph: removed edge %d -> %d", from_id, to_id)

    def has_edge(self, from_id: int, to_id: int) -> bool:
        return self._graph.has_edge(from_id, to_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_num_nodes(self) -> int:
        return self._graph.number_of_nodes()

    def get_num_edges(self) -> int:
        return self._graph.number_of_edges()

    def get_followers(self, agent_id: int) -> List[int]:
        """Return ids of agents that follow *agent_id*."""
        return list(self._graph.predecessors(agent_id))

    def get_following(self, agent_id: int) -> List[int]:
        """Return ids of agents that *agent_id* follows."""
        return list(self._graph.successors(agent_id))

    def get_follower_count(self, agent_id: int) -> int:
        return self._graph.in_degree(agent_id)

    def get_following_count(self, agent_id: int) -> int:
        return self._graph.out_degree(agent_id)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_edge_list(self) -> List[Dict[str, int]]:
        """Return all edges as a list of ``{"from": int, "to": int}`` dicts."""
        return [{"from": u, "to": v} for u, v in self._graph.edges()]

    def __repr__(self) -> str:
        return (
            f"<AgentGraph nodes={self.get_num_nodes()} "
            f"edges={self.get_num_edges()}>"
        )
