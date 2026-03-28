"""Self-contained social agent that uses an OpenAI-compatible LLM.

This replaces the CAMEL-AI ChatAgent dependency with a lightweight
implementation that talks directly to the ``LLMClient`` defined in
``app.utils.llm_client``.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from simulation_engine.social_platform.channel import Channel
from simulation_engine.social_platform.config.user import UserInfo
from simulation_engine.simulations.base import BaseAction, BaseEnvironment

logger = logging.getLogger(__name__)


class SocialAgent:
    """An LLM-backed agent that participates in one simulated platform.

    The agent observes its environment, sends the observation to an LLM,
    and dispatches the tool calls returned by the LLM through its
    ``BaseAction`` instance which communicates with the platform via
    the shared ``Channel``.

    Attributes:
        agent_id: Unique numeric id (matches ``UserInfo.agent_id``).
        user_info: Agent profile and persona information.
        channel: Async channel shared with the platform.
        env: Environment that renders the agent's observation prompt.
        action: ``BaseAction`` subclass for sending actions to the platform.
        action_tools: OpenAI tool definitions auto-generated from *action*.
        system_message: The base system prompt (from PromptBuilder).
        belief_injection: Dynamic belief-state text prepended each round.
        interview_history: List of (question, answer) pairs.
        llm_client: Reference to the project's ``LLMClient`` (lazy-loaded).
    """

    def __init__(
        self,
        agent_id: int,
        user_info: UserInfo,
        channel: Channel,
        env: BaseEnvironment,
        action: BaseAction,
        system_message: str,
        llm_client: Any = None,
        max_iterations: int = 1,
    ) -> None:
        self.agent_id = agent_id
        self.user_info = user_info
        self.channel = channel
        self.env = env
        self.action = action
        self.action_tools: List[Dict[str, Any]] = action.get_openai_function_list()
        self.system_message = system_message
        self.belief_injection: str = ""
        self.cross_platform_context: str = ""
        self.interview_history: List[Dict[str, str]] = []
        self.max_iterations = max_iterations

        # LLM client — set externally or lazily resolved.
        self._llm_client = llm_client

    # ------------------------------------------------------------------
    # LLM client resolution
    # ------------------------------------------------------------------

    @property
    def llm_client(self) -> Any:
        if self._llm_client is None:
            raise RuntimeError(
                "LLMClient not set on SocialAgent. "
                "Pass it to the constructor or set agent._llm_client."
            )
        return self._llm_client

    @llm_client.setter
    def llm_client(self, client: Any) -> None:
        self._llm_client = client

    # ------------------------------------------------------------------
    # System prompt assembly
    # ------------------------------------------------------------------

    def _build_full_system_message(self) -> str:
        """Combine the base system prompt with belief state and cross-platform
        context injections."""
        parts = [self.system_message]
        if self.belief_injection:
            parts.append(self.belief_injection)
        if self.cross_platform_context:
            parts.append(self.cross_platform_context)
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Core action loop
    # ------------------------------------------------------------------

    async def perform_action_by_llm(self) -> Dict[str, Any]:
        """Observe the environment, call the LLM, and dispatch tool calls.

        Returns:
            A dict summarising what happened:
            ``{"observation": str, "tool_calls": list, "responses": list}``.
        """
        # 1. Build observation from environment.
        observation = await self.env.to_text_prompt(self.agent_id)

        # 2. Assemble messages.
        messages = [
            {"role": "system", "content": self._build_full_system_message()},
            {"role": "user", "content": observation},
        ]

        all_tool_calls: List[Dict] = []
        all_responses: List[Any] = []

        for iteration in range(self.max_iterations):
            # 3. Call LLM with tools.
            response = self.llm_client.complete_with_tools(
                messages=messages,
                tools=self.action_tools,
                temperature=0.7,
                max_tokens=1024,
            )

            choice = response.choices[0]
            assistant_msg = choice.message

            # If the LLM didn't make any tool calls we're done.
            if not assistant_msg.tool_calls:
                logger.debug(
                    "Agent %d: LLM returned no tool calls (iteration %d)",
                    self.agent_id,
                    iteration,
                )
                break

            # 4. Dispatch each tool call.
            # Append the assistant message (with tool_calls) to the
            # conversation so multi-turn works.
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in assistant_msg.tool_calls
                    ],
                }
            )

            for tc in assistant_msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    fn_args = {}

                logger.info(
                    "Agent %d: tool_call %s(%s)",
                    self.agent_id,
                    fn_name,
                    fn_args,
                )

                # Look up the method on the action object.
                method = getattr(self.action, fn_name, None)
                if method is None:
                    result = {"error": f"Unknown action: {fn_name}"}
                else:
                    try:
                        if asyncio.iscoroutinefunction(method):
                            result = await method(**fn_args)
                        else:
                            result = method(**fn_args)
                    except Exception as exc:
                        logger.exception(
                            "Agent %d: error executing %s", self.agent_id, fn_name,
                        )
                        result = {"error": str(exc)}

                all_tool_calls.append({"name": fn_name, "arguments": fn_args})
                all_responses.append(result)

                # Append tool result for multi-turn.
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result) if not isinstance(result, str) else result,
                    }
                )

        return {
            "observation": observation,
            "tool_calls": all_tool_calls,
            "responses": all_responses,
        }

    # ------------------------------------------------------------------
    # Interview (direct Q&A)
    # ------------------------------------------------------------------

    async def perform_interview(self, prompt: str) -> str:
        """Ask the agent a direct question outside the action loop.

        The conversation includes the agent's system prompt (with current
        belief injection) so the answer is in-character.

        Args:
            prompt: The interview question.

        Returns:
            The LLM's text answer.
        """
        messages = [
            {"role": "system", "content": self._build_full_system_message()},
            {"role": "user", "content": prompt},
        ]

        # Add prior interview history for continuity.
        for entry in self.interview_history[-6:]:  # last 6 turns
            messages.insert(-1, {"role": "user", "content": entry["question"]})
            messages.insert(-1, {"role": "assistant", "content": entry["answer"]})

        answer = self.llm_client.complete(
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )

        self.interview_history.append({"question": prompt, "answer": answer})
        return answer

    # ------------------------------------------------------------------
    # Belief / context injection
    # ------------------------------------------------------------------

    def inject_belief_state(self, belief_text: str) -> None:
        """Replace the current belief injection text."""
        self.belief_injection = belief_text

    def inject_cross_platform_context(self, context: str) -> None:
        """Replace the current cross-platform context injection."""
        self.cross_platform_context = context
        self.env.set_extra_context(context)

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<SocialAgent id={self.agent_id} name={self.user_info.name!r}>"
