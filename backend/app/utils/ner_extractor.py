"""Ontology-guided Named Entity Recognition via LLM."""
import json
import logging
from typing import Any, Dict, List

from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

NER_SYSTEM_PROMPT = """You are a Named Entity Recognition (NER) system. Extract entities and relationships from the given text.

IMPORTANT RULES:
1. Only extract entities matching the provided ontology types.
2. Extract BROADLY — get every named person, company, organization, government agency, and country mentioned or implied by the text.
3. Each entity needs a name, type (from the ontology), a brief summary, and optional attributes.
4. Each relationship needs a source entity name, target entity name, type (from the ontology), and a fact description.
5. If no entities or relationships are found, return empty lists.

WHAT TO EXTRACT (be comprehensive):
- Named people: politicians, executives, analysts, journalists, diplomats, military leaders, investors, activists
- Companies and corporations: any company mentioned or relevant to the topic
- Government agencies: specific agencies like "Pentagon", "SEC", "Federal Reserve", "IRGC"
- Countries: extract countries as GovernmentAgency entities (e.g., "United States", "Iran", "China") — they are key actors
- Media outlets: specific news organizations
- NGOs, think tanks, international organizations: "NATO", "IMF", "WHO", "Brookings"
- Also extract people NOT directly mentioned but clearly relevant — if the text discusses US foreign policy, include the President even if not named

DO NOT EXTRACT:
- Abstract concepts: "Market Volatility", "Inflation", "Aggression", "Trade War"
- Vague unnamed groups: "The Media", "The Public", "Analysts", "Critics", "Investors"
- Sectors or economies as entities: "Tech Sector", "Oil Market"

Be EXPANSIVE — extract 10-20 entities per chunk. Include the obvious main actors AND the supporting cast (advisors, agencies, affected companies, allied/opposing countries).

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
                f"Extract ALL entities and relationships from this text. Be thorough and broad:\n"
                f"- Extract every named person, company, organization, agency, and country\n"
                f"- Include people not explicitly named but clearly implied (e.g., a country's leader)\n"
                f"- Aim for 10-20 entities — get the main actors AND the supporting cast\n"
                f"- Most entities should be real people, companies, or countries\n\n{text}"
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
