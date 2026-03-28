"""Web enrichment for public figures and thin entities."""
import logging
from typing import Optional

from app.config import Config
from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

ENRICHMENT_TRIGGERS = {"Politician", "CEO", "PublicFigure", "Celebrity"}
MIN_SUMMARY_LENGTH = 150


class WebEnricher:
    def __init__(self, llm_client: LLMClient, config: Config):
        self.llm = llm_client
        self.config = config

    def should_enrich(self, entity_type: str, summary: str) -> bool:
        if not self.config.web_enrichment_enabled:
            return False
        if entity_type in ENRICHMENT_TRIGGERS:
            return True
        if len(summary or "") < MIN_SUMMARY_LENGTH:
            return True
        return False

    def enrich(self, name: str, entity_type: str, existing_summary: str) -> str:
        """Enrich an entity with additional background information."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a research assistant. Provide a concise 2-3 paragraph "
                    "background on the given person or organization, covering their "
                    "role, public positions, and notable activities. Be factual."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"What do you know about {name} ({entity_type})?\n"
                    f"Existing context: {existing_summary}\n\n"
                    f"Provide additional background information."
                ),
            },
        ]

        # Use web search model if available, otherwise standard LLM
        model_override = self.config.web_search_model if self.config.web_search_model else None

        try:
            result = self.llm.complete(
                messages,
                smart=True,
                temperature=0.3,
                max_tokens=1024,
                model_override=model_override,
            )
            return f"{existing_summary}\n\n{result}".strip()
        except Exception as e:
            logger.warning(f"Web enrichment failed for {name}: {e}")
            return existing_summary
