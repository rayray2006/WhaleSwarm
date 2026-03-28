"""Core simulation abstractions.

Provides the base classes that every concrete platform (Twitter, Reddit,
Polymarket) must implement, plus the ``SimulationConfig`` dataclass that
bundles them for the runner.
"""

import asyncio
import inspect
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Type

from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.database import Database
from simulation_engine.social_platform.typing import ActionType

logger = logging.getLogger(__name__)


# ======================================================================
# BasePlatform
# ======================================================================

class BasePlatform(ABC):
    """Server-side platform that owns the SQLite database and processes
    agent requests delivered via a :class:`Channel`.

    Subclasses must set ``required_schemas`` (e.g. ``["post", "like"]``)
    and implement concrete handler methods whose names match the
    ``ActionType`` values they support (lower-cased, e.g.
    ``async def create_post(self, agent_id, **kwargs)``).
    """

    # Schemas loaded for ALL platforms.
    _core_schemas: List[str] = ["user", "trace"]

    # Subclass overrides this with platform-specific schemas.
    required_schemas: List[str] = []

    def __init__(self, db_path: str, channel: Channel, **kwargs: Any) -> None:
        self.db = Database(db_path)
        self.channel = channel
        self._running = False

        # Load core + subclass schemas.
        all_schemas = list(self._core_schemas) + list(self.required_schemas)
        self.db.load_schemas(all_schemas)
        logger.info(
            "%s initialised with schemas %s (db=%s)",
            self.__class__.__name__,
            all_schemas,
            db_path,
        )

    # ------------------------------------------------------------------
    # Message loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the platform message loop.

        Continuously reads from the channel's receive queue and dispatches
        each message to the appropriate handler method.
        """
        self._running = True
        logger.info("%s message loop started", self.__class__.__name__)
        try:
            async for message_id, data in self.channel.receive_from():
                if not self._running:
                    break
                try:
                    result = await self._dispatch(message_id, data)
                    await self.channel.send_to(message_id, result)
                except Exception:
                    logger.exception(
                        "Error dispatching message_id=%d", message_id,
                    )
                    await self.channel.send_to(
                        message_id,
                        {"success": False, "error": "internal platform error"},
                    )
        finally:
            self._running = False
            logger.info("%s message loop stopped", self.__class__.__name__)

    async def _dispatch(self, message_id: int, data: Any) -> Any:
        """Route an incoming message to the matching handler.

        *data* is expected to be a tuple
        ``(agent_id, message_body, action_type)``.
        """
        agent_id, message_body, action_type = data

        # Resolve action name from ActionType enum value.
        if isinstance(action_type, ActionType):
            action_name = action_type.name.lower()
        elif isinstance(action_type, str):
            action_name = action_type.lower()
        else:
            action_name = str(action_type).lower()

        handler = getattr(self, action_name, None)
        if handler is None or not callable(handler):
            logger.warning(
                "No handler for action '%s' on %s",
                action_name,
                self.__class__.__name__,
            )
            return {"success": False, "error": f"unknown action: {action_name}"}

        # Call handler — may be sync or async.
        if asyncio.iscoroutinefunction(handler):
            return await handler(agent_id, message_body)
        return handler(agent_id, message_body)

    def stop(self) -> None:
        """Signal the message loop to stop after the current iteration."""
        self._running = False

    # ------------------------------------------------------------------
    # Trace logging
    # ------------------------------------------------------------------

    def log_trace(
        self,
        user_id: int,
        action: str,
        info: str,
        created_at: str,
    ) -> None:
        """Insert a row into the ``trace`` table."""
        self.db.execute(
            "INSERT INTO trace (user_id, action, info, created_at) VALUES (?, ?, ?, ?)",
            (user_id, action, info, created_at),
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self.db.close()


# ======================================================================
# BaseAction
# ======================================================================

class BaseAction(ABC):
    """Agent-side interface for calling platform actions via the channel.

    Concrete subclasses define public ``async`` methods — one per
    supported action — with typed parameters and docstrings.
    ``get_openai_function_list()`` introspects those methods and
    generates OpenAI-compatible function-calling tool definitions
    automatically.
    """

    def __init__(self, agent_id: int, channel: Channel) -> None:
        self.agent_id = agent_id
        self.channel = channel

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    def get_openai_function_list(self) -> List[Dict[str, Any]]:
        """Build OpenAI tool definitions from public async methods.

        Each public async method (name not starting with ``_``) is
        converted into an OpenAI ``function`` tool definition with:
        - ``name``: the method name
        - ``description``: the first line of the docstring
        - ``parameters``: a JSON-Schema derived from the type hints
        """
        tools: List[Dict[str, Any]] = []

        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if name.startswith("_"):
                continue
            if not asyncio.iscoroutinefunction(method):
                continue
            # Skip inherited helpers.
            if name in ("perform_action", "get_openai_function_list"):
                continue

            sig = inspect.signature(method)
            doc = inspect.getdoc(method) or name.replace("_", " ").capitalize()
            description = doc.split("\n")[0].strip()

            # Build JSON-Schema for parameters.
            properties: Dict[str, Any] = {}
            required: List[str] = []
            for pname, param in sig.parameters.items():
                if pname == "self":
                    continue
                ptype = param.annotation
                json_type = _python_type_to_json_schema(ptype)

                prop: Dict[str, Any] = {"type": json_type}
                # Extract per-param docs from docstring if available.
                param_doc = _extract_param_doc(doc, pname)
                if param_doc:
                    prop["description"] = param_doc

                properties[pname] = prop
                if param.default is inspect.Parameter.empty:
                    required.append(pname)

            schema: Dict[str, Any] = {
                "type": "object",
                "properties": properties,
            }
            if required:
                schema["required"] = required

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": schema,
                    },
                }
            )

        return tools

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    async def perform_action(
        self,
        message: Any,
        action_type: ActionType,
    ) -> Any:
        """Send a message to the platform via the channel and await the response.

        Args:
            message: Action-specific payload (dict of kwargs, typically).
            action_type: The ``ActionType`` enum value for routing.

        Returns:
            The platform's response dict.
        """
        message_id = await self.channel.write_to_receive_queue(
            (self.agent_id, message, action_type)
        )
        return await self.channel.read_from_send_queue(message_id)


# ======================================================================
# BaseEnvironment
# ======================================================================

class BaseEnvironment(ABC):
    """Converts the current platform state visible to an agent into a
    text prompt that the LLM can reason about.
    """

    def __init__(self) -> None:
        self.extra_observation_context: str = ""

    @abstractmethod
    async def to_text_prompt(self, agent_id: int) -> str:
        """Return an observation string for the given agent.

        Implementations query the platform's SQLite database (e.g. feed,
        notifications, portfolio) and render it as human-readable text.
        The cross-platform bridge injects extra context via
        ``extra_observation_context`` before this method is called.
        """
        ...

    def set_extra_context(self, context: str) -> None:
        """Inject cross-platform observation context."""
        self.extra_observation_context = context

    def clear_extra_context(self) -> None:
        self.extra_observation_context = ""


# ======================================================================
# BasePromptBuilder
# ======================================================================

class BasePromptBuilder(ABC):
    """Builds the system prompt for an agent on a specific platform."""

    @abstractmethod
    def build_system_prompt(self, user_info: Any) -> str:
        """Return a complete system-message string.

        Args:
            user_info: A :class:`UserInfo` instance (or compatible dict)
                containing name, description/persona, and profile metadata.
        """
        ...


# ======================================================================
# SimulationConfig
# ======================================================================

@dataclass
class SimulationConfig:
    """Bundles all types and settings needed to instantiate one simulation
    platform and its associated agents.

    The simulation runner iterates over a list of these configs to spin
    up Twitter, Reddit, Polymarket, etc.
    """

    name: str
    platform_cls: Type[BasePlatform]
    action_cls: Type[BaseAction]
    environment_cls: Type[BaseEnvironment]
    prompt_builder: BasePromptBuilder
    default_actions: List[str] = field(default_factory=list)
    platform_kwargs: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# Internal helpers
# ======================================================================

_TYPE_MAP = {
    int: "integer",
    float: "number",
    str: "string",
    bool: "boolean",
}


def _python_type_to_json_schema(annotation: Any) -> str:
    """Map a Python type annotation to a JSON-Schema type string."""
    if annotation is inspect.Parameter.empty:
        return "string"
    # Handle Optional[X] (Union[X, None])
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        args = getattr(annotation, "__args__", ())
        # typing.Optional[X] is Union[X, NoneType]
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _TYPE_MAP.get(non_none[0], "string")
    return _TYPE_MAP.get(annotation, "string")


def _extract_param_doc(docstring: Optional[str], param_name: str) -> str:
    """Try to extract a per-parameter description from a Google/NumPy-style docstring."""
    if not docstring:
        return ""
    # Match patterns like "    param_name: description text"
    pattern = rf"^\s*{re.escape(param_name)}\s*(?:\(.+?\))?\s*:\s*(.+)"
    for line in docstring.split("\n"):
        m = re.match(pattern, line)
        if m:
            return m.group(1).strip()
    return ""
