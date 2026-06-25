"""
Tests for Python AST indexer.
"""

from __future__ import annotations

import os
import pytest
from pathlib import Path
from src.repo.ast_indexer import ASTIndex


@pytest.fixture
def temp_repo(tmp_path):
    """Creates a temporary repository with fake Python files."""
    repo_dir = tmp_path / "fake_repo"
    repo_dir.mkdir()
    
    # Simple function
    (repo_dir / "utils.py").write_text("""
def add(a, b):
    \"\"\"Adds two numbers.\"\"\"
    return a + b

async def fetch_data(url):
    return {"data": "ok"}
""", encoding="utf-8")

    # Class with methods
    (repo_dir / "models.py").write_text("""
class User:
    def __init__(self, name):
        self.name = name
    
    def greet(self):
        return f"Hello {self.name}"
""", encoding="utf-8")

    # Invalid Python file
    (repo_dir / "bad.py").write_text("if True print('oops')", encoding="utf-8")

    return repo_dir


def test_index_simple_function(temp_repo):
    """Test that functions appear in the index."""
    indexer = ASTIndex()
    indexer.index_directory(str(temp_repo))
    
    assert "utils.py:add" in indexer.functions
    func = indexer.functions["utils.py:add"]
    assert func["name"] == "add"
    assert "Adds two numbers" in func["docstring"]
    assert "return a + b" in func["source"]
    
    assert "utils.py:fetch_data" in indexer.functions


def test_get_context_for_failure(temp_repo):
    """Test context retrieval for a failure site."""
    indexer = ASTIndex()
    indexer.index_directory(str(temp_repo))
    
    # Failure in User.greet at line 7
    context = indexer.get_context_for_failure(
        failing_file="models.py",
        failing_function="greet",
        line_number=7
    )
    
    assert "File: models.py" in context
    assert "Function: greet" in context
    assert "return f\"Hello {self.name}\"" in context


def test_skips_unparseable_files(temp_repo):
    """Test that invalid Python files don't crash the indexer."""
    indexer = ASTIndex()
    # Should not raise SyntaxError
    indexer.index_directory(str(temp_repo))
    
    assert indexer.files_indexed == 2 # utils.py and models.py


def test_stats_after_indexing(temp_repo):
    """Test indexing statistics."""
    indexer = ASTIndex()
    indexer.index_directory(str(temp_repo))
    
    stats = indexer.stats()
    assert stats["files_indexed"] == 2
    assert stats["functions_indexed"] == 4 # add, fetch_data, __init__, greet
    assert stats["classes_indexed"] == 1 # User
