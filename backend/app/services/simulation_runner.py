"""SimulationRunner -- subprocess-based simulation executor.

Provides a class-level singleton that manages simulation subprocesses.
The runner spawns ``python -m simulation_engine.run`` as a child process
and tracks its lifecycle.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from app.config import Config
from app.services.simulation_ipc import (
    get_recent_actions,
    get_run_state_from_actions,
    parse_actions_jsonl,
)

logger = logging.getLogger(__name__)


class SimulationRunner:
    """Manages running simulation subprocesses.

    This is a class-level singleton -- all state is shared across
    instances via class attributes.
    """

    _processes: Dict[str, subprocess.Popen] = {}
    _run_states: Dict[str, Dict[str, Any]] = {}
    _start_times: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    @classmethod
    def start_simulation(
        cls,
        simulation_id: str,
        sim_dir: str,
        config: Config,
    ) -> Dict[str, Any]:
        """Start a simulation as a subprocess.

        Writes the simulation config to disk (if not already present),
        spawns ``python -m simulation_engine.run``, and registers cleanup.

        Args:
            simulation_id: Unique simulation ID.
            sim_dir: Path to the simulation directory.
            config: App config (used to locate Python interpreter).

        Returns:
            Dict with ``simulation_id``, ``pid``, ``status``.
        """
        # Check if already running.
        if simulation_id in cls._processes:
            proc = cls._processes[simulation_id]
            if proc.poll() is None:
                logger.warning(
                    "Simulation %s is already running (pid=%d)",
                    simulation_id, proc.pid,
                )
                return {
                    "simulation_id": simulation_id,
                    "pid": proc.pid,
                    "status": "already_running",
                }

        # Verify config file exists.
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                f"Simulation config not found: {config_path}. "
                "Generate it before starting."
            )

        # Ensure the simulation directory has the necessary files.
        os.makedirs(sim_dir, exist_ok=True)

        # Build the command.
        python = sys.executable
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        cmd = [
            python, "-m", "simulation_engine.run",
            "--simulation-id", simulation_id,
            "--sim-dir", sim_dir,
        ]

        # Spawn the subprocess.
        log_path = os.path.join(sim_dir, "subprocess.log")
        log_file = open(log_path, "w")

        env = os.environ.copy()
        # Ensure the backend root is in PYTHONPATH.
        existing_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = backend_root + ((":" + existing_path) if existing_path else "")

        proc = subprocess.Popen(
            cmd,
            cwd=backend_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,  # Detach from parent's process group.
        )

        cls._processes[simulation_id] = proc
        cls._start_times[simulation_id] = time.time()
        cls._run_states[simulation_id] = {
            "status": "running",
            "pid": proc.pid,
            "started_at": time.time(),
        }

        logger.info(
            "Started simulation %s as subprocess pid=%d",
            simulation_id, proc.pid,
        )

        return {
            "simulation_id": simulation_id,
            "pid": proc.pid,
            "status": "running",
        }

    # ------------------------------------------------------------------
    # Get run state
    # ------------------------------------------------------------------

    @classmethod
    def get_run_state(
        cls,
        simulation_id: str,
        sim_dir: str,
    ) -> Dict[str, Any]:
        """Get the current run state of a simulation.

        Reads actions.jsonl, parses progress, and returns a state dict.

        Args:
            simulation_id: Unique simulation ID.
            sim_dir: Path to the simulation directory.

        Returns:
            Dict with ``status``, ``current_round``, ``total_rounds``,
            ``action_counts``, ``recent_actions``, ``pid``, ``elapsed``.
        """
        # Check subprocess status.
        proc = cls._processes.get(simulation_id)
        subprocess_status = "unknown"

        if proc is not None:
            poll = proc.poll()
            if poll is None:
                subprocess_status = "running"
            elif poll == 0:
                subprocess_status = "completed"
            else:
                subprocess_status = "failed"
        else:
            # Check status file.
            status_path = os.path.join(sim_dir, "sim_status.txt")
            if os.path.exists(status_path):
                with open(status_path) as f:
                    subprocess_status = f.read().strip()

        # Read max_rounds from config.
        max_rounds = 10
        config_path = os.path.join(sim_dir, "simulation_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    cfg = json.load(f)
                max_rounds = cfg.get("max_rounds", 10)
            except Exception:
                pass

        # Parse actions.jsonl for progress.
        state = get_run_state_from_actions(sim_dir, max_rounds)

        # Merge subprocess info.
        state["subprocess_status"] = subprocess_status
        state["status"] = subprocess_status

        if proc is not None:
            state["pid"] = proc.pid

        start_time = cls._start_times.get(simulation_id)
        if start_time:
            state["elapsed_seconds"] = round(time.time() - start_time, 1)

        state["simulation_id"] = simulation_id

        return state

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    @classmethod
    def stop_simulation(
        cls,
        simulation_id: str,
        sim_dir: str = "",
    ) -> Dict[str, Any]:
        """Stop a running simulation by sending SIGTERM to its subprocess.

        Args:
            simulation_id: Unique simulation ID.
            sim_dir: Optional sim_dir path (used to read PID file as fallback).

        Returns:
            Dict with ``simulation_id`` and ``status``.
        """
        proc = cls._processes.get(simulation_id)

        if proc is not None:
            if proc.poll() is None:
                logger.info(
                    "Sending SIGTERM to simulation %s (pid=%d)",
                    simulation_id, proc.pid,
                )
                try:
                    os.kill(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

                # Wait briefly for graceful shutdown.
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "Simulation %s did not stop in 10s, sending SIGKILL",
                        simulation_id,
                    )
                    proc.kill()

                cls._run_states[simulation_id] = {"status": "stopped"}

                # Write status file.
                if sim_dir:
                    status_path = os.path.join(sim_dir, "sim_status.txt")
                    try:
                        with open(status_path, "w") as f:
                            f.write("stopped")
                    except Exception:
                        pass

                return {
                    "simulation_id": simulation_id,
                    "status": "stopped",
                }
            else:
                return {
                    "simulation_id": simulation_id,
                    "status": "already_finished",
                    "return_code": proc.poll(),
                }

        # Fallback: try to read PID from file.
        if sim_dir:
            pid_path = os.path.join(sim_dir, "sim.pid")
            if os.path.exists(pid_path):
                try:
                    with open(pid_path) as f:
                        pid = int(f.read().strip())
                    os.kill(pid, signal.SIGTERM)
                    logger.info(
                        "Sent SIGTERM to simulation %s via PID file (pid=%d)",
                        simulation_id, pid,
                    )
                    return {
                        "simulation_id": simulation_id,
                        "status": "stopped",
                        "pid": pid,
                    }
                except (ValueError, ProcessLookupError, PermissionError):
                    pass

        return {
            "simulation_id": simulation_id,
            "status": "not_found",
        }

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    @classmethod
    def cleanup(cls, simulation_id: str) -> None:
        """Remove a simulation from the tracking dicts."""
        cls._processes.pop(simulation_id, None)
        cls._run_states.pop(simulation_id, None)
        cls._start_times.pop(simulation_id, None)

    @classmethod
    def list_running(cls) -> List[Dict[str, Any]]:
        """Return a list of currently tracked simulations."""
        result = []
        for sim_id, proc in cls._processes.items():
            poll = proc.poll()
            result.append({
                "simulation_id": sim_id,
                "pid": proc.pid,
                "running": poll is None,
                "return_code": poll,
            })
        return result
