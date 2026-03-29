"""LLM-based topic research for Polymarket markets.

Generates comprehensive background text about a market topic by querying
the LLM from 5 different research angles, scoped by a focused brief that
identifies the key actors and factors that actually move the market.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


class TopicResearcher:
    """Generates background research text about a market topic via LLM."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    # ------------------------------------------------------------------
    # Step 0: Focused brief
    # ------------------------------------------------------------------

    def _generate_brief(
        self, market_question: str, market_description: str,
    ) -> Dict[str, Any]:
        """Identify the 15-25 key actors and factors that directly influence
        the market outcome.  Returns a structured brief used to scope all
        subsequent research prompts."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a prediction-market analyst. Given a market "
                    "question, identify ONLY the people, organizations, "
                    "countries, and factors that DIRECTLY influence whether "
                    "this prediction resolves YES or NO.\n\n"
                    "Be ruthlessly focused. Exclude historical background "
                    "figures, peripheral mentions, and anyone who does not "
                    "have direct decision-making power or measurable "
                    "influence on the outcome.\n\n"
                    "Return JSON:\n"
                    "{\n"
                    '  "key_actors": [\n'
                    '    {"name": "...", "role": "...", "why_relevant": "..."}\n'
                    "  ],\n"
                    '  "key_factors": [\n'
                    '    "factor that could tip the outcome either way"\n'
                    "  ],\n"
                    '  "scope_summary": "2-3 sentence summary of what matters for this prediction"\n'
                    "}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Market question: {market_question}\n\n"
                    f"Description: {market_description or 'N/A'}"
                ),
            },
        ]

        try:
            brief = self.llm.complete_json(
                messages, smart=True, temperature=0.3, max_tokens=4096,
            )
            if not isinstance(brief, dict):
                brief = {}
        except Exception:
            logger.exception("Brief generation failed, using empty brief")
            brief = {}

        # Build a human-readable scoping text from the brief
        actors = brief.get("key_actors", [])
        factors = brief.get("key_factors", [])
        scope = brief.get("scope_summary", "")

        actor_lines = []
        for a in actors[:25]:
            name = a.get("name", "")
            role = a.get("role", "")
            why = a.get("why_relevant", "")
            actor_lines.append(f"- {name} ({role}): {why}")

        brief["_scoping_text"] = (
            f"SCOPE: {scope}\n\n"
            f"KEY ACTORS (focus on these):\n"
            + "\n".join(actor_lines)
            + "\n\nKEY FACTORS:\n"
            + "\n".join(f"- {f}" for f in factors[:10])
        )

        logger.info(
            "Research brief: %d actors, %d factors",
            len(actors), len(factors),
        )
        return brief

    # ------------------------------------------------------------------
    # Step 1-5: Scoped research
    # ------------------------------------------------------------------

    def research(
        self,
        market_question: str,
        market_description: str = "",
        progress_cb=None,
    ) -> str:
        """Generate comprehensive background text about a market topic.

        First generates a focused brief identifying key actors, then
        makes 5 scoped research calls.  Returns concatenated text
        (~5000-8000 words) suitable for the ontology/NER pipeline.
        """
        # Step 0: Generate scoping brief
        if progress_cb:
            progress_cb(5, "Analyzing market...")
        brief = self._generate_brief(market_question, market_description)
        scoping = brief.get("_scoping_text", "")

        # Define research angles — each prompt includes scoping context
        angles = [
            {
                "label": "Key Decision Makers & Their Positions",
                "prompt": (
                    "Write a detailed article about the key decision makers "
                    "who will directly determine the outcome of this "
                    "prediction. For each person or organization, explain "
                    "their current position, what they want, and what would "
                    "make them change course. Focus ONLY on actors with "
                    "direct influence on the outcome.\n\n"
                    f"Prediction: {market_question}\n\n"
                    f"{scoping}"
                ),
            },
            {
                "label": "Factors Favoring YES",
                "prompt": (
                    "Write a detailed analytical article presenting the "
                    "strongest arguments and evidence that this prediction "
                    "will resolve YES. Focus on concrete actions, decisions, "
                    "and conditions that are currently pushing toward YES. "
                    "Reference specific actors and their motivations.\n\n"
                    f"Prediction: {market_question}\n\n"
                    f"{scoping}"
                ),
            },
            {
                "label": "Factors Favoring NO",
                "prompt": (
                    "Write a detailed analytical article presenting the "
                    "strongest arguments and evidence that this prediction "
                    "will resolve NO. Focus on concrete obstacles, opposing "
                    "actors, and conditions blocking the outcome. Reference "
                    "specific actors and their motivations.\n\n"
                    f"Prediction: {market_question}\n\n"
                    f"{scoping}"
                ),
            },
            {
                "label": "Current Negotiations & Timeline",
                "prompt": (
                    "Write a detailed article about the current state of "
                    "affairs. What has happened in the last few months? "
                    "What specific events, meetings, or decisions are "
                    "upcoming? What is the realistic timeline? Focus on "
                    "facts and developments directly relevant to whether "
                    "this prediction resolves YES or NO.\n\n"
                    f"Prediction: {market_question}\n\n"
                    f"{scoping}"
                ),
            },
            {
                "label": "Wildcards & Scenario Analysis",
                "prompt": (
                    "Write a detailed article about unexpected events or "
                    "scenarios that could dramatically shift this prediction. "
                    "Consider: leadership changes, elections, economic "
                    "shocks, military developments, or diplomatic "
                    "breakthroughs. For each wildcard, explain which "
                    "direction it would push the outcome and how likely "
                    "it is.\n\n"
                    f"Prediction: {market_question}\n\n"
                    f"{scoping}"
                ),
            },
        ]

        sections = []
        total = len(angles)

        for i, angle in enumerate(angles):
            label = angle["label"]
            if progress_cb:
                pct = int(10 + (i / total) * 50)
                progress_cb(pct, f"Researching: {label}")

            logger.info("Researching [%d/%d]: %s", i + 1, total, label)

            try:
                text = self.llm.complete(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a prediction-market research analyst "
                                "writing focused, factual articles. Write "
                                "800-1500 words. Use specific names, dates, "
                                "and facts. Stay strictly relevant to the "
                                "prediction question — do not include "
                                "tangential history or peripheral actors. "
                                "Do not use markdown headers."
                            ),
                        },
                        {"role": "user", "content": angle["prompt"]},
                    ],
                    smart=True,
                    temperature=0.5,
                    max_tokens=4096,
                )
                sections.append(f"=== {label.upper()} ===\n\n{text.strip()}")
                logger.info("  -> %d chars", len(text))
            except Exception:
                logger.exception("Failed to research angle: %s", label)
                sections.append(
                    f"=== {label.upper()} ===\n\n(research unavailable)"
                )

        combined = "\n\n\n".join(sections)
        logger.info(
            "Topic research complete: %d sections, %d total chars",
            len(sections), len(combined),
        )
        return combined
