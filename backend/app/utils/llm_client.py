"""OpenAI-compatible LLM client with dual-model routing."""
import json
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI, AsyncOpenAI

from app.config import Config

logger = logging.getLogger(__name__)


class LLMClient:
    """LLM client supporting OpenAI-compatible APIs and dual-model routing.

    Primary model: used for bulk tasks (NER, profile gen).
    Smart model: used for intelligence-sensitive tasks (ontology, reports).

    Provides both sync methods (complete, complete_json, complete_with_tools)
    for non-async callers and async methods (acomplete_with_tools) for use
    inside the simulation event loop.
    """

    def __init__(self, config: Config):
        self.config = config

        # Sync clients (used by Flask routes, graph builder, etc.)
        self._primary = OpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        self._primary_model = config.llm_model_name

        self._smart = OpenAI(
            api_key=config.smart_api_key,
            base_url=config.smart_base_url,
        )
        self._smart_model = config.smart_model_name

        # Async clients (used by simulation engine inside asyncio loop)
        self._async_primary = AsyncOpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        self._async_smart = AsyncOpenAI(
            api_key=config.smart_api_key,
            base_url=config.smart_base_url,
        )

    def complete(
        self,
        messages: List[Dict[str, str]],
        smart: bool = False,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        model_override: Optional[str] = None,
    ) -> str:
        """Call LLM and return the response text.

        Args:
            messages: Chat messages in OpenAI format.
            smart: Use the smart model for intelligence-sensitive tasks.
            json_mode: Request JSON output.
            temperature: Sampling temperature.
            max_tokens: Max tokens in response.
            model_override: Override the model name.
        """
        client = self._smart if smart else self._primary
        model = model_override or (self._smart_model if smart else self._primary_model)

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Skip json_mode for Gemini — it doesn't support response_format reliably
        is_gemini = "gemini" in model.lower() or "generativelanguage" in (
            client.base_url.host if hasattr(client.base_url, 'host') else str(client.base_url)
        )
        if json_mode and not is_gemini:
            kwargs["response_format"] = {"type": "json_object"}

        logger.debug(f"LLM call: model={model}, smart={smart}, msgs={len(messages)}")

        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""

        logger.debug(f"LLM response: {len(content)} chars")
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

    @staticmethod
    def _parse_json(text: str) -> Any:
        """Robustly parse JSON from LLM output.

        Handles common LLM issues: markdown fences, trailing commas,
        single-line comments, unquoted keys, etc.
        """
        import re

        text = text.strip()

        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # Try parsing as-is first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Remove single-line comments (// ...)
        text = re.sub(r'//[^\n]*', '', text)

        # Remove trailing commas before } or ]
        text = re.sub(r',\s*([}\]])', r'\1', text)

        # Try again
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Extract JSON object/array from surrounding text
        for pattern in [r'\{[\s\S]*\}', r'\[[\s\S]*\]']:
            match = re.search(pattern, text)
            if match:
                candidate = match.group()
                # Clean trailing commas again
                candidate = re.sub(r',\s*([}\]])', r'\1', candidate)
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

        # Last resort: raise with the cleaned text for debugging
        raise json.JSONDecodeError(
            f"Could not parse LLM JSON output (len={len(text)})",
            text[:200], 0,
        )

    def complete_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        smart: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> Dict:
        """Call LLM with tool definitions and return the full response (sync)."""
        client = self._smart if smart else self._primary
        model = self._smart_model if smart else self._primary_model

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response

    async def acomplete_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        smart: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 16384,
    ) -> Dict:
        """Call LLM with tool definitions and return the full response (async).

        Use this inside asyncio event loops (e.g. the simulation engine)
        so that other coroutines and platform message loops are not blocked.
        """
        client = self._async_smart if smart else self._async_primary
        model = self._smart_model if smart else self._primary_model

        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response
