import json
import os
import time
from pathlib import Path
from typing import Dict, Any

from aether_os.core.run_app import safe_fs

class MemoryManager:
    @staticmethod
    def save_project_memory(project_dir: Path, data: Dict[str, Any]):
        # safe_fs: the sandboxed app writes in project_dir; links are never followed
        safe_fs.safe_makedirs(project_dir, ".aetheros")
        memory_file = project_dir / ".aetheros" / "project_memory.json"

        # Merge if exists
        existing = {}
        text = safe_fs.read_text_or_none(project_dir, memory_file)
        if text is not None:
            existing = json.loads(text)

        existing.update(data)
        safe_fs.safe_write_text(project_dir, memory_file, json.dumps(existing, indent=2))
        return memory_file

    @staticmethod
    def add_changelog_entry(project_dir: Path, entry: str, author: str):
        memory_file = project_dir / ".aetheros" / "project_memory.json"
        text = safe_fs.read_text_or_none(project_dir, memory_file)
        if text is None:
            raise FileNotFoundError("Project memory not found")

        data = json.loads(text)
        changelog = data.get("changelog", [])
        changelog.append({
            "date": time.strftime("%Y-%m-%d"),
            "entry": entry,
            "author": author
        })
        data["changelog"] = changelog
        safe_fs.safe_write_text(project_dir, memory_file, json.dumps(data, indent=2))
