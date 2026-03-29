"""Project model and manager."""
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Project:
    project_id: str = ""
    name: str = ""
    status: str = "created"  # created, ontology_generated, graph_building, graph_built
    files: List[str] = field(default_factory=list)
    simulation_requirement: str = ""
    additional_context: str = ""
    ontology: Optional[Dict[str, Any]] = None
    graph_id: Optional[str] = None
    polymarket_config: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.project_id:
            self.project_id = str(uuid.uuid4())


class ProjectManager:
    def __init__(self, upload_dir: str):
        self.projects_dir = os.path.join(upload_dir, "projects")
        os.makedirs(self.projects_dir, exist_ok=True)

    def _project_dir(self, project_id: str) -> str:
        return os.path.join(self.projects_dir, project_id)

    def _project_file(self, project_id: str) -> str:
        return os.path.join(self._project_dir(project_id), "project.json")

    def create(self, project: Project) -> Project:
        project_dir = self._project_dir(project.project_id)
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(os.path.join(project_dir, "files"), exist_ok=True)
        self.save(project)
        return project

    def save(self, project: Project):
        with open(self._project_file(project.project_id), "w") as f:
            json.dump(asdict(project), f, indent=2)

    def load(self, project_id: str) -> Optional[Project]:
        path = self._project_file(project_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        return Project(**data)

    def get_files_dir(self, project_id: str) -> str:
        return os.path.join(self._project_dir(project_id), "files")

    def get_extracted_text_path(self, project_id: str) -> str:
        return os.path.join(self._project_dir(project_id), "extracted_text.txt")
