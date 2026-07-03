"""
Builds minimal RAG context from CI failure and AST index.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Any, Union

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from aether_os.phases.p08_cicd.dfle.log_parser import ParsedLog, StackFrame
    from src.dfle.ast_index import FileIndexEntry
    from src.repo.indexer import UniversalIndexer
    from src.knowledge.graph import KnowledgeGraph

# Alias as requested by prompt
from aether_os.phases.p08_cicd.dfle.log_parser import ParsedLog as ParsedFailure

# Type alias for index returned by build_index
ASTIndex = Dict[str, Dict[str, Any]]


class ContextBuilder:
    """Retrieves relevant code snippets for a given failure."""

    MAX_TOKENS = 3000
    CHARS_PER_TOKEN = 4  # Conservative estimate

    def __init__(self, root_dir: str | Path = ".") -> None:
        self.root_dir = Path(root_dir)

    def _get_function_source(self, filename: str, func_name: str, start_line: int, index_entry: Dict[str, Any]) -> str:
        """Extract function source code from file."""
        path = self.root_dir / filename
        if not path.exists():
            return ""

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
        except Exception as e:
            logger.warning("p08_cicd context_builder: could not read %s: %s", path, e)
            return ""

        # Find the end of the function. We look for the next function/class start line
        all_markers = []
        for f in index_entry.get("functions", []):
            all_markers.append(f["line"])
        for c in index_entry.get("classes", []):
            all_markers.append(c["line"])
        
        all_markers.sort()
        
        end_line = len(lines)
        for marker in all_markers:
            if marker > start_line:
                end_line = marker - 1
                break
        
        # Take the snippet
        # lines are 0-indexed in list, but start_line in AST is 1-indexed
        snippet = lines[start_line - 1 : end_line]
        return "\n".join(snippet)

    def build(self, failure: ParsedFailure, index: Union[ASTIndex, 'UniversalIndexer'], 
              graph: 'KnowledgeGraph' | None = None, language: str = "python") -> str:
        """
        Build a context string containing relevant code snippets.

        Args:
            failure: The parsed CI log/failure information.
            index: The current AST index or UniversalIndexer.
            graph: Optional KnowledgeGraph for additional context.
            language: The detected language of the failure.

        Returns:
            A formatted context string within the token limit.
        """
        if not failure.stack_traces:
            return "No relevant context found (no stack traces)."

        context_parts = []
        current_char_count = 0
        max_chars = self.MAX_TOKENS * self.CHARS_PER_TOKEN

        # 1. Use UniversalIndexer if provided
        from src.repo.indexer import UniversalIndexer
        if isinstance(index, UniversalIndexer):
            primary_trace = failure.primary_trace
            if primary_trace and primary_trace.frames:
                # Find the most relevant frame (usually the last one in our code)
                last_frame = primary_trace.frames[-1]
                repo_context = index.get_context(
                    language=language,
                    failing_file=last_frame.filename,
                    failing_function=last_frame.function,
                    line_number=last_frame.line,
                    max_tokens=2000
                )
                if repo_context:
                    context_parts.append("SOURCE CODE CONTEXT FROM REPOSITORY:\n")
                    context_parts.append(repo_context)
                    current_char_count += len(repo_context) + 40

        # 2. Use Knowledge Graph context if available
        if graph and current_char_count < max_chars:
            graph_parts = []
            seen_entities = set()
            
            function_names = []
            for trace in failure.stack_traces:
                for frame in trace.frames:
                    function_names.append(frame.function)

            for func_name in function_names:
                related = graph.get_related_entities(func_name, depth=1)
                for entity in related:
                    eid = entity["id"]
                    if eid not in seen_entities:
                        etype = entity["type"]
                        part = f"- {eid} ({etype})\n"
                        if current_char_count + len(part) < max_chars:
                            graph_parts.append(part)
                            current_char_count += len(part)
                            seen_entities.add(eid)
                        else:
                            break
                if current_char_count >= max_chars:
                    break
            
            if graph_parts:
                context_parts.append("\nRELATED ENTITIES FROM KNOWLEDGE GRAPH:\n")
                context_parts.extend(graph_parts)

        # 3. Fallback to existing dict-based indexing if room permits
        if current_char_count < max_chars and isinstance(index, dict):
            # Track seen (file, function) to avoid duplicates
            seen_functions = set()

            for trace in failure.stack_traces:
                for frame in trace.frames:
                    filename = frame.filename
                    func_name = frame.function
                    
                    if (filename, func_name) in seen_functions:
                        continue
                    
                    if filename not in index:
                        continue

                    index_entry = index[filename]
                    
                    # Find matching function in index to get start line
                    start_line = None
                    for f in index_entry.get("functions", []):
                        if f["name"] == func_name:
                            start_line = f["line"]
                            break
                    
                    if start_line is None:
                        continue

                    source = self._get_function_source(filename, func_name, start_line, index_entry)
                    if not source:
                        continue

                    header = f"File: {filename}, Function: {func_name}\n"
                    part = f"{header}```python\n{source}\n```\n\n"
                    
                    if current_char_count + len(part) > max_chars:
                        break
                    
                    context_parts.append(part)
                    current_char_count += len(part)
                    seen_functions.add((filename, func_name))
                
                if current_char_count > max_chars:
                    break

        if not context_parts:
            return "No relevant code found in AST index for the failure site."

        return "".join(context_parts)
