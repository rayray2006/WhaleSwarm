"""Report API endpoints.

- POST /generate        Start async report generation, return task_id
- GET  /<id>/status     Poll task progress
- GET  /<id>            Return completed report markdown
- POST /<id>/conversation  Chat with report agent over a completed report
"""

import json
import logging
import os
import threading
import uuid

from flask import Blueprint, current_app, jsonify, request

from app.models.task import TaskManager
from app.services.simulation_manager import SimulationManager

report_bp = Blueprint("report", __name__)
logger = logging.getLogger(__name__)

# In-memory store mapping report_id -> metadata (conversation history, etc.)
_report_meta: dict = {}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_config():
    return current_app.config["APP_CONFIG"]


def _get_storage():
    return current_app.extensions["neo4j_storage"]


def _build_report_agent():
    """Construct a ReportAgent with current app dependencies."""
    from app.services.report_agent import ReportAgent
    from app.utils.embedding_service import EmbeddingService
    from app.utils.llm_client import LLMClient

    config = _get_config()
    storage = _get_storage()
    llm = LLMClient(config)
    embedder = EmbeddingService(config)
    return ReportAgent(storage, llm, embedder, config)


# ------------------------------------------------------------------
# POST /generate
# ------------------------------------------------------------------

@report_bp.route("/generate", methods=["POST"])
def generate_report():
    """Start asynchronous report generation.

    Request JSON:
        simulation_id: str (required)

    Returns:
        task_id: str  -- use to poll status
        report_id: str
    """
    data = request.get_json(silent=True) or {}
    simulation_id = data.get("simulation_id")
    if not simulation_id:
        return jsonify({"error": "simulation_id is required"}), 400

    config = _get_config()

    # Load simulation state to get graph_id and sim_requirement
    sim_mgr = SimulationManager(config)
    sim_state = sim_mgr.load(simulation_id)
    if sim_state is None:
        return jsonify({"error": f"Simulation {simulation_id} not found"}), 404

    graph_id = sim_state.graph_id
    sim_requirement = sim_state.simulation_requirement or "General analysis"
    sim_dir = os.path.join(config.upload_dir, "simulations", simulation_id)

    # Create a report_id and task
    report_id = simulation_id  # one report per simulation, keyed by sim id
    task = TaskManager.create(
        task_type="report_generation",
        metadata={
            "simulation_id": simulation_id,
            "report_id": report_id,
            "graph_id": graph_id,
        },
    )

    # Store report metadata
    _report_meta[report_id] = {
        "simulation_id": simulation_id,
        "graph_id": graph_id,
        "sim_requirement": sim_requirement,
        "sim_dir": sim_dir,
        "task_id": task.task_id,
        "conversations": {},  # conversation_id -> history
    }

    # Run generation in background thread
    # We need to capture the app for context since we run off-request.
    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            try:
                TaskManager.update(task.task_id, status="processing", progress=5)

                from app.services.report_agent import ReportAgent
                from app.utils.embedding_service import EmbeddingService
                from app.utils.llm_client import LLMClient

                cfg = app.config["APP_CONFIG"]
                storage = app.extensions["neo4j_storage"]
                llm = LLMClient(cfg)
                embedder = EmbeddingService(cfg)
                agent = ReportAgent(storage, llm, embedder, cfg)

                def on_progress(pct, msg):
                    TaskManager.update(task.task_id, progress=pct)

                markdown = agent.generate_report(
                    simulation_id=simulation_id,
                    graph_id=graph_id,
                    sim_requirement=sim_requirement,
                    sim_dir=sim_dir,
                    config=cfg,
                    progress_cb=on_progress,
                )

                TaskManager.update(
                    task.task_id,
                    status="completed",
                    progress=100,
                    result={"report_id": report_id, "length": len(markdown)},
                )
                logger.info("Report generation completed: %s", report_id)

            except Exception as exc:
                logger.exception("Report generation failed: %s", simulation_id)
                TaskManager.update(
                    task.task_id,
                    status="failed",
                    error=str(exc),
                )

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({
        "task_id": task.task_id,
        "report_id": report_id,
        "status": "processing",
    })


# ------------------------------------------------------------------
# GET /<id>/status
# ------------------------------------------------------------------

@report_bp.route("/<report_id>/status", methods=["GET"])
def get_report_status(report_id):
    """Poll report generation progress.

    Returns:
        status: str  (pending | processing | completed | failed)
        progress: int  (0-100)
        error: str | null
    """
    # Find the task for this report
    meta = _report_meta.get(report_id)
    if meta and meta.get("task_id"):
        task = TaskManager.get(meta["task_id"])
        if task:
            return jsonify({
                "report_id": report_id,
                "status": task.status,
                "progress": task.progress,
                "error": task.error,
            })

    # Check if the report file already exists (from a previous run)
    config = _get_config()
    report_path = os.path.join(
        config.upload_dir, "reports", report_id, "report.md"
    )
    if os.path.exists(report_path):
        return jsonify({
            "report_id": report_id,
            "status": "completed",
            "progress": 100,
            "error": None,
        })

    return jsonify({
        "report_id": report_id,
        "status": "not_found",
        "progress": 0,
        "error": None,
    }), 404


# ------------------------------------------------------------------
# GET /<id>
# ------------------------------------------------------------------

@report_bp.route("/<report_id>", methods=["GET"])
def get_report(report_id):
    """Return the completed report markdown.

    Returns:
        report_id: str
        markdown: str
        simulation_id: str
    """
    config = _get_config()
    report_path = os.path.join(
        config.upload_dir, "reports", report_id, "report.md"
    )

    if not os.path.exists(report_path):
        return jsonify({"error": "Report not found or not yet generated"}), 404

    with open(report_path) as f:
        markdown = f.read()

    meta = _report_meta.get(report_id, {})

    return jsonify({
        "report_id": report_id,
        "simulation_id": meta.get("simulation_id", report_id),
        "markdown": markdown,
    })


# ------------------------------------------------------------------
# POST /<id>/conversation
# ------------------------------------------------------------------

@report_bp.route("/<report_id>/conversation", methods=["POST"])
def conversation(report_id):
    """Chat with the report agent about a completed report.

    Request JSON:
        question: str (required)
        conversation_id: str (optional, for multi-turn)

    Returns:
        response: str
        conversation_id: str
    """
    data = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    conversation_id = data.get("conversation_id") or str(uuid.uuid4())

    config = _get_config()

    # Check report exists
    report_path = os.path.join(
        config.upload_dir, "reports", report_id, "report.md"
    )
    if not os.path.exists(report_path):
        return jsonify({"error": "Report not found"}), 404

    # Get or create conversation history
    meta = _report_meta.get(report_id)
    if not meta:
        # Reconstruct minimal metadata
        meta = {
            "simulation_id": report_id,
            "graph_id": None,
            "sim_dir": None,
            "conversations": {},
        }
        # Try to recover graph_id from simulation state
        sim_mgr = SimulationManager(config)
        sim_state = sim_mgr.load(report_id)
        if sim_state:
            meta["graph_id"] = sim_state.graph_id
            meta["sim_dir"] = os.path.join(
                config.upload_dir, "simulations", report_id
            )
        _report_meta[report_id] = meta

    conversations = meta.setdefault("conversations", {})
    history = conversations.get(conversation_id, [])

    # Build agent and get response
    try:
        from app.services.report_agent import ReportAgent
        from app.utils.embedding_service import EmbeddingService
        from app.utils.llm_client import LLMClient

        storage = _get_storage()
        llm = LLMClient(config)
        embedder = EmbeddingService(config)
        agent = ReportAgent(storage, llm, embedder, config)

        response_text = agent.conversation(
            report_id=report_id,
            question=question,
            history=history,
            config=config,
            graph_id=meta.get("graph_id"),
            sim_dir=meta.get("sim_dir"),
        )

        # Update conversation history
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": response_text})
        conversations[conversation_id] = history

        return jsonify({
            "response": response_text,
            "conversation_id": conversation_id,
            "report_id": report_id,
        })

    except Exception as exc:
        logger.exception("Conversation failed for report %s", report_id)
        return jsonify({"error": str(exc)}), 500
