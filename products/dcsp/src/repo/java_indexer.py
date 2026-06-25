"""
Java regex-based indexer for DCSP.
Extracts method and class definitions for Java repositories.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Any


class JavaIndex:
    """Indexes Java source code using regex."""

    def __init__(self) -> None:
        self.functions: Dict[str, Dict[str, Any]] = {}
        self.classes: Dict[str, Dict[str, Any]] = {}
        self.files_indexed = 0

    def index_directory(self, repo_path: str) -> None:
        """Walks the directory and indexes Java files."""
        repo_root = Path(repo_path)
        for root, _, files in os.walk(repo_path):
            for file in files:
                if file.endswith(".java"):
                    self.index_file(os.path.join(root, file), str(repo_root))

    def index_file(self, filepath: str, repo_root: str) -> None:
        """Parses a Java file using regex."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            lines = content.splitlines()
            rel_path = os.path.relpath(filepath, repo_root)

            # Detect methods
            # Matches: public static void main(String[] args) {
            method_pattern = r"(?:public|private|protected|static|\s)+[\w\<\>\[\]]+\s+(?P<method>\w+)\s*\([^)]*\)\s*\{"
            # Detect classes
            class_pattern = r"(?:public|private|abstract)?\s*class\s+(?P<class>\w+)"

            for i, line in enumerate(lines):
                # Check for class
                class_match = re.search(class_pattern, line)
                if class_match:
                    name = class_match.group("class")
                    self.classes[f"{rel_path}:{name}"] = {
                        "name": name,
                        "file": rel_path,
                        "start_line": i + 1,
                        "source": "\n".join(lines[i : i + 50]) # Crude limit
                    }

                # Check for method
                method_match = re.search(method_pattern, line)
                if method_match:
                    name = method_match.group("method")
                    self.functions[f"{rel_path}:{name}"] = {
                        "name": name,
                        "file": rel_path,
                        "start_line": i + 1,
                        "end_line": i + 50,
                        "source": "\n".join(lines[i : i + 50])
                    }
            
            self.files_indexed += 1
        except (UnicodeDecodeError, OSError):
            pass

    def get_context_for_failure(self, failing_file: str, failing_function: str,
                                 line_number: int, max_tokens: int = 2000) -> str:
        """Retrieves Java context for a failure."""
        key = f"{failing_file}:{failing_function}"
        target = self.functions.get(key)
        
        if not target:
            # Try searching by file and line
            for k, func in self.functions.items():
                if func["file"] == failing_file and func["start_line"] <= line_number <= func.get("end_line", line_number + 50):
                    target = func
                    break

        if target:
            header = f"File: {target['file']}\nFunction: {target['name']}\n"
            return f"{header}```java\n{target['source']}\n```\n\n"

        return ""

    def stats(self) -> dict[str, int]:
        return {
            "files_indexed": self.files_indexed,
            "functions_indexed": len(self.functions),
            "classes_indexed": len(self.classes)
        }
