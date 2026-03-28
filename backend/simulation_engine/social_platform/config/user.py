"""UserInfo dataclass shared across all simulation platforms."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class UserInfo:
    """Minimal user representation passed to agents and prompt builders.

    Attributes:
        name: Display name of the user (e.g. "Jane Smith").
        description: Short bio / persona text for system-prompt injection.
        profile: Arbitrary platform-specific metadata dict (e.g. risk_tolerance,
            karma, mbti, etc.).
        agent_id: Numeric identifier linking this info to the agent graph.
    """

    name: str
    description: str = ""
    profile: Optional[Dict[str, Any]] = field(default=None)
    agent_id: int = 0

    def __post_init__(self) -> None:
        if self.profile is None:
            self.profile = {}

    # ------------------------------------------------------------------
    # Convenience accessors used by prompt builders
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """Look up a value in ``profile``, falling back to *default*."""
        return self.profile.get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "profile": self.profile,
            "agent_id": self.agent_id,
        }
