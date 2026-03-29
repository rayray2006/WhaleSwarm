"""Graph API endpoints."""
import logging
import os
import threading
import uuid

from flask import Blueprint, current_app, jsonify, request

from app.models.project import Project, ProjectManager
from app.models.task import TaskManager
from app.services.ontology_generator import OntologyGenerator
from app.services.text_processor import extract_text_from_file
from app.utils.llm_client import LLMClient

graph_bp = Blueprint("graph", __name__)
logger = logging.getLogger(__name__)


def _get_config():
    return current_app.config["APP_CONFIG"]


def _get_storage():
    return current_app.extensions["neo4j_storage"]


@graph_bp.route("/ontology/generate", methods=["POST"])
def generate_ontology():
    config = _get_config()
    pm = ProjectManager(config.upload_dir)

    # Parse input
    files = request.files.getlist("files")
    simulation_requirement = request.form.get("simulation_requirement", "")
    project_name = request.form.get("project_name", "Untitled")
    additional_context = request.form.get("additional_context", "")

    if not files or not simulation_requirement:
        return jsonify({"error": "files and simulation_requirement are required"}), 400

    # Create project
    project = Project(
        name=project_name,
        simulation_requirement=simulation_requirement,
        additional_context=additional_context,
    )
    pm.create(project)

    # Save uploaded files and extract text
    all_text = []
    files_dir = pm.get_files_dir(project.project_id)
    for f in files:
        file_path = os.path.join(files_dir, f.filename)
        f.save(file_path)
        project.files.append(f.filename)
        text = extract_text_from_file(file_path)
        all_text.append(text)

    # Concatenate and save extracted text
    full_text = "\n\n".join(all_text)
    text_path = pm.get_extracted_text_path(project.project_id)
    with open(text_path, "w") as tf:
        tf.write(full_text)

    # Generate ontology
    llm = LLMClient(config)
    generator = OntologyGenerator(llm)
    try:
        ontology = generator.generate(
            full_text, simulation_requirement, additional_context
        )
    except Exception as e:
        logger.error(f"Ontology generation failed: {e}")
        return jsonify({"error": str(e)}), 500

    project.ontology = ontology
    project.status = "ontology_generated"
    pm.save(project)

    return jsonify({
        "project_id": project.project_id,
        "ontology": ontology,
        "status": project.status,
    })


@graph_bp.route("/build", methods=["POST"])
def build_graph():
    config = _get_config()
    storage = _get_storage()
    pm = ProjectManager(config.upload_dir)

    data = request.get_json()
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id is required"}), 400

    project = pm.load(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    if not project.ontology:
        return jsonify({"error": "Ontology not generated yet"}), 400

    # Read extracted text
    text_path = pm.get_extracted_text_path(project_id)
    if not os.path.exists(text_path):
        return jsonify({"error": "Extracted text not found"}), 404

    with open(text_path) as f:
        text = f.read()

    # Create graph and task
    graph_id = str(uuid.uuid4())
    project.graph_id = graph_id
    project.status = "graph_building"
    pm.save(project)

    task = TaskManager.create("graph_build", {"project_id": project_id, "graph_id": graph_id})

    # Build in background thread
    chunk_size = data.get("chunk_size", 500)
    chunk_overlap = data.get("chunk_overlap", 50)
    batch_size = data.get("batch_size", 5)

    def _build():
        from app.services.graph_builder import GraphBuilder
        from app.utils.embedding_service import EmbeddingService

        llm = LLMClient(config)
        emb = EmbeddingService(config)
        builder = GraphBuilder(config, storage, llm, emb)
        try:
            # Pass market_question for relevance filtering if available.
            mq = None
            if project.polymarket_config:
                mq = project.polymarket_config.get("market_question")

            builder.build(
                text=text,
                graph_id=graph_id,
                graph_name=data.get("graph_name", project.name),
                ontology=project.ontology,
                task_id=task.task_id,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                batch_size=batch_size,
                market_question=mq,
            )
            project.status = "graph_built"
            pm.save(project)
        except Exception as e:
            logger.error(f"Graph build failed: {e}")
            TaskManager.update(task.task_id, status="failed", error=str(e))
            project.status = "graph_build_failed"
            pm.save(project)

    thread = threading.Thread(target=_build, daemon=True)
    thread.start()

    return jsonify({
        "task_id": task.task_id,
        "graph_id": graph_id,
        "status": "building",
    })


@graph_bp.route("/project/<project_id>", methods=["GET"])
def get_project(project_id):
    config = _get_config()
    pm = ProjectManager(config.upload_dir)
    project = pm.load(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    from dataclasses import asdict
    return jsonify(asdict(project))


@graph_bp.route("/task/<task_id>", methods=["GET"])
def get_task(task_id):
    task = TaskManager.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(TaskManager.to_dict(task))


@graph_bp.route("/<graph_id>", methods=["GET"])
def get_graph(graph_id):
    storage = _get_storage()
    try:
        data = storage.get_graph_data(graph_id)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Failed to get graph data: {e}")
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# Polymarket-focused endpoints
# ------------------------------------------------------------------

@graph_bp.route("/polymarket-search", methods=["POST"])
def polymarket_search():
    """Proxy search to Polymarket Gamma API (avoids CORS)."""
    data = request.get_json(silent=True) or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    from app.services.polymarket_client import PolymarketClient
    client = PolymarketClient()
    try:
        markets = client.search_markets(query, limit=10)
        return jsonify({"markets": markets or []})
    except Exception as e:
        logger.exception("Polymarket search failed")
        return jsonify({"error": str(e)}), 500


@graph_bp.route("/polymarket-setup", methods=["POST"])
def polymarket_setup():
    """Set up a project from a Polymarket market.

    1. Fetch market data from Polymarket
    2. Generate research text via LLM
    3. Generate ontology from research text
    4. Create project with polymarket_config

    Request JSON:
        market: dict        — selected market object from polymarket-search
        fictional_event: str — the fictional event to inject
        event_round: int     — which round to inject the event (default 5)
        project_name: str    — optional project name
    """
    data = request.get_json(silent=True) or {}
    market = data.get("market")
    fictional_event = data.get("fictional_event", "").strip()
    event_round = int(data.get("event_round", 5))
    project_name = data.get("project_name", "").strip()

    if not market:
        return jsonify({"error": "market is required"}), 400
    if not fictional_event:
        return jsonify({"error": "fictional_event is required"}), 400

    market_question = market.get("question", market.get("title", ""))
    if not market_question:
        return jsonify({"error": "Market has no question"}), 400

    market_description = market.get("description", "")

    # Fetch current prices if available
    yes_price = None
    try:
        tokens = market.get("clobTokenIds") or market.get("clob_token_ids") or []
        if tokens and len(tokens) >= 1:
            from app.services.polymarket_client import PolymarketClient
            client = PolymarketClient()
            yes_price = client.get_price(tokens[0])
    except Exception:
        logger.debug("Could not fetch live price, using market data")

    if yes_price is None:
        # Try to get price from market object itself
        yes_price = market.get("outcomePrices", [None])[0] if market.get("outcomePrices") else 0.5
        try:
            yes_price = float(yes_price)
        except (TypeError, ValueError):
            yes_price = 0.5

    config = _get_config()
    llm = LLMClient(config)

    # Step 1: Generate research text
    logger.info("Researching topic: %s", market_question[:80])
    from app.services.topic_researcher import TopicResearcher
    researcher = TopicResearcher(llm)
    research_text = researcher.research(market_question, market_description)

    # Step 2: Create project
    pm = ProjectManager(config.upload_dir)
    project = Project(
        name=project_name or market_question[:60],
        simulation_requirement=f"Predict: {market_question}",
        additional_context=f"Current market price: YES={yes_price:.2f}, NO={1 - yes_price:.2f}",
        polymarket_config={
            "market_question": market_question,
            "market_description": market_description,
            "condition_id": market.get("conditionId") or market.get("condition_id"),
            "clob_token_ids": market.get("clobTokenIds") or market.get("clob_token_ids"),
            "yes_price": yes_price,
            "no_price": round(1 - yes_price, 4),
            "fictional_event": fictional_event,
            "event_round": event_round,
        },
    )
    pm.create(project)

    # Step 3: Save research text
    text_path = pm.get_extracted_text_path(project.project_id)
    with open(text_path, "w") as f:
        f.write(research_text)

    # Step 4: Generate ontology
    logger.info("Generating ontology from research text (%d chars)", len(research_text))
    generator = OntologyGenerator(llm)
    try:
        ontology = generator.generate(
            research_text,
            project.simulation_requirement,
            project.additional_context,
        )
    except Exception as e:
        logger.exception("Ontology generation failed")
        return jsonify({"error": f"Ontology generation failed: {e}"}), 500

    project.ontology = ontology
    project.status = "ontology_generated"
    pm.save(project)

    return jsonify({
        "project_id": project.project_id,
        "ontology": ontology,
        "market_data": {
            "question": market_question,
            "yes_price": yes_price,
            "no_price": round(1 - yes_price, 4),
        },
        "status": project.status,
    })
