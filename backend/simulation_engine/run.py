"""CLI entry point for running a simulation.

Usage::

    python -m simulation_engine.run --simulation-id <id> --sim-dir <dir>

Loads the simulation config from disk, creates an OasisEnv via the
factory in ``make.py``, and runs ``asyncio.run(env.run())``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from typing import Optional

# Ensure the backend root is on sys.path so that ``app.*`` imports work
# when running as ``python -m simulation_engine.run``.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.config import Config
from simulation_engine.environment.make import create_environment

logger = logging.getLogger(__name__)


def _load_sim_config(sim_dir: str) -> dict:
    """Load simulation_config.json from the simulation directory."""
    config_path = os.path.join(sim_dir, "simulation_config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Simulation config not found: {config_path}")

    with open(config_path) as f:
        data = json.load(f)

    logger.info("Loaded simulation config from %s", config_path)
    return data


def _write_pid_file(sim_dir: str) -> None:
    """Write the current PID to a file so the parent process can track us."""
    pid_path = os.path.join(sim_dir, "sim.pid")
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))


def _write_status(sim_dir: str, status: str) -> None:
    """Write a simple status string to sim_status.txt."""
    status_path = os.path.join(sim_dir, "sim_status.txt")
    with open(status_path, "w") as f:
        f.write(status)


def main(
    simulation_id: str,
    sim_dir: str,
    config: Optional[Config] = None,
    start_round: int = 0,
) -> None:
    """Run a simulation.

    Args:
        simulation_id: Unique simulation identifier (for logging).
        sim_dir: Path to the simulation directory containing config and profiles.
        config: App config.  If ``None``, loaded from environment variables.
        start_round: Round to begin at (0 for fresh, >0 to resume).
    """
    # Setup logging.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join(sim_dir, "simulation.log"),
                mode="a",
            ),
        ],
    )

    logger.info("=" * 60)
    logger.info("SIMULATION START: %s", simulation_id)
    logger.info("  sim_dir: %s", sim_dir)
    logger.info("=" * 60)

    if config is None:
        config = Config.from_env()

    _write_pid_file(sim_dir)
    _write_status(sim_dir, "running")

    # Load simulation config.
    sim_config_data = _load_sim_config(sim_dir)

    # Create environment.
    env = create_environment(sim_config_data, sim_dir, config)

    # Handle signals gracefully.
    def _handle_sigterm(signum, frame):
        logger.info("Received SIGTERM -- stopping simulation gracefully")
        env.stop()

    def _handle_pause(signum, frame):
        if env._paused:
            logger.info("Received SIGUSR1 while already paused -- resuming")
            env.resume()
            _write_status(sim_dir, "running")
        else:
            logger.info("Received SIGUSR1 -- pausing simulation")
            env.pause()
            _write_status(sim_dir, "paused")

    def _handle_resume(signum, frame):
        logger.info("Received SIGUSR2 -- resuming simulation")
        env.resume()
        _write_status(sim_dir, "running")

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGUSR1, _handle_pause)
    signal.signal(signal.SIGUSR2, _handle_resume)

    # Run the simulation.
    try:
        asyncio.run(env.run(start_round=start_round))
        _write_status(sim_dir, "completed")
        logger.info("Simulation %s completed successfully", simulation_id)
    except KeyboardInterrupt:
        _write_status(sim_dir, "stopped")
        logger.info("Simulation %s interrupted", simulation_id)
    except Exception:
        _write_status(sim_dir, "failed")
        logger.exception("Simulation %s failed", simulation_id)
        raise


def cli() -> None:
    """Parse CLI arguments and run."""
    parser = argparse.ArgumentParser(
        description="Run a WhaleSwarm simulation",
    )
    parser.add_argument(
        "--simulation-id",
        required=True,
        help="Unique simulation identifier",
    )
    parser.add_argument(
        "--sim-dir",
        required=True,
        help="Path to the simulation directory",
    )
    parser.add_argument(
        "--start-round",
        type=int,
        default=0,
        help="Round to resume from (0 for fresh start)",
    )
    args = parser.parse_args()

    main(
        simulation_id=args.simulation_id,
        sim_dir=args.sim_dir,
        start_round=args.start_round,
    )


if __name__ == "__main__":
    cli()
