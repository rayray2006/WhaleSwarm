"""Simulation API endpoints."""
import logging
import os
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

            stakeholders = gen.generate_profiles(state.graph_id, task.task_id)
            logger.info("Generated %d stakeholder profiles from graph", len(stakeholders))

            TaskManager.update(task.task_id, progress=50,
                               metadata={"stage": "background_population"})
            stakeholder_names = [p.name for p in stakeholders]
            crowd = gen.generate_background_population(
                count=100,
                simulation_requirement=state.simulation_requirement,
                stakeholder_names=stakeholder_names,
                task_id=task.task_id,
            )
            logger.info("Generated %d crowd profiles", len(crowd))

            # Clean platform separation:
            #   Twitter    = all stakeholders (individuals + institutions post takes)
            #   Reddit     = crowd + individual stakeholders (no institutional accounts)
            #   Polymarket = crowd + individual stakeholders (institutions don't trade)
            from app.services.oasis_profile_generator import GROUP_ENTITY_TYPES
            individual_stakeholders = [
                p for p in stakeholders
                if p.profession.lower() not in GROUP_ENTITY_TYPES
                and not any(kw in p.profession.lower() for kw in (
                    "outlet", "company", "agency", "organization", "organisation",
                    "studio", "publisher", "league", "ngo", "think tank", "thinktank",
                ))
            ]
            sm.save_profiles(simulation_id,
                [p.to_twitter_format() for p in stakeholders], "twitter")
            sm.save_profiles(simulation_id,
                [p.to_reddit_format() for p in individual_stakeholders + crowd], "reddit")
            sm.save_profiles(simulation_id,
                [p.to_polymarket_format() for p in individual_stakeholders + crowd], "polymarket")
            sm.save_profiles(simulation_id,
                [asdict(p) for p in stakeholders + crowd], "all")

            state.profile_count = len(stakeholders) + len(crowd)
            sm.save(state)

            # Generate simulation config (also during prepare, not at start time)
            TaskManager.update(task.task_id, progress=95,
                               metadata={"stage": "config_generation"})

            from app.services.simulation_config_generator import SimulationConfigGenerator
            config_gen = SimulationConfigGenerator(llm)

            # Load polymarket overrides from project if available
            polymarket_config = None
            from app.models.project import ProjectManager
            pm = ProjectManager(config.upload_dir)
            project = pm.load(state.project_id)
            if project and project.polymarket_config:
                polymarket_config = project.polymarket_config
                logger.info(
                    "[CLOB-DEBUG] polymarket_config loaded from project: yes_price=%s, "
                    "market_question='%s'",
                    polymarket_config.get("yes_price"),
                    str(polymarket_config.get("market_question", ""))[:80],
                )
            else:
                logger.info(
                    "[CLOB-DEBUG] NO polymarket_config on project — initial price will "
                    "be LLM-generated or default 0.5"
                )

            sim_config = config_gen.generate(
                profiles=[asdict(p) for p in stakeholders + crowd],
                simulation_requirement=state.simulation_requirement,
                max_rounds=config.default_max_rounds,
                polymarket_config=polymarket_config,
            )
            sm.save_config(simulation_id, sim_config)
            state.config_generated = True

            state.status = "prepared"
            sm.save(state)

            TaskManager.update(task.task_id, status="completed", progress=100,
                               result={"profile_count": len(stakeholders) + len(crowd)})
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

    # If the caller supplied num_rounds, patch the saved config before launching.
    num_rounds = data.get("num_rounds")
    if num_rounds:
        try:
            num_rounds = int(num_rounds)
            sim_config = sm.load_config(simulation_id) or {}
            sim_config["max_rounds"] = num_rounds
            sm.save_config(simulation_id, sim_config)
            logger.info("Patched max_rounds=%d for simulation %s", num_rounds, simulation_id)
        except (ValueError, TypeError):
            pass

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


def _get_sim_pid(simulation_id: str) -> int | None:
    """Get the PID of a running simulation subprocess."""
    import signal as sig
    from app.services.simulation_runner import SimulationRunner

    # Try in-memory first
    proc = SimulationRunner._processes.get(simulation_id)
    if proc is not None and proc.poll() is None:
        return proc.pid

    # Fallback: read sim.pid file
    config = _get_config()
    pid_path = os.path.join(config.upload_dir, "simulations", simulation_id, "sim.pid")
    if os.path.exists(pid_path):
        try:
            pid = int(open(pid_path).read().strip())
            os.kill(pid, 0)  # check if alive (signal 0 = no-op)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    return None


@simulation_bp.route("/pause", methods=["POST"])
def pause_simulation():
    data = request.get_json()
    simulation_id = data.get("simulation_id")
    if not simulation_id:
        return jsonify({"error": "simulation_id required"}), 400

    simulation_id = _resolve_sim_id(simulation_id)
    pid = _get_sim_pid(simulation_id)
    if pid is None:
        return jsonify({"error": "Simulation not running"}), 404

    import signal as sig
    os.kill(pid, sig.SIGUSR1)
    return jsonify({"status": "paused", "simulation_id": simulation_id})


@simulation_bp.route("/resume", methods=["POST"])
def resume_simulation():
    data = request.get_json()
    simulation_id = data.get("simulation_id")
    if not simulation_id:
        return jsonify({"error": "simulation_id required"}), 400

    simulation_id = _resolve_sim_id(simulation_id)
    pid = _get_sim_pid(simulation_id)
    if pid is None:
        return jsonify({"error": "Simulation not running"}), 404

    import signal as sig
    os.kill(pid, sig.SIGUSR2)
    return jsonify({"status": "running", "simulation_id": simulation_id})


@simulation_bp.route("/<simulation_id>/run-status", methods=["GET"])
def get_run_status(simulation_id):
    simulation_id = _resolve_sim_id(simulation_id)
    config = _get_config()
    sm = SimulationManager(config)
    sim_dir = sm.get_sim_dir(simulation_id)
    from app.services.simulation_runner import SimulationRunner
    from app.services.simulation_ipc import get_posts_from_db
    state = SimulationRunner.get_run_state(simulation_id, sim_dir)
    if not state:
        return jsonify({"error": "No run state found"}), 404

    # Include live posts + comments from SQLite.
    # Posts are returned newest-first; we reverse for display.
    def _format_comment(c):
        return {
            "author": c.get("user_name") or c.get("name") or f"user_{c['user_id']}",
            "content": c.get("content", ""),
        }

    try:
        twitter_posts = get_posts_from_db(sim_dir, "twitter", limit=50)
        state["tweets"] = [
            {
                "post_id": p["post_id"],
                "author": p.get("user_name") or p.get("name") or f"user_{p['user_id']}",
                "content": p.get("content", ""),
                "text": p.get("content", ""),
                "likes": p.get("num_likes", 0),
                "like_count": p.get("num_likes", 0),
                "dislikes": p.get("num_dislikes", 0),
                "comments": [_format_comment(c) for c in p.get("comments", [])],
            }
            for p in twitter_posts
        ]
    except Exception:
        pass

    try:
        reddit_posts = get_posts_from_db(sim_dir, "reddit", limit=50)
        state["reddit_posts"] = [
            {
                "post_id": p["post_id"],
                "author": p.get("user_name") or p.get("name") or f"user_{p['user_id']}",
                "content": p.get("content", ""),
                "title": p.get("content", ""),
                "text": p.get("content", ""),
                "score": (p.get("num_likes", 0) or 0) - (p.get("num_dislikes", 0) or 0),
                "upvotes": p.get("num_likes", 0),
                "comments": [_format_comment(c) for c in p.get("comments", [])],
            }
            for p in reddit_posts
        ]
    except Exception:
        pass

    # Include live Polymarket data (prices, portfolios).
    try:
        pm_db_path = os.path.join(sim_dir, "polymarket.db")
        if os.path.exists(pm_db_path):
            import sqlite3 as _sql
            pm_conn = _sql.connect(pm_db_path)
            pm_conn.row_factory = _sql.Row
            pm_conn.execute("PRAGMA read_uncommitted = ON")

            # Current market price from AMM reserves.
            markets = pm_conn.execute(
                "SELECT market_id, question, outcome_a, outcome_b, "
                "reserve_a, reserve_b FROM market WHERE resolved = 0"
            ).fetchall()

            if markets:
                m = markets[0]
                total = (m["reserve_a"] or 0) + (m["reserve_b"] or 0)
                yes_price = m["reserve_b"] / total if total > 0 else 0.5

                # Portfolio leaderboard (top traders by P&L).
                traders = pm_conn.execute(
                    "SELECT p.user_id, p.balance, u.user_name, u.name "
                    "FROM portfolio p "
                    "LEFT JOIN user u ON p.user_id = u.user_id "
                    "ORDER BY p.balance DESC LIMIT 10"
                ).fetchall()

                leaderboard = []
                for t in traders:
                    # Calculate position value.
                    positions = pm_conn.execute(
                        "SELECT shares, outcome FROM position WHERE user_id = ?",
                        (t["user_id"],),
                    ).fetchall()
                    pos_value = 0.0
                    for pos in positions:
                        if pos["outcome"] == m["outcome_a"]:
                            # outcome_a is YES; value = shares * yes_price
                            pos_value += pos["shares"] * yes_price
                        else:
                            # outcome_b is NO; value = shares * (1 - yes_price)
                            pos_value += pos["shares"] * (1 - yes_price)
                    total_value = t["balance"] + pos_value
                    pnl = total_value - 1000.0  # initial balance
                    leaderboard.append({
                        "agent_id": t["user_id"],
                        "name": t["user_name"] or t["name"] or f"trader_{t['user_id']}",
                        "agent_name": t["user_name"] or t["name"] or f"trader_{t['user_id']}",
                        "pnl": round(pnl, 2),
                        "balance": round(t["balance"], 2),
                        "total_value": round(total_value, 2),
                    })
                leaderboard.sort(key=lambda x: x["pnl"], reverse=True)

                # Build price history from trade log.
                # Each trade records the post-trade price; we reconstruct
                # the per-round price by taking the last trade price per round.
                price_history = []
                init_prob = 0.5
                try:
                    # Get initial price from sim config
                    sim_state = sm.load(simulation_id)
                    sim_cfg = sm.load_config(simulation_id)
                    if sim_cfg:
                        init_prob = float(
                            sim_cfg.get("events", {}).get("market_initial_probability", 0.5)
                        )
                    price_history.append({"round": 0, "price": round(init_prob, 4)})

                    # Get per-trade price from the trace table
                    import json as _json
                    traces = pm_conn.execute(
                        "SELECT info FROM trace WHERE action IN ('buy_shares', 'sell_shares') "
                        "ORDER BY rowid"
                    ).fetchall()
                    round_idx = 1
                    for tr in traces:
                        try:
                            info = _json.loads(tr["info"])
                            # new_price_a is YES price (reserve_b / total)
                            p = info.get("new_price_a")
                            if p is not None:
                                price_history.append({
                                    "round": round_idx,
                                    "price": round(float(p), 4),
                                })
                                round_idx += 1
                        except (ValueError, TypeError, KeyError):
                            continue
                except Exception:
                    pass

                # Always include current price as the last point
                if not price_history or price_history[-1]["price"] != round(yes_price, 4):
                    price_history.append({
                        "round": state.get("rounds_completed", len(price_history)),
                        "price": round(yes_price, 4),
                    })

                # Build real price history from divergence records in actions.jsonl
                real_price_history = []
                try:
                    from app.services.simulation_ipc import get_divergence_from_actions
                    divergences = get_divergence_from_actions(sim_dir)
                    seen_rounds = set()
                    for d in divergences:
                        r = d.get("round")
                        rp = d.get("real_price")
                        if r is not None and rp is not None and r not in seen_rounds:
                            real_price_history.append({"round": r, "price": round(float(rp), 4)})
                            seen_rounds.add(r)
                except Exception:
                    pass

                state["polymarket"] = {
                    "yes_price": round(yes_price, 4),
                    "no_price": round(1 - yes_price, 4),
                    "market_question": m["question"],
                    "leaderboard": leaderboard[:8],
                    "price_history": price_history,
                    "real_price_history": real_price_history,
                    "initial_price": round(init_prob, 4),
                }

            pm_conn.close()
    except Exception:
        pass

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
