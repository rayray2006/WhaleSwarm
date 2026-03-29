"""Ontology-guided Named Entity Recognition via LLM."""
import json
import logging
from typing import Any, Dict, List

from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

NER_SYSTEM_PROMPT = """You are a Named Entity Recognition (NER) system. Extract entities and relationships from the given text.

IMPORTANT RULES:
1. Only extract entities matching the provided ontology types.
2. Entities must be SPECIFIC, NAMED real-world actors who could plausibly have social media accounts (people, organizations, companies, etc.).
3. Each entity needs a name, type (from the ontology), a brief summary, and optional attributes.
4. Each relationship needs a source entity name, target entity name, type (from the ontology), and a fact description.
5. If no entities or relationships are found, return empty lists.

NEVER EXTRACT THESE — they are NOT entities:
- Abstract concepts or phenomena: "Iranian Aggression", "Market Volatility", "Climate Change", "Inflation"
- Vague categories: "The Media", "The Public", "Analysts", "Investors", "Critics"
- Economies or sectors: "Iranian Economy", "Tech Sector", "Oil Market", "Housing Market"
- Policies or events: "Sanctions", "Ceasefire", "Trade War", "The Election"
- Geographic areas used as actors: "Iran", "Russia", "Europe", "The West"

INSTEAD, extract the SPECIFIC people and organizations behind them:
- "Iranian Aggression" → extract "Ayatollah Khamenei" (Politician), "IRGC" (GovernmentAgency)
- "The Media" → extract "CNN" (MediaOutlet), "Reuters" (MediaOutlet)
- "Iranian Economy" → extract "Central Bank of Iran" (GovernmentAgency), specific analysts
- "Analysts" → extract specific named analysts like "Mohamed El-Erian" (Analyst)

Every entity MUST have a proper noun name — a name you could Google and find a real person or organization.

ONTOLOGY:
Entity types: {entity_types}
Relationship types: {edge_types}

Return JSON in this exact format:
{{
  "entities": [
    {{"name": "...", "type": "...", "summary": "...", "attributes": {{}}}}
  ],
  "relations": [
    {{"source": "...", "target": "...", "type": "...", "fact": "..."}}
  ]
}}"""


class NERExtractor:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def extract(
        self,
        text: str,
        entity_types: List[str],
        edge_types: List[str],
    ) -> Dict[str, List[Dict]]:
        """Extract entities and relations from text using ontology guidance."""
        system_msg = NER_SYSTEM_PROMPT.format(
            entity_types=", ".join(entity_types),
            edge_types=", ".join(edge_types),
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": (
                f"Extract ALL entities and relationships from this text. Be thorough — "
                f"extract every named person, organization, agency, and company mentioned. "
                f"Aim for at least 8-15 entities per chunk if the text supports it. "
                f"Include diverse types — don't just extract the obvious main actors, "
                f"also get analysts, commentators, affected organizations, and relevant "
                f"institutions.\n\n{text}"
            )},
        ]

        try:
            result = self.llm.complete_json(
                messages, smart=False, temperature=0.3, max_tokens=8192
            )
            if isinstance(result, list):
                result = result[0] if result else {}
            if not isinstance(result, dict):
                return {"entities": [], "relations": []}
            entities = result.get("entities", [])
            relations = result.get("relations", [])

            # Validate entity types
            valid_types = set(entity_types)
            entities = [e for e in entities if e.get("type") in valid_types]

            return {"entities": entities, "relations": relations}
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"NER extraction failed: {e}")
            return {"entities": [], "relations": []}
