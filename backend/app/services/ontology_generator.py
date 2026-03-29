"""Ontology generation from documents via Smart LLM."""
import logging
from typing import Any, Dict

from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

ONTOLOGY_SYSTEM_PROMPT = """You are an ontology designer for a social media simulation engine.

Given document text and a simulation requirement, design an ontology with:
1. Entity types: 12-18 types of actors who could plausibly have social media accounts
2. Edge types: 8-12 relationship types between these actors

CRITICAL RULES FOR ENTITY TYPES:
- Every entity type MUST be a person or institution that could post on Twitter/Reddit.
- INDIVIDUALS: Politician, Journalist, Analyst, Activist, Diplomat, MilitaryOfficial, Researcher, Investor, Trader, Influencer, Lawyer, Executive, Professor, Student, Commentator, GameDeveloper, Engineer, Designer, ContentCreator, Athlete, Coach
- INSTITUTIONS: MediaOutlet, Company, NGO, ThinkTank, GovernmentAgency, Studio, Publisher, League (these post as official accounts)
- ALWAYS include "Person" and "Organization" as generic fallback types at the end.

BANNED ENTITY TYPES (never use these):
- State, Country, Nation, Region, Territory, City, Continent — geographic areas are NOT social media actors
- Government, InternationalOrganization, Alliance, Bloc — too abstract; use specific officials or agencies instead
- Topic, Viewpoint, Concept, Event, Theory, Policy — abstract concepts
- MilitaryUnit, Army, Fleet — not social media actors
- Citizen, People — too vague

If the domain involves countries (e.g., geopolitics), extract the PEOPLE who represent those countries:
  - Instead of "Russia" → "Vladimir Putin" (Politician), "Kremlin" (GovernmentAgency)
  - Instead of "NATO" → "NATO Secretary General" (Diplomat)
  - Instead of "United States" → "Joe Biden" (Politician), "State Department" (GovernmentAgency)

MULTI-DOMAIN BALANCE:
If the text covers multiple domains (e.g., geopolitics AND gaming, technology AND finance, sports AND politics), you MUST include entity types from EVERY domain mentioned. Allocate types proportionally. Do NOT let one domain consume all slots.

Example: if text covers a Russia-Ukraine ceasefire AND GTA VI release, you need types for BOTH:
  Geopolitics: Politician, Diplomat, MilitaryOfficial, Analyst, Activist, Journalist
  Gaming: GameDeveloper, Executive, ContentCreator, Company, Influencer

Return JSON:
{
  "entity_types": ["Type1", "Type2", ...],
  "edge_types": ["RELATIONSHIP_1", "RELATIONSHIP_2", ...],
  "analysis_summary": "List ALL domains found and how entity types cover each domain."
}"""

# Types that must never become entity types (post-LLM validation).
_BANNED_TYPES = {
    "state", "country", "nation", "region", "territory", "city",
    "continent", "government", "internationalorganization",
    "alliance", "bloc", "militaryunit", "army", "fleet",
    "topic", "viewpoint", "concept", "event", "theory", "policy",
    "citizen", "people", "headofstate",
}


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
            import json as _json
            try:
                result = _json.loads(result)
            except _json.JSONDecodeError:
                raise ValueError(f"LLM returned unparseable string: {result[:200]}")
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict from LLM, got {type(result).__name__}: {str(result)[:200]}")

        # Post-validate: strip banned entity types.
        entity_types = result.get("entity_types", [])
        edge_types = result.get("edge_types", [])

        original_count = len(entity_types)
        entity_types = [t for t in entity_types if t.lower() not in _BANNED_TYPES]

        if original_count != len(entity_types):
            removed = [t for t in result["entity_types"] if t.lower() in _BANNED_TYPES]
            logger.warning("Removed %d banned entity types: %s", len(removed), removed)

        # Ensure fallback types exist.
        for fallback in ("Person", "Organization"):
            if fallback not in entity_types:
                entity_types.append(fallback)

        result["entity_types"] = entity_types

        if len(entity_types) < 3:
            raise ValueError(f"Too few entity types after filtering: {len(entity_types)}")

        logger.info(
            f"Ontology generated: {len(entity_types)} entity types, "
            f"{len(edge_types)} edge types"
        )
        return result
