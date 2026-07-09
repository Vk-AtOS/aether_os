"""
AetherOS — Phase DAG (Directed Acyclic Graph) definitions.

Encodes which phases depend on which, enabling topological sort and
parallel execution of independent phases within the same dependency wave.

Usage:
    from aether_os.orchestrator.phase_dag import get_execution_waves, build_dag
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Full dependency map for the 39-phase pipeline.
# Key   = phase name
# Value = list of phases that MUST complete before this phase starts.
# An empty list means the phase has no dependencies (can start immediately).
# ---------------------------------------------------------------------------
PHASE_DEPENDENCIES: Dict[str, List[str]] = {
    # ── 12-stage pipeline (current) ────────────────────────────────────────
    # These are the canonical stage names post-July-2026 refactor.
    "s01_intake":        [],
    "s02_architecture":  ["s01_intake"],
    "s03_backend":       ["s02_architecture"],
    "s04_frontend":      ["s03_backend"],
    "s05_quality":       ["s03_backend", "s04_frontend"],
    "s06_testing":       ["s05_quality"],
    "s07_healing":       ["s06_testing"],
    "s08_observability": ["s07_healing"],
    "s09_devops":        ["s07_healing"],
    "s10_enterprise":    ["s07_healing"],
    "s11_handoff":       ["s08_observability", "s09_devops", "s10_enterprise"],
    "s12_specialist":    ["s04_frontend"],

    # ── Research & intake (legacy p0x_* names — kept for tests and checkpoint resume) ──
    "p00_research":               [],
    "p00b_data_archaeology":      ["p00_research"],
    "p00c_architecture_planner":  ["p00_research"],

    "p01_intake_requirements":    ["p00_research"],
    "p01b_integration_discovery": ["p01_intake_requirements"],

    # ── Architecture & modelling ───────────────────────────────────────────
    "p02_architecture":           ["p01_intake_requirements"],
    "p02b_domain_ir":             ["p02_architecture"],
    "p02c_permission_modeling":   ["p02b_domain_ir"],

    # ── Scaffolding ────────────────────────────────────────────────────────
    "p03_scaffolding":            ["p02b_domain_ir"],

    # ── Backend generation ─────────────────────────────────────────────────
    # p04_backend depends on scaffolding + permission model + integration map.
    "p04_backend":                ["p03_scaffolding", "p02c_permission_modeling",
                                   "p01b_integration_discovery"],
    # p04b and p04c can run in parallel once p04_backend is done.
    "p04b_business_logic":        ["p04_backend"],
    "p04c_integration_codegen":   ["p04_backend", "p01b_integration_discovery"],

    # ── Frontend / client surfaces ─────────────────────────────────────────
    # p05_frontend only needs the backend contract (p04_backend), NOT p04b.
    # This is the key parallelism win: p04b + p05_frontend run concurrently.
    "p05_frontend":               ["p04_backend"],
    "p05b_mobile":                ["p05_frontend"],
    "p05c_desktop":               ["p05_frontend"],
    "p05d_cli":                   ["p04_backend"],      # CLI is backend-only; no frontend dep
    "p05e_serverless":            ["p04_backend"],      # Same logic as CLI

    # ── Security & verification ────────────────────────────────────────────
    # Security review needs BOTH backend (including business logic) and frontend done.
    "p06_review_security":        ["p04b_business_logic", "p05_frontend"],
    # Formal verification only needs the database schema from p04b.
    "p06b_formal_verification":   ["p04b_business_logic"],

    # ── Testing & quality ─────────────────────────────────────────────────
    "p07_testing":                ["p06_review_security"],
    "p07b_self_healing":          ["p07_testing"],

    # ── Delivery pipeline ──────────────────────────────────────────────────
    # p08, p09, p10, p11 all depend on self-healing passing — they are
    # independent of each other and can run concurrently in one wave.
    "p08_cicd_deployment":        ["p07b_self_healing"],
    "p09_observability":          ["p07b_self_healing"],
    "p10_docs_delivery":          ["p07b_self_healing"],
    "p11_deployment":             ["p08_cicd_deployment"],

    # ── Post-deployment observability ──────────────────────────────────────
    # All post-deployment phases require live deployment; they are mutually
    # independent and collapse into a single parallel wave.
    "p11a_monitoring":            ["p11_deployment"],
    "p11b_error_tracking":        ["p11_deployment"],
    "p11c_analytics":             ["p11_deployment"],
    "p11d_alerting":              ["p11_deployment"],
    "p11e_enterprise_deployment": ["p11_deployment"],

    # ── Feature management ─────────────────────────────────────────────────
    "p12a_feature_flags":         ["p11_deployment"],
    "p12b_ab_testing":            ["p11_deployment", "p12a_feature_flags"],

    # ── Memory & portal ────────────────────────────────────────────────────
    "p13_app_memory":             ["p11_deployment"],
    "p14_client_portal":          ["p10_docs_delivery"],

    # ── Handoff ────────────────────────────────────────────────────────────
    "p15_handoff":                ["p14_client_portal", "p10_docs_delivery"],

    # ── Cloud platform extension phases ───────────────────────────────────
    # IAM and billing are independent of each other; both need deployment done.
    "p16_iam":                    ["p11_deployment"],
    "p17_control_plane":          ["p16_iam"],
    "p18_billing_metering":       ["p11_deployment"],
    "p19_service_catalog":        ["p16_iam", "p18_billing_metering"],
    "p20_multiregion":            ["p17_control_plane"],
    "p21_sre_agent":              ["p11_deployment"],
}


def build_dag(phases: List[str]) -> Dict[str, List[str]]:
    """Return the subgraph of PHASE_DEPENDENCIES restricted to *phases*.

    Any dependency that is not present in *phases* is dropped (the phase
    effectively becomes a root within this subgraph).  This lets callers
    safely build partial pipelines (e.g. resume from p06 onwards).

    Args:
        phases: Ordered list of phase names to include in the run.

    Returns:
        Dict mapping each phase to its dependencies that also appear in
        *phases*.
    """
    phase_set = set(phases)
    dag: Dict[str, List[str]] = {}
    for phase in phases:
        known_deps = PHASE_DEPENDENCIES.get(phase)
        if known_deps is None:
            # Phase not in the dependency map — treat as sequential fallback:
            # depend on the phase immediately before it in the provided list.
            idx = phases.index(phase)
            dag[phase] = [phases[idx - 1]] if idx > 0 else []
            logger.debug(
                "[phase_dag] %r not in PHASE_DEPENDENCIES — sequential fallback to %r",
                phase, dag[phase],
            )
        else:
            # Keep only deps that are actually running in this subgraph.
            dag[phase] = [d for d in known_deps if d in phase_set]
    return dag


def _detect_cycle(deps: Dict[str, List[str]]) -> List[str] | None:
    """Return a cycle path if one exists in *deps*, else None.

    Uses iterative DFS with WHITE/GRAY/BLACK colouring to avoid Python
    recursion limits on large dependency graphs.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in deps}
    parent: Dict[str, str] = {}

    for start_node in list(deps.keys()):
        if color.get(start_node, WHITE) != WHITE:
            continue
        # Iterative DFS using an explicit stack.
        # Stack items: (node, iterator_over_neighbors, already_colored_gray)
        stack: list = [(start_node, iter(deps.get(start_node, [])), False)]
        while stack:
            node, neighbors_iter, entered = stack[-1]
            if not entered:
                color[node] = GRAY
                stack[-1] = (node, neighbors_iter, True)
            try:
                neighbor = next(neighbors_iter)
            except StopIteration:
                color[node] = BLACK
                stack.pop()
                continue
            nbr_color = color.get(neighbor, WHITE)
            if nbr_color == GRAY:
                # Back-edge found — reconstruct the cycle path
                cycle = [neighbor, node]
                cur = node
                while parent.get(cur) and parent.get(cur) != neighbor:
                    cur = parent[cur]
                    cycle.append(cur)
                return cycle
            if nbr_color == WHITE:
                parent[neighbor] = node
                stack.append((neighbor, iter(deps.get(neighbor, [])), False))
    return None


def get_execution_waves(phases: List[str]) -> List[List[str]]:
    """Topological sort returning waves of phases that can run in parallel.

    Within a wave, every phase's dependencies have already completed in a
    prior wave, so all phases in the same wave are safe to execute
    concurrently.

    The algorithm is Kahn's BFS topological sort:
      1. Compute in-degree for every node in the subgraph.
      2. Enqueue all zero-in-degree nodes as wave 0.
      3. Remove wave nodes, decrement successor in-degrees; nodes that
         reach 0 in-degree join the next wave.
      4. Repeat until all nodes are placed.

    Args:
        phases: Ordered list of phase names that will run in this pipeline
                invocation.  Order is used only for the sequential fallback
                (phases not in PHASE_DEPENDENCIES).

    Returns:
        List of waves, each wave being a list of phase names.  Phases
        within a wave have no dependencies on each other and can run
        concurrently.  Waves must be executed in order.

    Raises:
        ValueError: If a cycle is detected in the dependency graph (which
                    would indicate a misconfiguration in PHASE_DEPENDENCIES).
    """
    if not phases:
        return []

    dag = build_dag(phases)

    # DFS cycle detection before Kahn's sort — prevents silent hangs on misconfiguration.
    cycle = _detect_cycle(dag)
    if cycle is not None:
        logger.error("[phase_dag] Cycle detected in PHASE_DEPENDENCIES: %s", cycle)
        raise ValueError(f"Cycle detected in PHASE_DEPENDENCIES: {cycle}")

    # In-degree: number of unresolved dependencies per phase.
    in_degree: Dict[str, int] = {p: len(dag[p]) for p in phases}

    # Adjacency: for each phase, which phases depend on it?
    dependants: Dict[str, List[str]] = defaultdict(list)
    for phase, deps in dag.items():
        for dep in deps:
            dependants[dep].append(phase)

    waves: List[List[str]] = []
    # Seed with all phases that have no pending dependencies.
    ready: deque[str] = deque(p for p in phases if in_degree[p] == 0)
    placed = 0

    while ready:
        # All nodes currently in *ready* form the next wave.
        current_wave = list(ready)
        ready.clear()

        # Preserve original ordering within a wave for deterministic output.
        current_wave.sort(key=lambda p: phases.index(p))
        waves.append(current_wave)
        placed += len(current_wave)

        # Unlock successors whose last dependency just completed.
        for phase in current_wave:
            for successor in dependants[phase]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    ready.append(successor)

    if placed != len(phases):
        cycle_phases = [p for p in phases if in_degree[p] > 0]
        raise ValueError(
            f"[phase_dag] Cycle detected in dependency graph — "
            f"phases stuck: {cycle_phases}"
        )

    logger.info(
        "[phase_dag] %d phases → %d waves (max parallelism wave sizes: %s)",
        len(phases),
        len(waves),
        [len(w) for w in waves],
    )
    return waves
