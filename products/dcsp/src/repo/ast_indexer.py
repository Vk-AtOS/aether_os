"""
Python AST indexer for DCSP.
Parses Python files to extract function and class source code.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Dict, Any, Optional


class ASTIndex:
    """Indexes Python source code using the ast module."""

    def __init__(self) -> None:
        # Key: "filename:function_name"
        self.functions: Dict[str, Dict[str, Any]] = {}
        self.classes: Dict[str, Dict[str, Any]] = {}
        self.files_indexed = 0

    def index_directory(self, repo_path: str, extensions: list[str] | None = None) -> None:
        """Walks the directory and indexes all matching files."""
        if extensions is None:
            extensions = [".py"]
        
        repo_root = Path(repo_path)
        skip_dirs = {"venv", "node_modules", ".git", "__pycache__"}

        for root, dirs, files in os.walk(repo_path):
            # Prune directories to skip
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            
            for file in files:
                if any(file.endswith(ext) for ext in extensions):
                    filepath = os.path.join(root, file)
                    self.index_file(filepath, str(repo_root))

    def index_file(self, filepath: str, repo_root: str) -> None:
        """Parses a single file and extracts definitions."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            
            tree = ast.parse(source)
            rel_path = os.path.relpath(filepath, repo_root)
            lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start_line = node.lineno
                    end_line = getattr(node, "end_lineno", start_line)
                    func_source = "\n".join(lines[start_line - 1 : end_line])
                    
                    key = f"{rel_path}:{node.name}"
                    self.functions[key] = {
                        "name": node.name,
                        "file": rel_path,
                        "start_line": start_line,
                        "end_line": end_line,
                        "source": func_source,
                        "docstring": ast.get_docstring(node) or ""
                    }
                
                elif isinstance(node, ast.ClassDef):
                    start_line = node.lineno
                    end_line = getattr(node, "end_lineno", start_line)
                    class_source = "\n".join(lines[start_line - 1 : end_line])
                    
                    key = f"{rel_path}:{node.name}"
                    self.classes[key] = {
                        "name": node.name,
                        "file": rel_path,
                        "start_line": start_line,
                        "end_line": end_line,
                        "source": class_source,
                        "docstring": ast.get_docstring(node) or ""
                    }
            
            self.files_indexed += 1
        except (SyntaxError, UnicodeDecodeError, OSError):
            # Silently skip files that fail to parse
            pass

    def get_context_for_failure(self, failing_file: str, failing_function: str, 
                                 line_number: int, max_tokens: int = 2000) -> str:
        """Retrieves relevant code context for a given failure site."""
        context_parts = []
        current_chars = 0
        max_chars = max_tokens * 4

        # 1. Find the specific function containing the line
        target_func = None
        for key, func in self.functions.items():
            if func["file"] == failing_file and func["start_line"] <= line_number <= func["end_line"]:
                target_func = func
                break
        
        # Fallback to function name if line number check fails
        if not target_func:
            key = f"{failing_file}:{failing_function}"
            target_func = self.functions.get(key)

        if target_func:
            header = f"File: {target_func['file']}\nFunction: {target_func['name']}\n"
            block = f"{header}```python\n{target_func['source']}\n```\n\n"
            context_parts.append(block)
            current_chars += len(block)

            # 2. Find callers (simple string search)
            for key, func in self.functions.items():
                if current_chars >= max_chars:
                    break
                
                if target_func["name"] in func["source"] and func != target_func:
                    header = f"File: {func['file']}\nFunction: {func['name']} (Potential Caller)\n"
                    block = f"{header}```python\n{func['source']}\n```\n\n"
                    if current_chars + len(block) <= max_chars:
                        context_parts.append(block)
                        current_chars += len(block)

        return "".join(context_parts)

    def stats(self) -> dict[str, int]:
        """Returns indexing statistics."""
        return {
            "files_indexed": self.files_indexed,
            "functions_indexed": len(self.functions),
            "classes_indexed": len(self.classes)
        }
