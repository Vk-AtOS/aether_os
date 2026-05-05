import json
import os
import time
from pathlib import Path
from typing import Dict, Any

class MemoryManager:
    @staticmethod
    def save_project_memory(project_dir: Path, data: Dict[str, Any]):
        memory_dir = project_dir / ".aetheros"
        memory_dir.mkdir(exist_ok=True)
        memory_file = memory_dir / "project_memory.json"
        
        # Merge if exists
        existing = {}
        if memory_file.exists():
            existing = json.loads(memory_file.read_text())
        
        existing.update(data)
        memory_file.write_text(json.dumps(existing, indent=2))
        return memory_file

    @staticmethod
    def add_changelog_entry(project_dir: Path, entry: str, author: str):
        memory_file = project_dir / ".aetheros" / "project_memory.json"
        if not memory_file.exists():
            raise FileNotFoundError("Project memory not found")
            
        data = json.loads(memory_file.read_text())
        changelog = data.get("changelog", [])
        changelog.append({
            "date": time.strftime("%Y-%m-%d"),
            "entry": entry,
            "author": author
        })
        data["changelog"] = changelog
        memory_file.write_text(json.dumps(data, indent=2))
