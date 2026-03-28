"""Simulation state lifecycle manager."""
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from app.config import Config


@dataclass
class SimulationState:
    simulation_id: str = ""
    project_id: str = ""
    graph_id: str = ""
    status: str = "created"  # created, preparing, prepared, running, completed, stopped, failed
    name: str = ""
    simulation_requirement: str = ""
    profile_count: int = 0
    config_generated: bool = False

    def __post_init__(self):
        if not self.simulation_id:
            self.simulation_id = str(uuid.uuid4())


class SimulationManager:
    def __init__(self, config: Config):
        self.config = config
        self.sims_dir = os.path.join(config.upload_dir, "simulations")
        os.makedirs(self.sims_dir, exist_ok=True)

    def _sim_dir(self, sim_id: str) -> str:
        d = os.path.join(self.sims_dir, sim_id)
        os.makedirs(d, exist_ok=True)
        return d

    def _state_file(self, sim_id: str) -> str:
        return os.path.join(self._sim_dir(sim_id), "simulation.json")

    def create(self, state: SimulationState) -> SimulationState:
        self.save(state)
        return state

    def save(self, state: SimulationState):
        with open(self._state_file(state.simulation_id), "w") as f:
            json.dump(asdict(state), f, indent=2)

    def load(self, sim_id: str) -> Optional[SimulationState]:
        path = self._state_file(sim_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        return SimulationState(**data)

    def save_profiles(self, sim_id: str, profiles: List[Dict], platform: str):
        """Save profiles in platform-specific format."""
        path = os.path.join(self._sim_dir(sim_id), f"{platform}_profiles.json")
        with open(path, "w") as f:
            json.dump(profiles, f, indent=2)

    def load_profiles(self, sim_id: str, platform: str) -> List[Dict]:
        path = os.path.join(self._sim_dir(sim_id), f"{platform}_profiles.json")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return json.load(f)

    def save_config(self, sim_id: str, config_data: Dict):
        path = os.path.join(self._sim_dir(sim_id), "simulation_config.json")
        with open(path, "w") as f:
            json.dump(config_data, f, indent=2)

    def load_config(self, sim_id: str) -> Optional[Dict]:
        path = os.path.join(self._sim_dir(sim_id), "simulation_config.json")
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def get_sim_dir(self, sim_id: str) -> str:
        return self._sim_dir(sim_id)
