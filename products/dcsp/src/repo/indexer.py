"""
Universal repository indexer for DCSP.
Orchestrates language-specific indexers to provide source context.
"""

from __future__ import annotations

from src.repo.ast_indexer import ASTIndex
from src.repo.js_indexer import JSIndex
from src.repo.java_indexer import JavaIndex


class UniversalIndexer:
    """Combines multiple language-specific indexers."""

    def __init__(self) -> None:
        self.py_index = ASTIndex()
        self.js_index = JSIndex()
        self.java_index = JavaIndex()

    def index_repository(self, repo_path: str) -> dict[str, int]:
        """Indexes the entire repository using all available indexers."""
        self.py_index.index_directory(repo_path)
        self.js_index.index_directory(repo_path)
        self.java_index.index_directory(repo_path)
        
        py_stats = self.py_index.stats()
        js_stats = self.js_index.stats()
        java_stats = self.java_index.stats()

        return {
            "files_indexed": py_stats["files_indexed"] + js_stats["files_indexed"] + java_stats["files_indexed"],
            "functions_indexed": py_stats["functions_indexed"] + js_stats["functions_indexed"] + java_stats["functions_indexed"],
            "classes_indexed": py_stats["classes_indexed"] + js_stats["classes_indexed"] + java_stats["classes_indexed"]
        }

    def get_context(self, language: str, failing_file: str,
                    failing_function: str, line_number: int,
                    max_tokens: int = 2000) -> str:
        """Routes context requests to the appropriate indexer."""
        if language == "python":
            return self.py_index.get_context_for_failure(failing_file, failing_function, line_number, max_tokens)
        elif language == "javascript":
            return self.js_index.get_context_for_failure(failing_file, failing_function, line_number, max_tokens)
        elif language == "java":
            return self.java_index.get_context_for_failure(failing_file, failing_function, line_number, max_tokens)
        else:
            # Fallback to python indexer
            return self.py_index.get_context_for_failure(failing_file, failing_function, line_number, max_tokens)

    def _as_dict(self) -> dict:
        """Build the {filename: {functions: [...]}} dict that simulate_impact expects."""
        out: dict = {}
        for key, fn in self.py_index.functions.items():
            filepath = fn["file"]
            out.setdefault(filepath, {"functions": []})["functions"].append(fn)
        return out

    def get(self, key: str, default=None):
        """Dict-compatible get() so simulate_impact can call ast_index.get(filename, {})."""
        return self._as_dict().get(key, default)

    def items(self):
        """Dict-compatible items() so simulate_impact can iterate ast_index.items()."""
        return self._as_dict().items()

    def clear(self) -> None:
        """Clears all indexed data."""
        self.py_index = ASTIndex()
        self.js_index = JSIndex()
        self.java_index = JavaIndex()


# Singleton instance
GLOBAL_INDEXER = UniversalIndexer()
