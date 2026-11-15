"""
Static impact simulation for DSEE Phase 2.

Analyzes patch diffs against AST index and call graph to estimate risk,
detecting removed functions, signature changes, and dependency ripples.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dfle.call_graph import CallGraph


@dataclass
class ImpactResult:
    """Result of the impact simulation."""

    safe: bool
    risk_level: str  # "safe", "minor", "risky"
    reasons: list[str] = field(default_factory=list)
    dependency_ripple_count: int = 0


def simulate_impact(patch_diff: str, ast_index: dict[str, dict], call_graph: CallGraph) -> ImpactResult:
    """
    Simulate impact of a patch based on AST changes and call graph.

    Args:
        patch_diff: The unified diff string.
        ast_index: Current AST index (dict from ast_index.py).
        call_graph: Current CallGraph object.

    Returns:
        ImpactResult indicating safety and risk level.
    """
    reasons = []
    risk_level = "safe"
    changed_functions: set[str] = set()

    # Parse diff to identify changed files, hunks, and def changes
    files_info: dict[str, dict] = {}
    current_file = None

    hunk_re = re.compile(r"@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@")
    def_re = re.compile(r"^(?:async\s+)?def\s+([a-zA-Z_][a-zA-Z0-9_]*)")

    lines = patch_diff.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("+++ "):
            # Extract filename, handling b/ prefix
            current_file = line[4:].strip()
            if current_file.startswith("b/"):
                current_file = current_file[2:]
            files_info[current_file] = {
                "added_defs": {},    # name -> content
                "removed_defs": {},  # name -> content
                "shifts": [],        # (old_start, shift)
                "changed_lines": set(),  # old line numbers
            }
            i += 1
            continue

        if current_file and line.startswith("@@ "):
            match = hunk_re.match(line)
            if match:
                old_start = int(match.group(1))
                old_len = int(match.group(2)) if match.group(2) else 1
                new_len = int(match.group(4)) if match.group(4) else 1
                
                # The net shift introduced by this hunk affects lines after it
                files_info[current_file]["shifts"].append((old_start + old_len, new_len - old_len))
                
                # Parse the hunk content
                j = i + 1
                curr_old_line = old_start
                while j < len(lines) and not (lines[j].startswith("@@ ") or lines[j].startswith("+++ ")):
                    hline = lines[j]
                    if hline.startswith("-"):
                        files_info[current_file]["changed_lines"].add(curr_old_line)
                        m = def_re.match(hline[1:].strip())
                        if m:
                            files_info[current_file]["removed_defs"][m.group(1)] = hline[1:].strip()
                        curr_old_line += 1
                    elif hline.startswith("+"):
                        m = def_re.match(hline[1:].strip())
                        if m:
                            files_info[current_file]["added_defs"][m.group(1)] = hline[1:].strip()
                    elif not hline.startswith("\\"):
                        curr_old_line += 1
                    j += 1
                i = j - 1
        i += 1

    # 1. Exported function changes & 4. Call graph expansion
    for filename, info in files_info.items():
        # Exported function changes (removal or signature change)
        for name in info["removed_defs"]:
            if not name.startswith("_"):
                if name not in info["added_defs"]:
                    reasons.append(f"Public function '{name}' removed or renamed in {filename}")
                    risk_level = "risky"
                elif info["removed_defs"][name] != info["added_defs"][name]:
                    reasons.append(f"Public function '{name}' signature modified in {filename}")
                    risk_level = "risky"

        # Call graph expansion (new functions)
        file_index = ast_index.get(filename, {})
        indexed_names = {f["name"] for f in file_index.get("functions", [])}
        for name in info["added_defs"]:
            if name not in indexed_names:
                reasons.append(f"New function '{name}' introduced in {filename}")
                if risk_level == "safe":
                    risk_level = "minor"

    # 2. Signature modification (line shifts) and identifying changed functions for ripple
    for filename, file_index in ast_index.items():
        if filename not in files_info:
            continue
        info = files_info[filename]
        functions = file_index.get("functions", [])
        sorted_funcs = sorted(functions, key=lambda x: x["line"])

        for idx, f in enumerate(sorted_funcs):
            name = str(f["name"])
            old_line = int(f["line"])

            # Find the cumulative shift at this function's position
            applicable_shift = 0
            for threshold, delta in info["shifts"]:
                if old_line >= threshold:
                    applicable_shift += delta

            if abs(applicable_shift) > 5:
                reasons.append(f"Significant line shift ({applicable_shift}) for '{name}' in {filename}")
                risk_level = "risky"

            # Determine function range to check for body changes
            # Assume function ends where next one begins or EOF
            end_line = int(sorted_funcs[idx + 1]["line"]) if idx + 1 < len(sorted_funcs) else 10**9

            was_changed = (name in info["removed_defs"] or name in info["added_defs"])
            if not was_changed:
                for cl in info["changed_lines"]:
                    if old_line <= cl < end_line:
                        was_changed = True
                        break

            if was_changed:
                changed_functions.add(name)

    # 3. Dependency ripple (transitive callers)
    affected_nodes: set[str] = set()
    queue: list[str] = []

    # Initial level: callers of the changed function names
    for func_name in changed_functions:
        for caller in call_graph.callers_of(func_name):
            if caller not in affected_nodes:
                affected_nodes.add(caller)
                queue.append(caller)

    # Transitive levels
    processed: set[str] = set()
    while queue:
        curr_id = queue.pop(0)
        if curr_id in processed:
            continue
        processed.add(curr_id)

        # Extract name from node_id "file:line:name"
        name = curr_id.split(":")[-1]
        for caller in call_graph.callers_of(name):
            if caller not in affected_nodes:
                affected_nodes.add(caller)
                queue.append(caller)

    ripple_count = len(affected_nodes)
    if ripple_count > 0:
        reasons.append(f"Dependency ripple: {ripple_count} downstream functions potentially affected")
        if risk_level == "safe" and ripple_count > 5:
            risk_level = "minor"

    return ImpactResult(
        safe=(risk_level != "risky"),
        risk_level=risk_level,
        reasons=reasons,
        dependency_ripple_count=ripple_count,
    )
