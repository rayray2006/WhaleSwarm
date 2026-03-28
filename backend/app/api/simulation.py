"""Simulation API endpoints."""
import logging
import threading
from dataclasses import asdict

from flask import Blueprint, current_app, jsonify, request

from app.models.project import ProjectManager
from app.models.task import TaskManager
from app.services.simulation_manager import SimulationManager, SimulationState

simulation_bp = Blueprint("simulation", __name__)
logger = logging.getLogger(__name__)


def _get_config():
    return current_app.config["APP_CONFIG"]


def _get_storage():
    return current_app.extensions["neo4j_storage"]


def _resolve_sim_id(candidate_id: str) -> str:
    """Resolve a simulation_id or project_id to an actual simulation_id."""
    import os, json
    config = _get_config()
    sm = SimulationManager(config)
    if sm.load(candidate_id):
        return candidate_id
    # Search by project_id
    sims_dir = os.path.join(config.upload_dir, "simulations")
    if os.path.exists(sims_dir):
        for sid in sorted(os.listdir(sims_dir), reverse=True):  # newest first
            sim_file = os.path.join(sims_dir, sid, "simulation.json")
            if os.path.exists(sim_file):
                with open(sim_file) as f:
                    sdata = json.load(f)
                if sdata.get("project_id") == candidate_id:
                    return sid
    return candidate_id  # return as-is, let caller handle 404


@simulation_bp.route("/entities/<graph_id>", methods=["GET"])
def get_entities(graph_id):
    storage = _get_storage()
    from app.services.entity_reader import EntityReader
    reader = EntityReader(storage)
    entities = reader.get_entities(graph_id)
    return jsonify({"entities": entities})


@simulation_bp.route("/create", methods=["POST"])
def create_simulation():
    config = _get_config()
    data = request.get_json()
    project_id = data.get("project_id")
    if not project_id:
        return jsonify({"error": "project_id required"}), 400

    pm = ProjectManager(config.upload_dir)
    project = pm.load(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    sm = SimulationManager(config)
    state = SimulationState(
        project_id=project_id,
        graph_id=project.graph_id or "",
        name=project.name,
        simulation_requirement=project.simulation_requirement,
    )
    sm.create(state)

    return jsonify({
        "simulation_id": state.simulation_id,
        "status": state.status,
    })


@simulation_bp.route("/prepare", methods=["POST"])
def prepare_simulation():
    config = _get_config()
    data = request.get_json()
    simulation_id = data.get("simulation_id")
    if not simulation_id:
        return jsonify({"error": "simulation_id required"}), 400

    sm = SimulationManager(config)
    state = sm.load(simulation_id)
    if not state:
        return jsonify({"error": "Simulation not found"}), 404

    task = TaskManager.create("profile_generation", {"simulation_id": simulation_id})

    # Capture app for background thread context
    app = current_app._get_current_object()
    storage = _get_storage()

    def _generate():
        from app.services.oasis_profile_generator import OasisProfileGenerator
        from app.utils.llm_client import LLMClient

        llm = LLMClient(config)
        gen = OasisProfileGenerator(config, storage, llm)

        try:
            state.status = "preparing"
            sm.save(state)

            profiles = gen.generate_profiles(state.graph_id, task.task_id)

            # Save in all platform formats
            sm.save_profiles(simulation_id, [p.to_twitter_format() for p in profiles], "twitter")
            sm.save_profiles(simulation_id, [p.to_reddit_format() for p in profiles], "reddit")
            sm.save_profiles(simulation_id, [p.to_polymarket_format() for p in profiles], "polymarket")
            sm.save_profiles(simulation_id, [asdict(p) for p in profiles], "all")

            state.profile_count = len(profiles)
            sm.save(state)

            # Generate simulation config (also during prepare, not at start time)
            TaskManager.update(task.task_id, progress=95,
                               metadata={"stage": "config_generation"})

            from app.services.simulation_config_generator import SimulationConfigGenerator
            config_gen = SimulationConfigGenerator(llm)
            sim_config = config_gen.generate(
                profiles=[asdict(p) for p in profiles],
                simulation_requirement=state.simulation_requirement,
                max_rounds=config.default_max_rounds,
            )
            sm.save_config(simulation_id, sim_config)
            state.config_generated = True

            state.status = "prepared"
            sm.save(state)

            TaskManager.update(task.task_id, status="completed", progress=100,
                               result={"profile_count": len(profiles)})
        except Exception as e:
            logger.error(f"Preparation failed: {e}", exc_info=True)
            TaskManager.update(task.task_id, status="failed", error=str(e))
            state.status = "failed"
            sm.save(state)

    thread = threading.Thread(target=_generate, daemon=True)
    thread.start()

    return jsonify({"task_id": task.task_id, "status": "preparing"})


@simulation_bp.route("/prepare/status", methods=["POST"])
def prepare_status():
    data = request.get_json()
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"error": "task_id required"}), 400

    task = TaskManager.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(TaskManager.to_dict(task))


@simulation_bp.route("/start", methods=["POST"])
def start_simulation():
    config = _get_config()
    data = request.get_json()
    simulation_id = data.get("simulation_id")
    logger.info(f"POST /start received simulation_id={simulation_id}")
    if not simulation_id:
        return jsonify({"error": "simulation_id required"}), 400

    simulation_id = _resolve_sim_id(simulation_id)
    sm = SimulationManager(config)
    state = sm.load(simulation_id)
    if not state:
        logger.error(f"Simulation not found: {simulation_id}")
        return jsonify({"error": f"Simulation not found: {simulation_id}"}), 404

    # Config should already be generated during prepare step
    if not state.config_generated:
        return jsonify({"error": "Simulation not prepared yet. Config not generated."}), 400

    # Start simulation subprocess
    from app.services.simulation_runner import SimulationRunner
    try:
        SimulationRunner.start_simulation(
            simulation_id=simulation_id,
            sim_dir=sm.get_sim_dir(simulation_id),
            config=config,
        )
        state.status = "running"
        sm.save(state)
        return jsonify({"status": "running", "simulation_id": simulation_id})
    except Exception as e:
        logger.error(f"Failed to start simulation: {e}")
        return jsonify({"error": str(e)}), 500


@simulation_bp.route("/stop", methods=["POST"])
def stop_simulation():
    config = _get_config()
    data = request.get_json()
    simulation_id = data.get("simulation_id")
    if not simulation_id:
        return jsonify({"error": "simulation_id required"}), 400

    from app.services.simulation_runner import SimulationRunner
    SimulationRunner.stop_simulation(simulation_id)

    sm = SimulationManager(config)
    state = sm.load(simulation_id)
    if state:
        state.status = "stopped"
        sm.save(state)

    return jsonify({"status": "stopped"})


@simulation_bp.route("/<simulation_id>/run-status", methods=["GET"])
def get_run_status(simulation_id):
    simulation_id = _resolve_sim_id(simulation_id)
    config = _get_config()
    sm = SimulationManager(config)
    sim_dir = sm.get_sim_dir(simulation_id)
    from app.services.simulation_runner import SimulationRunner
    state = SimulationRunner.get_run_state(simulation_id, sim_dir)
    if not state:
        return jsonify({"error": "No run state found"}), 404
    return jsonify(state)


@simulation_bp.route("/<simulation_id>/profiles", methods=["GET"])
def get_profiles(simulation_id):
    simulation_id = _resolve_sim_id(simulation_id)
    config = _get_config()
    sm = SimulationManager(config)
    platform = request.args.get("platform", "all")
    profiles = sm.load_profiles(simulation_id, platform)
    return jsonify({"profiles": profiles})


@simulation_bp.route("/<simulation_id>/config", methods=["GET"])
def get_config(simulation_id):
    simulation_id = _resolve_sim_id(simulation_id)
    config = _get_config()
    sm = SimulationManager(config)
    sim_config = sm.load_config(simulation_id)
    if not sim_config:
        return jsonify({"error": "Config not found"}), 404
    return jsonify(sim_config)


@simulation_bp.route("/<simulation_id>/posts", methods=["GET"])
def get_posts(simulation_id):
    simulation_id = _resolve_sim_id(simulation_id)
    config = _get_config()
    platform = request.args.get("platform", "twitter")
    round_num = request.args.get("round")

    from app.services.simulation_ipc import get_posts_from_db
    sm = SimulationManager(config)
    sim_dir = sm.get_sim_dir(simulation_id)

    posts = get_posts_from_db(sim_dir, platform, round_num)
    return jsonify({"posts": posts})
