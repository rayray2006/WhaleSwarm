"""Persistent agent state and market-series configuration models.

Extension B of the Convergence PRD.  These dataclasses track agent
performance across a series of markets and define the configuration
for multi-market evolution runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ------------------------------------------------------------------
# Model tier mapping
# ------------------------------------------------------------------

MODEL_TIER_MAP: Dict[str, str] = {
    "base": "google/gemini-2.5-flash-lite",
    "mid":  "google/gemini-2.5-flash",
    "top":  "google/gemini-2.5-pro",
}


# ------------------------------------------------------------------
# Persistent agent state
# ------------------------------------------------------------------

@dataclass
class PersistentAgentState:
    """Tracks an agent's cumulative state across a market series.

    This state persists between individual market simulations and is
    used to determine model-tier promotions, kills (bankruptcy), and
    performance summaries injected into the agent's system prompt.

    Attributes
    ----------
    agent_id:
        Unique integer ID for this agent within the series.
    name:
        Display name (from the knowledge-graph entity).
    persona:
        Full persona string used in the system prompt.
    source_entity_uuid:
        UUID of the knowledge-graph entity this agent is derived from.
    wallet_balance:
        Current USD balance, carried across markets.
    total_pnl:
        Cumulative profit/loss across all markets.
    markets_participated:
        Number of markets this agent has actively traded in.
    win_rate:
        Fraction of resolved positions that were profitable (0.0 -- 1.0).
    avg_edge_captured:
        Mean difference between the agent's entry price and the fair
        value at resolution, across profitable trades.
    best_categories:
        List of market categories where this agent performs best.
    risk_profile:
        One of ``"conservative"``, ``"moderate"``, ``"aggressive"``.
    model_tier:
        Current LLM tier: ``"base"``, ``"mid"``, or ``"top"``.
    trades_won:
        Number of individual trades that resolved profitably.
    trades_lost:
        Number of individual trades that resolved at a loss.
    positions_history:
        List of dicts recording each market's final outcome for this
        agent: ``{"market_idx": int, "pnl": float, "outcome": str}``.
    """

    agent_id: int = 0
    name: str = ""
    persona: str = ""
    source_entity_uuid: str = ""
    wallet_balance: float = 1000.0
    total_pnl: float = 0.0
    markets_participated: int = 0
    win_rate: float = 0.0
    avg_edge_captured: float = 0.0
    best_categories: List[str] = field(default_factory=list)
    risk_profile: str = "moderate"
    model_tier: str = "base"
    trades_won: int = 0
    trades_lost: int = 0
    positions_history: List[Dict] = field(default_factory=list)

    # ----------------------------------------------------------------
    # Derived properties
    # ----------------------------------------------------------------

    @property
    def is_bankrupt(self) -> bool:
        """True if the agent's balance has hit zero or below."""
        return self.wallet_balance <= 0.0

    @property
    def total_trades(self) -> int:
        return self.trades_won + self.trades_lost

    @property
    def model_name(self) -> str:
        """Resolve the tier label to an actual model identifier."""
        return MODEL_TIER_MAP.get(self.model_tier, MODEL_TIER_MAP["base"])

    # ----------------------------------------------------------------
    # Update helpers
    # ----------------------------------------------------------------

    def record_market_result(
        self,
        market_idx: int,
        pnl: float,
        outcome: str,
        edge_captured: float = 0.0,
        category: str = "",
    ) -> None:
        """Record the result of one market for this agent."""
        self.markets_participated += 1
        self.total_pnl += pnl
        self.wallet_balance += pnl

        if pnl > 0:
            self.trades_won += 1
        elif pnl < 0:
            self.trades_lost += 1

        # Update win rate
        if self.total_trades > 0:
            self.win_rate = self.trades_won / self.total_trades

        # Rolling average of edge captured (profitable trades only)
        if pnl > 0 and edge_captured > 0:
            n_wins = self.trades_won
            if n_wins > 1:
                self.avg_edge_captured = (
                    self.avg_edge_captured * (n_wins - 1) + edge_captured
                ) / n_wins
            else:
                self.avg_edge_captured = edge_captured

        # Track best categories
        if pnl > 0 and category and category not in self.best_categories:
            self.best_categories.append(category)
            # Keep only top 5
            self.best_categories = self.best_categories[-5:]

        self.positions_history.append({
            "market_idx": market_idx,
            "pnl": round(pnl, 4),
            "outcome": outcome,
            "edge": round(edge_captured, 4),
        })

    def to_dict(self) -> Dict:
        """Serialize to a plain dict for JSON storage."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "persona": self.persona,
            "source_entity_uuid": self.source_entity_uuid,
            "wallet_balance": round(self.wallet_balance, 2),
            "total_pnl": round(self.total_pnl, 2),
            "markets_participated": self.markets_participated,
            "win_rate": round(self.win_rate, 4),
            "avg_edge_captured": round(self.avg_edge_captured, 4),
            "best_categories": self.best_categories,
            "risk_profile": self.risk_profile,
            "model_tier": self.model_tier,
            "trades_won": self.trades_won,
            "trades_lost": self.trades_lost,
            "positions_history": self.positions_history,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "PersistentAgentState":
        """Deserialize from a plain dict."""
        return cls(
            agent_id=data.get("agent_id", 0),
            name=data.get("name", ""),
            persona=data.get("persona", ""),
            source_entity_uuid=data.get("source_entity_uuid", ""),
            wallet_balance=data.get("wallet_balance", 1000.0),
            total_pnl=data.get("total_pnl", 0.0),
            markets_participated=data.get("markets_participated", 0),
            win_rate=data.get("win_rate", 0.0),
            avg_edge_captured=data.get("avg_edge_captured", 0.0),
            best_categories=data.get("best_categories", []),
            risk_profile=data.get("risk_profile", "moderate"),
            model_tier=data.get("model_tier", "base"),
            trades_won=data.get("trades_won", 0),
            trades_lost=data.get("trades_lost", 0),
            positions_history=data.get("positions_history", []),
        )


# ------------------------------------------------------------------
# Market specification
# ------------------------------------------------------------------

@dataclass
class MarketSpec:
    """Specification for a single market within a series.

    Attributes
    ----------
    question:
        The market question (e.g., "Will X happen by Y date?").
    outcome_a:
        Label for the YES / first outcome.
    outcome_b:
        Label for the NO / second outcome.
    initial_probability:
        Starting implied probability for outcome_a (0.0 -- 1.0).
    winning_outcome:
        If set, used for backtesting -- the known correct outcome
        (``"YES"`` or ``"NO"``).  ``None`` for live/forward sims.
    documents:
        List of document paths or URLs to inject as context for agents.
    max_rounds:
        Maximum number of trading rounds for this market.
    category:
        Free-text category for cohort classification.
    duration_days:
        Expected duration from creation to resolution.
    """

    question: str = ""
    outcome_a: str = "YES"
    outcome_b: str = "NO"
    initial_probability: float = 0.5
    winning_outcome: Optional[str] = None
    documents: List[str] = field(default_factory=list)
    max_rounds: int = 10
    category: str = ""
    duration_days: int = 30

    def to_dict(self) -> Dict:
        return {
            "question": self.question,
            "outcome_a": self.outcome_a,
            "outcome_b": self.outcome_b,
            "initial_probability": self.initial_probability,
            "winning_outcome": self.winning_outcome,
            "documents": self.documents,
            "max_rounds": self.max_rounds,
            "category": self.category,
            "duration_days": self.duration_days,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "MarketSpec":
        return cls(
            question=data.get("question", ""),
            outcome_a=data.get("outcome_a", "YES"),
            outcome_b=data.get("outcome_b", "NO"),
            initial_probability=data.get("initial_probability", 0.5),
            winning_outcome=data.get("winning_outcome"),
            documents=data.get("documents", []),
            max_rounds=data.get("max_rounds", 10),
            category=data.get("category", ""),
            duration_days=data.get("duration_days", 30),
        )


# ------------------------------------------------------------------
# Market series configuration
# ------------------------------------------------------------------

@dataclass
class MarketSeriesConfig:
    """Configuration for a multi-market evolution series.

    Attributes
    ----------
    series_id:
        Unique identifier for this series run.
    series_name:
        Human-readable name.
    market_cohort:
        Default cohort classification for bet-size calibration.
    markets:
        Ordered list of market specifications to run sequentially.
    initial_agent_count:
        Number of agents to start with in the first market.
    kill_threshold:
        Balance at or below which an agent is removed ("killed").
        Default 0.0 means agents are killed only when fully bankrupt.
    whale_threshold_percentile:
        Top X percentile of agents by balance get promoted to mid tier.
        E.g., 0.01 = top 1%.
    elite_threshold_percentile:
        Top X percentile get promoted to top tier.
        E.g., 0.001 = top 0.1%.
    graph_id:
        Knowledge graph ID to source agent profiles from.
    initial_balance:
        Starting USD balance for each agent.
    """

    series_id: str = ""
    series_name: str = ""
    market_cohort: str = "other:medium:normal"
    markets: List[MarketSpec] = field(default_factory=list)
    initial_agent_count: int = 50
    kill_threshold: float = 0.0
    whale_threshold_percentile: float = 0.01
    elite_threshold_percentile: float = 0.001
    graph_id: str = ""
    initial_balance: float = 1000.0

    def to_dict(self) -> Dict:
        return {
            "series_id": self.series_id,
            "series_name": self.series_name,
            "market_cohort": self.market_cohort,
            "markets": [m.to_dict() for m in self.markets],
            "initial_agent_count": self.initial_agent_count,
            "kill_threshold": self.kill_threshold,
            "whale_threshold_percentile": self.whale_threshold_percentile,
            "elite_threshold_percentile": self.elite_threshold_percentile,
            "graph_id": self.graph_id,
            "initial_balance": self.initial_balance,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "MarketSeriesConfig":
        markets = [
            MarketSpec.from_dict(m) for m in data.get("markets", [])
        ]
        return cls(
            series_id=data.get("series_id", ""),
            series_name=data.get("series_name", ""),
            market_cohort=data.get("market_cohort", "other:medium:normal"),
            markets=markets,
            initial_agent_count=data.get("initial_agent_count", 50),
            kill_threshold=data.get("kill_threshold", 0.0),
            whale_threshold_percentile=data.get("whale_threshold_percentile", 0.01),
            elite_threshold_percentile=data.get("elite_threshold_percentile", 0.001),
            graph_id=data.get("graph_id", ""),
            initial_balance=data.get("initial_balance", 1000.0),
        )

    @classmethod
    def from_json_file(cls, path: str) -> "MarketSeriesConfig":
        """Load a series config from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


# Need json import for from_json_file
import json
