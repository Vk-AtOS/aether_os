"""AetherOS — Multi-tenant project isolation manager."""
from __future__ import annotations
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from pathlib import Path as _Path
from typing import List, Optional

logger = logging.getLogger(__name__)

(_Path.home() / ".aether_os").mkdir(parents=True, exist_ok=True)

_PROJECTS_ROOT = _Path.home() / ".aether_os" / "projects"


@dataclass
class ProjectRecord:
    project_id: str
    client_id: str
    name: str
    created_at: str
    archived: bool = False
    metadata: dict = field(default_factory=dict)


class ProjectManager:
    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = root or _PROJECTS_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path = self._root / "_index.json"
        self._records: dict[str, ProjectRecord] = {}
        self._load_index()

    def _load_index(self) -> None:
        if self._index_path.exists():
            try:
                data = json.loads(self._index_path.read_text())
                for rec in data:
                    r = ProjectRecord(**rec)
                    self._records[r.project_id] = r
            except Exception as e:
                logger.warning("Could not load project index: %s", e)

    def _save_index(self) -> None:
        self._index_path.write_text(
            json.dumps([asdict(r) for r in self._records.values()], indent=2)
        )

    def create_project(self, client_id: str, name: str,
                       metadata: dict | None = None) -> str:
        project_id = str(uuid.uuid4())[:12]
        rec = ProjectRecord(
            project_id=project_id,
            client_id=client_id,
            name=name,
            created_at=datetime.utcnow().isoformat(),
            metadata=metadata or {},
        )
        self._records[project_id] = rec
        self.get_project_dir(project_id).mkdir(parents=True, exist_ok=True)
        self._save_index()
        logger.info("Project created: %s / %s (%s)", client_id, name, project_id)
        return project_id

    def get_project_dir(self, project_id: str) -> Path:
        p = self._root / project_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_output_dir(self, project_id: str, phase: str) -> Path:
        p = self.get_project_dir(project_id) / phase
        p.mkdir(parents=True, exist_ok=True)
        return p

    def list_projects(self, client_id: str) -> List[ProjectRecord]:
        return [r for r in self._records.values()
                if r.client_id == client_id and not r.archived]

    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        return self._records.get(project_id)

    def archive_project(self, project_id: str) -> None:
        if project_id in self._records:
            self._records[project_id].archived = True
            self._save_index()


_manager: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    global _manager
    if _manager is None:
        _manager = ProjectManager()
    return _manager
