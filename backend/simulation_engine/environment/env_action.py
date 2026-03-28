"""Environment-level action helpers.

Provides utilities for dispatching environment-level actions such as
injecting news events, triggering market resolutions, and broadcasting
system messages at scheduled simulation hours.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Optional

from simulation_engine.social_platform.database import Database

logger = logging.getLogger(__name__)


# ======================================================================
# Event injection
# ======================================================================

def inject_news_event(
    db: Database,
    event_text: str,
    author_user_id: int,
    platform_name: str = "twitter",
) -> Optional[int]:
    """Insert a news-event post into a platform's database.

    Args:
        db: The platform's SQLite database.
        event_text: The content of the news event.
        author_user_id: The user_id to attribute the post to.
        platform_name: Used only for logging.

    Returns:
        The ``post_id`` of the inserted post, or ``None`` on failure.
    """
    try:
        created_at = datetime.utcnow().isoformat()
        cursor = db.execute(
            "INSERT INTO post (user_id, content, created_at) VALUES (?, ?, ?)",
            (author_user_id, event_text, created_at),
        )
        post_id = cursor.lastrowid
        logger.info(
            "Injected news event on %s (post_id=%d): %s",
            platform_name, post_id, event_text[:80],
        )
        return post_id
    except Exception:
        logger.exception("Failed to inject news event on %s", platform_name)
        return None


def inject_market_event(
    db: Database,
    market_id: int,
    event_text: str,
    author_user_id: int,
) -> Optional[int]:
    """Insert a comment on a Polymarket market as an event injection.

    Args:
        db: The Polymarket SQLite database.
        market_id: The target market.
        event_text: The comment content.
        author_user_id: Who the comment is attributed to.

    Returns:
        The ``comment_id`` or ``None`` on failure.
    """
    try:
        created_at = datetime.utcnow().isoformat()
        cursor = db.execute(
            "INSERT INTO poly_comment (market_id, creator_id, content, created_at) "
            "VALUES (?, ?, ?, ?)",
            (market_id, author_user_id, event_text, created_at),
        )
        comment_id = cursor.lastrowid
        logger.info(
            "Injected market event on market %d (comment_id=%d): %s",
            market_id, comment_id, event_text[:80],
        )
        return comment_id
    except Exception:
        logger.exception("Failed to inject market event on market %d", market_id)
        return None


# ======================================================================
# Scheduled event dispatcher
# ======================================================================

class ScheduledEventDispatcher:
    """Dispatches scheduled events based on simulated time.

    Events are defined in the simulation config under ``events.scheduled_events``
    with a structure like::

        {
            "hour": 14,
            "description": "Breaking news about ...",
            "platforms": ["twitter", "reddit"],
            "type": "news"   # "news" | "market_comment" | "system_message"
        }
    """

    def __init__(self, events: List[Dict[str, Any]]) -> None:
        self.events = events
        self._dispatched: set = set()  # Track (event_index, round) to avoid duplicates.

    def get_events_for_hour(self, sim_hour: int, round_num: int) -> List[Dict[str, Any]]:
        """Return events that should fire at the given simulated hour.

        Each event fires at most once per unique (event_index, sim_hour) pair.
        """
        triggered: List[Dict[str, Any]] = []

        for i, event in enumerate(self.events):
            trigger_hour = event.get("hour")
            if trigger_hour is None:
                continue

            key = (i, sim_hour)
            if key in self._dispatched:
                continue

            if sim_hour == trigger_hour:
                self._dispatched.add(key)
                triggered.append(event)

        return triggered

    def dispatch(
        self,
        events: List[Dict[str, Any]],
        platform_dbs: Dict[str, Database],
        platform_agents: Dict[str, List[Any]],
    ) -> List[Dict[str, Any]]:
        """Dispatch a list of events into the appropriate platform databases.

        Args:
            events: Events to dispatch.
            platform_dbs: Mapping of platform name to Database.
            platform_agents: Mapping of platform name to list of agents.

        Returns:
            List of action records for logging.
        """
        actions: List[Dict[str, Any]] = []

        for event in events:
            event_type = event.get("type", "news")
            description = event.get("description", "")
            target_platforms = event.get("platforms", list(platform_dbs.keys()))

            for pname in target_platforms:
                db = platform_dbs.get(pname)
                agents = platform_agents.get(pname, [])
                if db is None or not agents:
                    continue

                # Pick a random agent to attribute the event to.
                author = random.choice(agents)
                author_id = getattr(author, "agent_id", 0)

                if event_type == "market_comment" and pname == "polymarket":
                    market_id = event.get("market_id", 1)
                    comment_id = inject_market_event(db, market_id, description, author_id)
                    actions.append({
                        "type": "scheduled_event",
                        "event_type": event_type,
                        "platform": pname,
                        "market_id": market_id,
                        "comment_id": comment_id,
                        "description": description[:200],
                    })
                else:
                    post_id = inject_news_event(db, description, author_id, pname)
                    actions.append({
                        "type": "scheduled_event",
                        "event_type": event_type,
                        "platform": pname,
                        "post_id": post_id,
                        "description": description[:200],
                    })

        return actions


# ======================================================================
# Broadcast system message
# ======================================================================

def broadcast_system_message(
    agents: List[Any],
    message: str,
) -> None:
    """Inject a system-level message into every agent's extra observation context.

    This is useful for announcements that all agents should see,
    regardless of platform.
    """
    for agent in agents:
        if hasattr(agent, "env") and hasattr(agent.env, "set_extra_context"):
            current = getattr(agent.env, "extra_observation_context", "")
            if current:
                agent.env.set_extra_context(current + f"\n\nSYSTEM: {message}")
            else:
                agent.env.set_extra_context(f"SYSTEM: {message}")
