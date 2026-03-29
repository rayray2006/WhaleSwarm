"""Vertex AI Gemini LLM client using google-genai SDK with Application Default Credentials."""
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from app.config import Config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OpenAI-compatible response wrappers
# The rest of the codebase (agent.py, etc.) expects response objects that
# look like openai.ChatCompletion.  These lightweight dataclasses provide
# that interface without importing openai.
# ---------------------------------------------------------------------------

@dataclass
class _FunctionCall:
    name: str
    arguments: str  # JSON-encoded string, matching openai SDK convention


@dataclass
class _ToolCall:
    id: str
    type: str
    function: _FunctionCall


@dataclass
class _Message:
    role: str
    content: Optional[str]
    tool_calls: Optional[List[_ToolCall]]


@dataclass
class _Choice:
    message: _Message


@dataclass
class _ChatCompletion:
    choices: List[_Choice]


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

class LLMClient:
    """Vertex AI Gemini LLM client with dual-model routing.

    Primary model: used for bulk tasks (NER, profile gen, agent actions).
    Smart model: used for intelligence-sensitive tasks (ontology, reports).

    Authentication is via Application Default Credentials (ADC).
    Run 'gcloud auth application-default login' to configure ADC locally.

    Provides both sync methods (complete, complete_json, complete_with_tools)
    and an async method (acomplete_with_tools) for use inside the simulation
    event loop.
    """

    def __init__(self, config: Config):
        self.config = config
        try:
            self._client = genai.Client(
                vertexai=True,
                project=config.vertex_project,
                location=config.vertex_location,
            )
        except Exception as exc:
            raise RuntimeError(
                "Failed to initialize Vertex AI client. "
                "Ensure Application Default Credentials are configured: "
                "run 'gcloud auth application-default login'"
            ) from exc

        self._primary_model = self._strip_prefix(config.llm_model_name)
        self._smart_model = self._strip_prefix(
            config.smart_model_name or config.llm_model_name
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """Remove provider prefix (e.g. 'google/') — Vertex AI doesn't use it."""
        return model.removeprefix("google/")

    @staticmethod
    def _convert_messages(messages: List[Dict]) -> tuple:
        """Convert OpenAI-format messages to (system_instruction, gemini_contents).

        Handles system, user, assistant (with optional tool_calls), and tool roles.
        For multi-turn tool use, tool-response messages are matched back to their
        originating function call by tool_call_id to recover the function name.
        """
        system_instruction: Optional[str] = None
        contents: List[types.Content] = []

        for i, msg in enumerate(messages):
            role = msg["role"]

            if role == "system":
                system_instruction = msg.get("content", "")

            elif role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text=msg.get("content", ""))],
                ))

            elif role == "assistant":
                parts: List[types.Part] = []
                if msg.get("content"):
                    parts.append(types.Part(text=msg["content"]))
                for tc in (msg.get("tool_calls") or []):
                    raw_args = tc["function"]["arguments"]
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    parts.append(types.Part(
                        function_call=types.FunctionCall(
                            id=tc.get("id", ""),
                            name=tc["function"]["name"],
                            args=args,
                        )
                    ))
                if parts:
                    contents.append(types.Content(role="model", parts=parts))

            elif role == "tool":
                tool_call_id = msg.get("tool_call_id", "")
                # Scan prior messages to find the function name for this tool_call_id.
                fn_name = ""
                for prior in messages[:i]:
                    if prior.get("role") == "assistant":
                        for tc in (prior.get("tool_calls") or []):
                            if tc.get("id") == tool_call_id:
                                fn_name = tc["function"]["name"]
                                break
                raw = msg.get("content", "")
                try:
                    response_data = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    response_data = {"result": str(raw)}
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(
                        function_response=types.FunctionResponse(
                            id=tool_call_id,
                            name=fn_name,
                            response=response_data,
                        )
                    )],
                ))

        return system_instruction, contents

    @staticmethod
    def _convert_tools(tools: List[Dict]) -> List[types.Tool]:
        """Convert OpenAI tool definitions to Gemini Tool format."""
        declarations = []
        for tool in tools:
            if tool.get("type") == "function":
                fn = tool["function"]
                declarations.append(types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters"),
                ))
        return [types.Tool(function_declarations=declarations)]

    @staticmethod
    def _to_completion(response) -> _ChatCompletion:
        """Wrap a Gemini GenerateContentResponse in an OpenAI-compatible object."""
        if not response.candidates:
            return _ChatCompletion(
                choices=[_Choice(
                    message=_Message(role="assistant", content="", tool_calls=None)
                )]
            )

        parts = response.candidates[0].content.parts or []
        text_parts = [p.text for p in parts if getattr(p, "text", None)]
        fn_parts = [p for p in parts if getattr(p, "function_call", None)]

        content = "\n".join(text_parts) if text_parts else None
        tool_calls = None
        if fn_parts:
            tool_calls = []
            for p in fn_parts:
                fc = p.function_call
                call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
                tool_calls.append(_ToolCall(
                    id=call_id,
                    type="function",
                    function=_FunctionCall(
                        name=fc.name,
                        arguments=json.dumps(dict(fc.args)),
                    ),
                ))

        return _ChatCompletion(
            choices=[_Choice(
                message=_Message(role="assistant", content=content, tool_calls=tool_calls)
            )]
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        messages: List[Dict[str, str]],
        smart: bool = False,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        model_override: Optional[str] = None,
    ) -> str:
        """Call LLM and return the response text."""
        model = self._strip_prefix(
            model_override or (self._smart_model if smart else self._primary_model)
        )
        system_instruction, contents = self._convert_messages(messages)
        config_kwargs: Dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            # Disable thinking for text/JSON generation — bulk tasks don't benefit
            # from reasoning and it adds significant latency.
            "thinking_config": types.ThinkingConfig(thinking_budget=0),
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if json_mode:
            config_kwargs["response_mime_type"] = "application/json"

        logger.debug("LLM call: model=%s, smart=%s, msgs=%d", model, smart, len(messages))
        response = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        content = response.text or ""
        logger.debug("LLM response: %d chars", len(content))
        return content

    def complete_json(
        self,
        messages: List[Dict[str, str]],
        smart: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> Any:
        """Call LLM and parse the response as JSON."""
        text = self.complete(
            messages, smart=smart, json_mode=True,
            temperature=temperature, max_tokens=max_tokens,
        )
        return self._parse_json(text)

    def complete_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        smart: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> _ChatCompletion:
        """Call LLM with tool definitions and return an OpenAI-compatible response (sync)."""
        model = self._smart_model if smart else self._primary_model
        system_instruction, contents = self._convert_messages(messages)
        config_kwargs: Dict[str, Any] = {
            "tools": self._convert_tools(tools),
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        response = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return self._to_completion(response)

    async def acomplete_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        smart: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> _ChatCompletion:
        """Call LLM with tool definitions and return an OpenAI-compatible response (async).

        Use this inside asyncio event loops (e.g. the simulation engine) so that
        other coroutines and platform message loops are not blocked.
        """
        model = self._smart_model if smart else self._primary_model
        system_instruction, contents = self._convert_messages(messages)
        config_kwargs: Dict[str, Any] = {
            "tools": self._convert_tools(tools),
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        response = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return self._to_completion(response)

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Robustly parse JSON from LLM output.

        Handles common LLM issues: markdown fences, trailing commas,
        single-line comments, etc.
        """
        import re

        text = text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Remove single-line comments and trailing commas
        text = re.sub(r'//[^\n]*', '', text)
        text = re.sub(r',\s*([}\]])', r'\1', text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Extract JSON object/array from surrounding text
        for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
            match = re.search(pattern, text)
            if match:
                candidate = re.sub(r',\s*([}\]])', r'\1', match.group())
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

        raise json.JSONDecodeError(
            f"Could not parse LLM JSON output (len={len(text)})",
            text[:200], 0,
        )
