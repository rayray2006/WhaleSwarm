"""Ontology generation from documents via Smart LLM."""
import json
import logging
from typing import Any, Dict

from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

ONTOLOGY_SYSTEM_PROMPT = """You are an ontology designer for a social media simulation engine.

Given document text and a simulation requirement, you must design an ontology that defines:
1. Entity types: 8-10 types of real-world social media actors found in the documents
2. Edge types: 6-10 relationship types between these actors

CRITICAL RULES:
- Entity types MUST be real-world "accounts" that could plausibly speak on social media
  GOOD: Student, Professor, CEO, Company, Journalist, Politician, Organization, MediaOutlet
  BAD: Topic, Viewpoint, Concept, Event, Theory, Policy (these are abstract, not actors)
- Produce exactly 8-10 entity types: identify the specific types relevant to the documents, plus 1-2 generic fallback types (like "Person" or "Organization")
- 6-10 relationship types describing connections between entities (WORKS_FOR, ADVISES, COLLABORATES_WITH, etc.)
- Return a brief analysis summary explaining the document domain

Return JSON in this exact format:
{
  "entity_types": ["Type1", "Type2", ...],
  "edge_types": ["RELATIONSHIP_1", "RELATIONSHIP_2", ...],
  "analysis_summary": "Brief description of the document domain and key themes."
}"""


class OntologyGenerator:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def generate(self, text: str, simulation_requirement: str, additional_context: str = "") -> Dict[str, Any]:
        """Generate ontology from document text and simulation requirement."""
        user_content = f"""SIMULATION REQUIREMENT:
{simulation_requirement}

{f'ADDITIONAL CONTEXT: {additional_context}' if additional_context else ''}

DOCUMENT TEXT (first 8000 chars):
{text[:8000]}

Design the ontology for this simulation."""

        messages = [
            {"role": "system", "content": ONTOLOGY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        result = self.llm.complete_json(
            messages, smart=True, temperature=0.5, max_tokens=16384
        )

        # Handle LLM returning unexpected types
        if isinstance(result, list):
            result = result[0] if result else {}
        if isinstance(result, str):
            # Try parsing the string as JSON
            import json as _json
            try:
                result = _json.loads(result)
            except _json.JSONDecodeError:
                raise ValueError(f"LLM returned unparseable string: {result[:200]}")
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from LLM, got {type(result).__name__}: {str(result)[:200]}")

        # Validate
        entity_types = result.get("entity_types", [])
        edge_types = result.get("edge_types", [])

        if len(entity_types) < 5:
            raise ValueError(f"Too few entity types: {len(entity_types)}")

        logger.info(
            f"Ontology generated: {len(entity_types)} entity types, "
            f"{len(edge_types)} edge types"
        )
        return result
