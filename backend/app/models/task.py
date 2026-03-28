"""Task model and manager for background operations."""
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Task:
    task_id: str = ""
    task_type: str = ""
    status: str = "pending"  # pending, processing, completed, failed
    progress: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Optional[str] = None

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())


class TaskManager:
    """In-memory task tracking for background operations."""

    _tasks: Dict[str, Task] = {}

    @classmethod
    def create(cls, task_type: str, metadata: Dict = None) -> Task:
        task = Task(task_type=task_type, metadata=metadata or {})
        cls._tasks[task.task_id] = task
        return task

    @classmethod
    def get(cls, task_id: str) -> Optional[Task]:
        return cls._tasks.get(task_id)

    @classmethod
    def update(cls, task_id: str, **kwargs):
        task = cls._tasks.get(task_id)
        if task:
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)

    @classmethod
    def to_dict(cls, task: Task) -> Dict:
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "status": task.status,
            "progress": task.progress,
            "metadata": task.metadata,
            "result": task.result,
            "error": task.error,
        }
