"""ReACT-loop report agent: Reason-Act-Observe for report generation.

The agent plans a table of contents, then for each section:
  THOUGHT -> SEARCH -> OBSERVE -> WRITE -> REFLECT (with retry).

Also supports follow-up conversation mode over a completed report.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from app.config import Config
from app.services.graph_tools import GraphToolsService, InsightForgeResult
from app.services.simulation_ipc import (
    get_posts_from_db,
    get_recent_actions,
    get_run_state_from_actions,
    get_trades_from_db,
)
from app.storage.neo4j_storage import Neo4jStorage
from app.utils.embedding_service import EmbeddingService
from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

MAX_REFLECTION_ROUNDS = 2
PLATFORMS = ["twitter", "reddit", "polymarket"]


# ======================================================================
# Report Logger -- writes every agent action to agent_log.jsonl
# ======================================================================


class ReportLogger:
    """Append-only JSON-lines logger for the agent loop."""

    def __init__(self, log_dir: str):
        os.makedirs(log_dir, exist_ok=True)
        self._path = os.path.join(log_dir, "agent_log.jsonl")

    def log(self, event: str, data: Optional[Dict] = None):
        entry = {
            "ts": time.time(),
            "event": event,
            **(data or {}),
        }
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception:
            logger.debug("Failed to write agent log entry", exc_info=True)


# ======================================================================
# Section dataclass
# ======================================================================


@dataclass
class ReportSection:
    title: str
    description: str = ""
    content: str = ""
    search_results: List[Dict] = field(default_factory=list)
    reflection_notes: str = ""
    rounds_used: int = 0


# ======================================================================
# ReportAgent
# ======================================================================


class ReportAgent:
    """Generate comprehensive markdown reports using a ReACT loop."""

    def __init__(
        self,
        storage: Neo4jStorage,
        llm: LLMClient,
        embedder: EmbeddingService,
        config: Config,
    ):
        self.storage = storage
        self.llm = llm
        self.embedder = embedder
        self.config = config
        self.graph_tools = GraphToolsService(storage, llm, embedder, config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_report(
        self,
        simulation_id: str,
        graph_id: str,
        sim_requirement: str,
        sim_dir: str,
        config: Config,
        progress_cb=None,
    ) -> str:
        """Run the full ReACT loop and return a markdown report.

        Args:
            simulation_id: ID of the simulation.
            graph_id: ID of the knowledge graph.
            sim_requirement: The simulation requirement / research question.
            sim_dir: Path to the simulation output directory.
            config: App config.
            progress_cb: Optional callable(percent: int, message: str).

        Returns:
            Markdown string of the completed report.
        """
        report_dir = os.path.join(config.upload_dir, "reports", simulation_id)
        os.makedirs(report_dir, exist_ok=True)
        rlog = ReportLogger(report_dir)
        rlog.log("report_start", {"simulation_id": simulation_id, "graph_id": graph_id})

        def _progress(pct: int, msg: str):
            rlog.log("progress", {"percent": pct, "message": msg})
            if progress_cb:
                progress_cb(pct, msg)

        _progress(5, "Gathering simulation context")

        # Gather simulation context
        sim_context = self._gather_simulation_context(sim_dir)
        rlog.log("sim_context_gathered", {"action_count": sim_context.get("action_count", 0)})

        # Step 1: PLAN -- generate table of contents
        _progress(10, "Planning report outline")
        sections = self._plan_outline(sim_requirement, sim_context, graph_id)
        rlog.log("outline_planned", {"sections": [s.title for s in sections]})

        total_sections = len(sections)

        # Step 2: For each section, run the ReACT loop
        for idx, section in enumerate(sections):
            section_pct_base = 15 + int(70 * idx / total_sections)
            _progress(section_pct_base, f"Writing section: {section.title}")
            rlog.log("section_start", {"section": section.title, "index": idx})

            self._write_section(
                section=section,
                graph_id=graph_id,
                sim_requirement=sim_requirement,
                sim_dir=sim_dir,
                sim_context=sim_context,
                rlog=rlog,
            )
            rlog.log("section_done", {"section": section.title, "rounds": section.rounds_used})

        # Step 3: Assemble final report
        _progress(90, "Assembling final report")
        markdown = self._assemble_report(sections, sim_requirement, sim_context)
        rlog.log("report_assembled", {"length": len(markdown)})

        # Save report to disk
        report_path = os.path.join(report_dir, "report.md")
        with open(report_path, "w") as f:
            f.write(markdown)

        _progress(100, "Report complete")
        rlog.log("report_complete", {"path": report_path})
        return markdown

    def conversation(
        self,
        report_id: str,
        question: str,
        history: List[Dict[str, str]],
        config: Config,
        graph_id: Optional[str] = None,
        sim_dir: Optional[str] = None,
    ) -> str:
        """Follow-up conversation over a completed report.

        Searches graph for additional context and answers the question using
        the report + conversation history.
        """
        # Load the existing report if available
        report_dir = os.path.join(config.upload_dir, "reports", report_id)
        report_path = os.path.join(report_dir, "report.md")
        report_text = ""
        if os.path.exists(report_path):
            with open(report_path) as f:
                report_text = f.read()

        # Optionally search graph for more context
        extra_context = ""
        if graph_id:
            try:
                results = self.graph_tools.quick_search(question, graph_id, top_k=5)
                if results:
                    facts = [
                        f"- {r['name']}: {r.get('summary', '')}" for r in results
                    ]
                    extra_context = "\n\nRelevant graph entities:\n" + "\n".join(facts)
            except Exception:
                logger.debug("Graph search failed in conversation mode", exc_info=True)

        # Optionally pull recent simulation data
        sim_data_context = ""
        if sim_dir and os.path.isdir(sim_dir):
            try:
                recent = get_recent_actions(sim_dir, limit=10)
                if recent:
                    lines = []
                    for a in recent[-5:]:
                        lines.append(
                            f"- Round {a.get('_round', '?')}: "
                            f"{a.get('agent_name', '?')} did {a.get('action', '?')} "
                            f"on {a.get('platform', '?')}"
                        )
                    sim_data_context = "\n\nRecent simulation activity:\n" + "\n".join(lines)
            except Exception:
                pass

        # Build messages
        system_prompt = (
            "You are a research analyst assistant. You have access to a completed "
            "simulation report and a knowledge graph. Answer the user's question "
            "based on the report and any additional context provided. "
            "Be specific, cite entities and data points when possible."
        )

        messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]

        # Include report as context (truncate if very long)
        report_excerpt = report_text[:12000] if len(report_text) > 12000 else report_text
        if report_excerpt:
            messages.append({
                "role": "user",
                "content": f"[REPORT CONTEXT]\n{report_excerpt}",
            })
            messages.append({
                "role": "assistant",
                "content": "I have reviewed the report. How can I help?",
            })

        # Append conversation history
        for msg in history:
            messages.append(msg)

        # Final user question with extra context
        user_content = question
        if extra_context:
            user_content += extra_context
        if sim_data_context:
            user_content += sim_data_context
        messages.append({"role": "user", "content": user_content})

        response = self.llm.complete(
            messages, smart=True, temperature=0.5, max_tokens=4096
        )
        return response

    # ------------------------------------------------------------------
    # Private: Plan outline
    # ------------------------------------------------------------------

    def _plan_outline(
        self,
        sim_requirement: str,
        sim_context: Dict,
        graph_id: str,
    ) -> List[ReportSection]:
        """Smart LLM generates a 5-8 section table of contents."""
        # Get a quick sense of what entities exist
        entity_sample = ""
        try:
            entities = self.storage.get_entities(graph_id)[:20]
            entity_names = [e["name"] for e in entities]
            entity_sample = ", ".join(entity_names)
        except Exception:
            pass

        action_summary = ""
        counts = sim_context.get("action_counts", {})
        if counts:
            action_summary = ", ".join(f"{k}: {v}" for k, v in counts.items())

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a research report planner. Generate a table of contents "
                    "for an analytical report about a social simulation. "
                    "Return a JSON object with key 'sections', each section having "
                    "'title' and 'description'. Generate 5-8 sections. "
                    "Always include: Executive Summary, Methodology, Key Findings, "
                    "and Conclusion sections. Fill in topic-specific sections between them."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Simulation requirement: {sim_requirement}\n"
                    f"Rounds completed: {sim_context.get('rounds_completed', '?')}\n"
                    f"Agent action counts: {action_summary}\n"
                    f"Key entities in knowledge graph: {entity_sample}\n"
                    f"\nGenerate the report outline."
                ),
            },
        ]

        try:
            result = self.llm.complete_json(messages, smart=True, temperature=0.4)
            if isinstance(result, list):
                result = result[0] if result and isinstance(result[0], dict) else {}
            raw_sections = result.get("sections", []) if isinstance(result, dict) else []
            if isinstance(raw_sections, list) and len(raw_sections) >= 3:
                return [
                    ReportSection(
                        title=s.get("title", f"Section {i+1}"),
                        description=s.get("description", ""),
                    )
                    for i, s in enumerate(raw_sections[:8])
                ]
        except Exception:
            logger.exception("Failed to plan outline, using defaults")

        # Fallback outline
        return [
            ReportSection(title="Executive Summary", description="High-level overview of findings"),
            ReportSection(title="Methodology", description="How the simulation was conducted"),
            ReportSection(title="Agent Behavior Analysis", description="How agents behaved across platforms"),
            ReportSection(title="Market Dynamics", description="Trading patterns and price movements"),
            ReportSection(title="Information Flow", description="How information spread across platforms"),
            ReportSection(title="Conclusion", description="Key takeaways and implications"),
        ]

    # ------------------------------------------------------------------
    # Private: Write a single section via ReACT
    # ------------------------------------------------------------------

    def _write_section(
        self,
        section: ReportSection,
        graph_id: str,
        sim_requirement: str,
        sim_dir: str,
        sim_context: Dict,
        rlog: ReportLogger,
    ):
        """ReACT loop for a single section: THOUGHT -> SEARCH -> OBSERVE -> WRITE -> REFLECT."""
        for round_num in range(1 + MAX_REFLECTION_ROUNDS):
            section.rounds_used = round_num + 1

            # THOUGHT: What do I need to know?
            thought = self._thought_step(section, sim_requirement, round_num)
            rlog.log("thought", {"section": section.title, "round": round_num, "thought": thought})

            # SEARCH: Call graph tools
            search_query = thought if thought else f"{section.title}: {section.description}"
            search_results = self._search_step(search_query, graph_id, sim_requirement, rlog)
            section.search_results.extend(search_results.get("entity_insights", []))

            # OBSERVE: Get simulation feed data
            observations = self._observe_step(sim_dir, section.title, sim_context)
            rlog.log("observe", {"section": section.title, "obs_keys": list(observations.keys())})

            # WRITE: LLM composes section text
            section.content = self._write_step(
                section=section,
                search_results=search_results,
                observations=observations,
                sim_requirement=sim_requirement,
                round_num=round_num,
            )
            rlog.log("write", {"section": section.title, "round": round_num, "length": len(section.content)})

            # REFLECT: Self-critique
            if round_num < MAX_REFLECTION_ROUNDS:
                reflection = self._reflect_step(section, sim_requirement)
                rlog.log("reflect", {"section": section.title, "reflection": reflection})
                section.reflection_notes = reflection

                # If no significant gaps, stop early
                if self._reflection_is_satisfied(reflection):
                    rlog.log("reflect_satisfied", {"section": section.title})
                    break
            else:
                break

    def _thought_step(self, section: ReportSection, sim_requirement: str, round_num: int) -> str:
        """Generate a thought: what do I need to know for this section?"""
        prior = ""
        if round_num > 0 and section.reflection_notes:
            prior = f"\nPrevious reflection identified these gaps: {section.reflection_notes}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a research analyst planning what information to gather "
                    "for a report section. Output a concise 1-2 sentence search query "
                    "that would find the most relevant information. Return plain text, not JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Report topic: {sim_requirement}\n"
                    f"Section: {section.title}\n"
                    f"Section description: {section.description}{prior}\n"
                    f"What should I search for?"
                ),
            },
        ]
        try:
            return self.llm.complete(messages, smart=False, temperature=0.3, max_tokens=256).strip()
        except Exception:
            return f"{section.title} {section.description}"

    def _search_step(
        self, query: str, graph_id: str, sim_requirement: str, rlog: ReportLogger
    ) -> Dict[str, Any]:
        """Search the knowledge graph. Prefer InsightForge, fall back gracefully."""
        rlog.log("search_start", {"query": query})

        # Try InsightForge first
        try:
            result = self.graph_tools.insight_forge(
                query=query,
                graph_id=graph_id,
                simulation_requirement=sim_requirement,
                top_k_per_sub=4,
            )
            rlog.log("search_insightforge", {
                "facts": len(result.semantic_facts),
                "entities": len(result.entity_insights),
                "chains": len(result.relationship_chains),
            })
            return {
                "tool": "InsightForge",
                "semantic_facts": result.semantic_facts,
                "entity_insights": result.entity_insights,
                "relationship_chains": result.relationship_chains,
                "sub_queries": result.sub_queries,
            }
        except Exception:
            logger.debug("InsightForge failed, falling back to PanoramaSearch", exc_info=True)

        # Fall back to PanoramaSearch
        try:
            results = self.graph_tools.panorama_search(query, graph_id, top_k=6)
            facts = [r.get("summary", "") for r in results if r.get("summary")]
            chains = []
            for r in results:
                chains.extend(r.get("relationship_chains", []))
            rlog.log("search_panorama", {"nodes": len(results), "chains": len(chains)})
            return {
                "tool": "PanoramaSearch",
                "semantic_facts": facts,
                "entity_insights": results,
                "relationship_chains": chains,
                "sub_queries": [],
            }
        except Exception:
            logger.debug("PanoramaSearch failed, falling back to QuickSearch", exc_info=True)

        # Fall back to QuickSearch
        try:
            results = self.graph_tools.quick_search(query, graph_id, top_k=8)
            facts = [r.get("summary", "") for r in results if r.get("summary")]
            rlog.log("search_quick", {"results": len(results)})
            return {
                "tool": "QuickSearch",
                "semantic_facts": facts,
                "entity_insights": results,
                "relationship_chains": [],
                "sub_queries": [],
            }
        except Exception:
            logger.exception("All graph search tools failed")
            return {
                "tool": "none",
                "semantic_facts": [],
                "entity_insights": [],
                "relationship_chains": [],
                "sub_queries": [],
            }

    def _observe_step(
        self, sim_dir: str, section_title: str, sim_context: Dict
    ) -> Dict[str, Any]:
        """Gather simulation feed data: posts, trades, actions."""
        observations: Dict[str, Any] = {
            "run_state": sim_context,
        }

        # Gather posts from each platform
        for platform in PLATFORMS:
            try:
                posts = get_posts_from_db(sim_dir, platform, limit=20)
                if posts:
                    observations[f"{platform}_posts"] = posts
            except Exception:
                pass

        # Gather trades
        try:
            trades = get_trades_from_db(sim_dir, limit=30)
            if trades:
                observations["trades"] = trades
        except Exception:
            pass

        # Recent agent actions
        try:
            recent = get_recent_actions(sim_dir, limit=30)
            if recent:
                observations["recent_actions"] = recent
        except Exception:
            pass

        return observations

    def _write_step(
        self,
        section: ReportSection,
        search_results: Dict,
        observations: Dict,
        sim_requirement: str,
        round_num: int,
    ) -> str:
        """LLM composes section text with citations."""
        # Format graph context
        facts_text = ""
        facts = search_results.get("semantic_facts", [])
        if facts:
            facts_text = "Knowledge Graph Facts:\n" + "\n".join(f"- {f}" for f in facts[:15])

        chains_text = ""
        chains = search_results.get("relationship_chains", [])
        if chains:
            chains_text = "Relationship Chains:\n" + "\n".join(f"- {c}" for c in chains[:15])

        entities_text = ""
        entities = search_results.get("entity_insights", [])
        if entities:
            ent_lines = []
            for e in entities[:10]:
                name = e.get("name", "?")
                etype = e.get("type", "Entity")
                summary = e.get("summary", "")
                ent_lines.append(f"- [{etype}] {name}: {summary}")
            entities_text = "Entities:\n" + "\n".join(ent_lines)

        # Format simulation observations
        sim_text_parts = []
        run_state = observations.get("run_state", {})
        if run_state:
            sim_text_parts.append(
                f"Simulation: {run_state.get('rounds_completed', '?')} rounds completed, "
                f"{run_state.get('agent_action_count', 0)} total actions"
            )

        for platform in PLATFORMS:
            posts = observations.get(f"{platform}_posts", [])
            if posts:
                sample = posts[:5]
                lines = []
                for p in sample:
                    author = p.get("user_name") or p.get("name") or p.get("user_id", "?")
                    content = p.get("content", p.get("question", ""))[:200]
                    lines.append(f'  "{content}" -- {author}')
                sim_text_parts.append(f"{platform.title()} posts:\n" + "\n".join(lines))

        trades = observations.get("trades", [])
        if trades:
            trade_lines = []
            for t in trades[:5]:
                user = t.get("user_name", t.get("user_id", "?"))
                side = t.get("side", "?")
                amount = t.get("amount", "?")
                trade_lines.append(f"  {user}: {side} for {amount}")
            sim_text_parts.append("Trades:\n" + "\n".join(trade_lines))

        sim_text = "\n\n".join(sim_text_parts) if sim_text_parts else "No simulation data available."

        # Compose the section
        prior_content = ""
        if round_num > 0 and section.content:
            prior_content = (
                f"\n\nPrevious draft (improve based on reflection):\n{section.content[:3000]}"
                f"\n\nReflection notes: {section.reflection_notes}"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert analyst writing a section of a research report. "
                    "Write in clear, professional markdown. Use bullet points, bold text, "
                    "and sub-headers (###) where appropriate. "
                    "Cite specific entities from the knowledge graph in **bold**. "
                    "Quote specific simulation posts or trades when relevant. "
                    "Be analytical and insightful, not just descriptive."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Report topic: {sim_requirement}\n\n"
                    f"Section: {section.title}\n"
                    f"Section purpose: {section.description}\n\n"
                    f"--- KNOWLEDGE GRAPH DATA ---\n{facts_text}\n\n{chains_text}\n\n{entities_text}\n\n"
                    f"--- SIMULATION DATA ---\n{sim_text}"
                    f"{prior_content}\n\n"
                    f"Write this section now. Use ## for the section heading."
                ),
            },
        ]

        try:
            return self.llm.complete(
                messages, smart=True, temperature=0.5, max_tokens=4096
            )
        except Exception:
            logger.exception("Failed to write section: %s", section.title)
            return f"## {section.title}\n\n*Content generation failed.*\n"

    def _reflect_step(self, section: ReportSection, sim_requirement: str) -> str:
        """LLM self-critiques the section for completeness."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a critical reviewer. Evaluate the following report section "
                    "for completeness, accuracy, and analytical depth. "
                    "If the section is satisfactory, respond with exactly: SATISFIED. "
                    "Otherwise, briefly describe what gaps remain or what should be improved. "
                    "Keep your response under 100 words."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Report topic: {sim_requirement}\n"
                    f"Section: {section.title}\n\n"
                    f"Content:\n{section.content[:4000]}"
                ),
            },
        ]

        try:
            return self.llm.complete(
                messages, smart=True, temperature=0.3, max_tokens=256
            ).strip()
        except Exception:
            return "SATISFIED"

    def _reflection_is_satisfied(self, reflection: str) -> bool:
        """Check if the reflection indicates satisfaction."""
        reflection_lower = reflection.lower().strip()
        return "satisfied" in reflection_lower and len(reflection_lower) < 50

    # ------------------------------------------------------------------
    # Private: Gather simulation context
    # ------------------------------------------------------------------

    def _gather_simulation_context(self, sim_dir: str) -> Dict[str, Any]:
        """Pull aggregate simulation state from the sim directory."""
        try:
            state = get_run_state_from_actions(sim_dir)
            state["action_count"] = state.get("agent_action_count", 0)
            return state
        except Exception:
            logger.debug("Failed to gather simulation context", exc_info=True)
            return {
                "rounds_completed": 0,
                "total_rounds": 0,
                "action_counts": {},
                "agent_action_count": 0,
                "action_count": 0,
                "recent_actions": [],
                "status": "unknown",
            }

    # ------------------------------------------------------------------
    # Private: Assemble final report
    # ------------------------------------------------------------------

    def _assemble_report(
        self,
        sections: List[ReportSection],
        sim_requirement: str,
        sim_context: Dict,
    ) -> str:
        """Combine all sections into a single markdown document."""
        parts = []

        # Title
        parts.append(f"# Simulation Analysis Report\n")
        parts.append(f"**Research Question:** {sim_requirement}\n")
        parts.append(
            f"**Simulation Stats:** {sim_context.get('rounds_completed', '?')} rounds, "
            f"{sim_context.get('agent_action_count', 0)} agent actions\n"
        )
        parts.append("---\n")

        # Table of contents
        parts.append("## Table of Contents\n")
        for i, section in enumerate(sections, 1):
            anchor = section.title.lower().replace(" ", "-").replace(":", "")
            parts.append(f"{i}. [{section.title}](#{anchor})")
        parts.append("\n---\n")

        # Sections
        for section in sections:
            parts.append(section.content)
            parts.append("")  # blank line between sections

        # Footer
        parts.append("---\n")
        parts.append(
            "*Report generated by WhaleSwarm Report Agent using ReACT methodology "
            "with knowledge graph retrieval and simulation data analysis.*\n"
        )

        return "\n".join(parts)
