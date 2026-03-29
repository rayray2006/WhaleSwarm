"""Per-agent cross-platform activity tracking.

Tracks what each agent has done on OTHER platforms so they can see a
digest of their own cross-platform activity in their observation prompt.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MAX_DIGEST_ITEMS = 5


class CrossPlatformLog:
    """Stores per-agent, per-platform action history for cross-platform awareness."""

    def __init__(self) -> None:
        self._log: Dict[int, Dict[str, List[Dict]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def record(self, agent_id: int, platform: str, action: Dict[str, Any]) -> None:
        action_name = action.get("action", action.get("name", "unknown"))
        content = action.get("content", "")
        if not content:
            args = action.get("arguments", {})
            content = args.get("content", args.get("query", ""))

        self._log[agent_id][platform].append({
            "action": action_name,
            "content": (content or "")[:150],
            "round": action.get("_round", 0),
        })

    def record_batch(self, platform: str, actions: List[Dict[str, Any]]) -> None:
        for action in actions:
            agent_id = action.get("agent_id")
            if agent_id is not None:
                self.record(agent_id, platform, action)

    def get_digest(self, agent_id: int, exclude_platform: str) -> str:
        agent_log = self._log.get(agent_id, {})
        if not agent_log:
            return ""

        lines = []
        for platform, actions in agent_log.items():
            if platform == exclude_platform:
                continue
            if not actions:
                continue

            recent = actions[-MAX_DIGEST_ITEMS:]
            header = f"Your recent {platform.capitalize()} activity:"
            items = []
            for a in recent:
                desc = a["action"]
                if a["content"]:
                    desc += f": {a['content'][:80]}"
                items.append(f"  - {desc}")

            lines.append(header + "\n" + "\n".join(items))

        if not lines:
            return ""

        return "===== YOUR CROSS-PLATFORM ACTIVITY =====\n" + "\n".join(lines)
