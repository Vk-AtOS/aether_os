"""
JavaScript/TypeScript regex-based indexer for DCSP.
Extracts function and method definitions without external dependencies.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Any


class JSIndex:
    """Indexes JavaScript/TypeScript source code using regex."""

    def __init__(self) -> None:
        self.functions: Dict[str, Dict[str, Any]] = {}
        self.files_indexed = 0

    def index_directory(self, repo_path: str) -> None:
        """Walks the directory and indexes JS/TS files."""
        repo_root = Path(repo_path)
        skip_dirs = {"node_modules", "dist", "build", ".git"}
        extensions = {".js", ".ts", ".jsx", ".tsx"}

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    self.index_file(os.path.join(root, file), str(repo_root))

    def index_file(self, filepath: str, repo_root: str) -> None:
        """Parses a JS/TS file using regex to find functions."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            
            lines = content.splitlines()
            rel_path = os.path.relpath(filepath, repo_root)

            # Patterns for function declarations, arrow functions, and class methods
            # Matches: function name(), const name = () =>, name: async function()
            pattern = r"(?:function\s+(?P<func1>\w+)|(?P<func2>\w+)\s*[:=]\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>))"
            
            for i, line in enumerate(lines):
                match = re.search(pattern, line)
                if match:
                    func_name = match.group("func1") or match.group("func2")
                    if not func_name:
                        continue

                    # Very crude "end of function" detection: find next function or end of file
                    # In a real tool, we'd use a parser, but batch requirement says regex.
                    # We'll take up to 50 lines or next match for now.
                    start_line = i + 1
                    end_line = min(i + 50, len(lines))
                    
                    key = f"{rel_path}:{func_name}"
                    self.functions[key] = {
                        "name": func_name,
                        "file": rel_path,
                        "start_line": start_line,
                        "end_line": end_line,
                        "source": "\n".join(lines[i : end_line])
                    }
            
            self.files_indexed += 1
        except (UnicodeDecodeError, OSError):
            pass

    def get_context_for_failure(self, failing_file: str, failing_function: str,
                                 line_number: int, max_tokens: int = 2000) -> str:
        """Retrieves JS context for a failure."""
        context_parts = []
        current_chars = 0
        max_chars = max_tokens * 4

        # Search for function containing the line
        target_func = None
        for key, func in self.functions.items():
            if func["file"] == failing_file and func["start_line"] <= line_number <= func["end_line"]:
                target_func = func
                break
        
        if not target_func:
            key = f"{failing_file}:{failing_function}"
            target_func = self.functions.get(key)

        if target_func:
            header = f"File: {target_func['file']}\nFunction: {target_func['name']}\n"
            block = f"{header}```javascript\n{target_func['source']}\n```\n\n"
            context_parts.append(block)
            current_chars += len(block)

        return "".join(context_parts)

    def stats(self) -> dict[str, int]:
        return {
            "files_indexed": self.files_indexed,
            "functions_indexed": len(self.functions),
            "classes_indexed": 0 # Not explicitly tracked separately in JS regex impl
        }
