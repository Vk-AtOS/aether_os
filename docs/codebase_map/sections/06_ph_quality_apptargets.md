# 06_ph_quality_apptargets: Quality, security review, formal verification, and the STLC plane

Scope: `phases/p06_review_security`, `p06b_formal_verification`, `p07_testing`, `p07a_unit_testing`, `p07b_performance_testing`, `p07b_self_healing`, `p07c_accessibility_testing`, `p07d_e2e_testing`. That is 36 files and about 5,750 LOC, excluding `__pycache__`. Commit 052a101. Mapped 2026-11-08.
(The `p05b..p05e` app-target phases named in the earlier header belong to another worker and are not covered here.)

Callers: `stages/s05_quality`, `stages/s06_testing`, `stages/s07_healing`, `orchestrator/phase_hooks.py`, and the legacy `orchestrator/pipeline_helpers.py`. They were read only where needed to decide whether gates and tests are actually wired in.

---

## 1. Summary

- **How the phases are called.** In the live 12-stage pipeline (`orchestrator/phase_sequence.py:90-103`), none of these phases is called through its `supervisor_agent.py` or `gate.py`. Stage supervisors import `task_agent.run()` directly:
  - `stages/s05_quality/supervisor.py:69-90,275-301` runs p06 and p06b in parallel.
  - `stages/s06_testing/supervisor.py:56-58,131-145` runs **only p07a**.
  - `stages/s07_healing/supervisor.py:80,127` runs p07b_self_healing.
  - The stage gates for s05, s06 and s07 always return `passed=True` (s05 `:257-271`, s06 `:181-186`, s07 `:245-251`).
  - **As a result, all 8 per-phase `gate.py` files are unused in production.** Only tests import them (`tests/test_phases.py:221-262`, `tests/test_integration_pipeline.py:252-354`).
- **The only real blocking gate in this plane is outside these directories.** It is `orchestrator/phase_hooks.py:76-155` (`_hook_quality_gate`). After `s06_testing` it calls `core/quality/metrics.score_project(project_dir)`. If the score is below 80%, it runs `s07_healing`, up to 2 times. On the 3rd failed score it raises `PipelineBlockedError`.
  - The test component of that score reads `p07_testing/unit_testing/summary.json` or `p07a_unit_testing/summary.json` (`core/quality/metrics.py:184-200`).
  - s06 writes to `s06_testing/unit_testing/summary.json` instead, so in the stage pipeline real pytest results never reach the score. The score falls back to a constant 0.5.
- **What actually executes:**
  - Bandit runs as a subprocess (p06).
  - The CodeScanner and compliance scanner run (p06).
  - pytest runs on a deterministic, template-generated CRUD test file (p07a), plus an import smoke check.
  - pytest runs in the self-healing loop (p07b_self_healing).
  - uvicorn and the QualityMonitor L1–L4 probe run (p07b_self_healing).
  - The performance test is 50 concurrent `GET /health` calls via httpx (p07b_perf).
  - axe (via node) and Playwright (via npx) are launched by p07c and p07d.
  - **However, p07b_perf, p07c and p07d never run in the stage pipeline.** s07 starts them only if `quality_probe.l1_passed` is set (`stages/s07_healing/supervisor.py:196-198`), and grep finds no code that produces that key. They also need a `backend_port` or `frontend_url`, which only s09 produces, after s07.
  - The Locust file is generated but never executed.
- **"Formal verification" (p06b) is AST/regex heuristics wrapped in a trivial Z3 call.** Every check encodes `flag == <python bool>` together with `Not(flag)` (`z3_checkers.py:34-38`, `z3_invariants.py:87-91`). The solver verdict is therefore fixed in advance by the Python boolean. INV-003 is a tautology: it is always VERIFIED when it applies (`z3_checkers.py:128-129`).
- **LLM use in scope** (all via `get_llm_client().call(...)`):
  - p06 OWASP review (`subtasks.py:73-91`, `task_type="code_review"`).
  - p07a `crud.py` import-repair (`task_agent.py:280-293`).
  - p07b_self_healing file-rewrite repair (`task_agent.py:361-434`, two tries per attempt).
  - p07d Playwright spec generation (`task_agent.py:73-82`).
  - `p07_testing/agents.py` TestAgent, which is dead code.
- **Bugs that matter most:**
  - `p07b_self_healing/task_agent.py:217,252` calls `_apply_deterministic_fallback`, which is undefined; the import is `apply_deterministic_fallback`. This raises `NameError` on the 5th attempt.
  - `astor` is missing from requirements and lockfiles. As a result `ASTSecurityPatcher.patch_file` raises, and bandit results are discarded whenever bandit finds a HIGH-severity issue.
  - The p06 gate counts `severity` keys, but bandit emits `issue_severity`. The gate's own docstring calls it a blocker, but it would almost never block.

## 2. Coverage table

| File | LOC | Purpose | Status |
|---|---|---|---|
| p06_review_security/__init__.py | 3 | exports ReviewSecuritySupervisor | REAL (unused in stage path) |
| p06_review_security/supervisor_agent.py | 18 | PhaseBase wrapper: run → task_agent, gate → gate.validate | DEAD in prod (tests only) |
| p06_review_security/task_agent.py | 300 | runs 3 subtasks with `asyncio.gather`, then CodeScanner and dimension critique; writes consolidated.json; `_inject_compliance` regex patcher (G12) | REAL; always `success=True` (:124) |
| p06_review_security/subtasks.py | 389 | `run_code_review` (LLM), `run_bandit_scan` (subprocess), `run_compliance_scan` (scanner, PDF, manifest, file injection) | LLM-DRIVEN + REAL |
| p06_review_security/gate.py | 117 | blocks on ≥1 critical or ≥5 high; regex scan for SQL f-strings and secrets | PLACEBO (not wired; mostly counts 0) |
| p06_review_security/patcher.py | 83 | `ASTSecurityPatcher` (CORS and SECRET_KEY) plus text-insert helpers | Patcher BROKEN (no astor; CORS match never fires); helpers REAL |
| p06_review_security/manifest.py | 112 | writes compliance_manifest.json with SHA-256 drift fingerprint of route files | REAL (duplicates `core/compliance/manifest_writer.py`) |
| p06_review_security/critique_integration.py | 101 | calls `core.quality.dimension_critic.critique_directory`, stores result in input_data | REAL, fail-open; duplicated by s05 (`supervisor.py:105-108`) |
| p06b_formal_verification/__init__.py | 3 | exports FormalVerificationSupervisor | REAL (unused) |
| p06b_formal_verification/supervisor_agent.py | 22 | PhaseBase wrapper | DEAD in prod |
| p06b_formal_verification/task_agent.py | 322 | scans ≤50 .py files, runs Z3Encoder per routes file, builds the PASS/FAIL/PARTIAL report | REAL (heuristic) |
| p06b_formal_verification/z3_encoder.py | 565 | `extract_routes` AST walker, regex helpers, `Z3Encoder.verify_all` (7 invariants) | REAL AST + decorative Z3 |
| p06b_formal_verification/z3_checkers.py | 165 | INV-001..004 checkers | decorative Z3 (bool-equality) |
| p06b_formal_verification/z3_invariants.py | 332 | INV-005..007 checkers (tenant, ownership, tx boundary) | decorative Z3 over regex |
| p06b_formal_verification/prompts.py | 41 | INVARIANT_DESCRIPTIONS, REPORT_HEADER, PATENT_BASIS | DEAD (no importers; grep) |
| p06b_formal_verification/gate.py | 86 | FAIL verdict blocks | PLACEBO (not wired) |
| p07_testing/__init__.py | 3 | exports TestingSupervisor | REAL |
| p07_testing/supervisor_agent.py | 18 | PhaseBase wrapper | DEAD in prod (tests only) |
| p07_testing/task_agent.py | 111 | runs p07a, b, c, d sequentially and aggregates `test_quality_flag` | REAL but only reached through legacy `orchestrator/pipeline.py:163` → `pipeline_helpers.py:220-260`; not in the stage path |
| p07_testing/gate.py | 109 | blocks if flag == fail or pass-rate < 70% | PLACEBO (not wired) |
| p07_testing/agents.py | 40 | TestAgent: LLM smoke-test generator | DEAD (no importers; `agents/implementations.py:303` has its own TestAgent) |
| p07_testing/tools.py | 105 | `run_tests()` subprocess helper | DEAD (no importers) |
| p07_testing/engine.py | 254 | traceback → `pytest.raises` regression-test generator | DEAD (no importers) |
| p07_testing/coverage.py | 461 | `coverage run` + `coverage json` analyzer | DEAD (no importers) |
| p07a_unit_testing/__init__.py | 0 | – | – |
| p07a_unit_testing/task_agent.py | 411 | template CRUD tests, then **runs pytest**, then import smoke check with LLM crud.py repair | TEMPLATE + REAL exec + LLM-DRIVEN repair |
| p07a_unit_testing/gate.py | 32 | blocks only if `success=False` | PLACEBO (task always returns success=True; not wired) |
| p07b_performance_testing/__init__.py | 0 | – | – |
| p07b_performance_testing/task_agent.py | 173 | 50 concurrent GET /health via httpx, p50/p95/p99; writes locustfile (never run) | REAL-trivial + TEMPLATE; never reached in stage path |
| p07b_performance_testing/gate.py | 54 | p95 > 2000 ms or error rate > 10% blocks | PLACEBO (not wired; reads wrong key) |
| p07b_self_healing/__init__.py | 3 | exports SelfHealingSupervisor | REAL |
| p07b_self_healing/supervisor_agent.py | 18 | PhaseBase wrapper | DEAD in prod |
| p07b_self_healing/task_agent.py | **600** | MAX_ATTEMPTS = 5 loop: pytest, then LLM rewrite of failing file, then QualityMonitor probe | REAL + LLM-DRIVEN (at the 600-line cap) |
| p07b_self_healing/quality_helpers.py | 249 | seed UNIQUE dedup, crud relative-import fix, file locators, deterministic fallback regeneration | REAL (fallback unreachable because of NameError) |
| p07b_self_healing/gate.py | 66 | force-passes on max_attempts_reached | PLACEBO by design (not wired) |
| p07c_accessibility_testing/__init__.py | 0 | – | – |
| p07c_accessibility_testing/task_agent.py | 139 | node + axe-playwright script, `<img alt>` regex scan | REAL exec, but false-pass by construction; never reached |
| p07c_accessibility_testing/gate.py | 47 | blocks on > 3 critical/serious | PLACEBO + TypeError (iterates over an int) |
| p07d_e2e_testing/__init__.py | 0 | – | – |
| p07d_e2e_testing/task_agent.py | 150 | LLM or template Playwright spec, then `npx playwright test --reporter=json` | LLM-DRIVEN + REAL exec; never reached |
| p07d_e2e_testing/gate.py | 45 | blocks on > 50% failures | PLACEBO (output_path is a .ts file, so no JSON is ever parsed) |

## 3. Per-phase breakdown

### p06_review_security (runs inside s05, in parallel with p06b)

- **Inputs** (`phase_input.input_data`): `project_dir`, `backend_output_path`, `domain`, `project_name`.
- **Flow.** `task_agent.run` (:43-126) runs three subtasks with `asyncio.gather(..., return_exceptions=True)` (:53-58). Exceptions, and results with an empty `output_path`, are silently dropped (:62-70).

1. **`run_code_review`** (`subtasks.py:31-121`). LLM-DRIVEN.
   - Reads the first 6000 chars of `src/main.py` (:46-53). It reviews only main.py, not routers or models.
   - Prepends `build_compliance_summary(domain)` (:61-71).
   - Prompt: "senior security engineer … OWASP Top-10 … Return JSON {findings[{issue,severity high|medium|low,line_hint,recommendation}],overall_score,summary}" (:73-86).
   - Call: `get_llm_client().call(prompt, task_type="code_review")` with a 150 s timeout (:87-90).
   - Output: `code_review/review.json`. If JSON parsing fails, the score defaults to `overall_score: 75` (:95).
   - Metadata carries counts only. The findings themselves are not in metadata.
2. **`run_bandit_scan`** (:124-287). REAL.
   - Runs `pip install bandit -q` at runtime on every run (:145-150), although bandit is already in `requirements.txt:74`.
   - Then runs `bandit -r -f json -ll src/` (:151-156). Because of `-ll`, LOW findings are never reported.
   - Files bandit skipped for parse errors become a synthetic HIGH finding, and confidence drops to 0.3 (:170-188, :215).
   - Output: `security/security_scan.json`.
   - If any HIGH finding exists, it calls `ASTSecurityPatcher().patch_file()` on each flagged file, or on main.py (:240-264).
3. **`run_compliance_scan`** (:290-389). REAL.
   - Runs `core.compliance.code_scanner.scan_file(main.py)` and writes `compliance/compliance_scan.json` plus `compliance_report.pdf` via `generate_pdf`.
   - **Mutates the generated `main.py` in place** via `_inject_compliance` (`task_agent.py:133-297`):
     - CORS `["*"]` → env-driven list.
     - Hardcoded SECRET_KEY → `os.environ.get(..., token_hex)`.
     - A plaintext `password ==` comparison gets a comment only.
     - A SECRET_KEY null guard.
     - A slowapi limiter (default limits 200/day and 50/hour) inserted after `app = FastAPI(`.
     - An audit-log middleware that decodes the JWT payload **without verifying the signature**, for logging only.
   - Writes `compliance_manifest.json` (`manifest.py`) and `domain_knowledge.json` into the project root.
   - Back-propagates `compliance_score`, `compliance_pdf_path` and `compliance_manifest_path` into `input_data` (:363-366).
4. **CodeScanner extended scan** (`task_agent.py:73-91`). Runs `core.security.code_scanner.CodeScanner().scan_project(project_dir, domain)` and writes `security/extended_scan.json`. The result is not included in consolidated.json.
5. **Dimension critique** (`critique_integration.py`). Writes `dimension_critique` and its summary into `input_data`. s05 re-runs the same critic on `backend_output_path`.

- **Output:** `consolidated.json`, holding `phases.{code_review, static_analysis, compliance}` with output_path, success, confidence and metadata. `success=True` is hard-coded (:124).
- **Gate (`gate.py`, unwired).**
  - Thresholds: critical ≥ 1 or high ≥ 5 blocks (:18-19).
  - Severity counting walks for `"severity"` keys (:22-35). consolidated.json contains bandit's `issue_severity` and only LLM finding *counts*, so the counts are about 0.
  - The fallback regex scan globs `p04*/backend_codegen/src` under the project root (:75). In the stage pipeline p04a writes `p04a_backend_codegen/src` (`core/quality/metrics.py:335`), so the glob likely matches nothing.
  - Even when a regex hits, it only sets `n_high = max(n_high, 1)` (:82, :87), so it can never reach 5. It is effectively a placebo.

### p06b_formal_verification (runs inside s05)

- **Inputs:** `project_dir`, then `output_path`, then `backend_output_path` (:184-189). Also `project_name` and `domain`.
- **Flow.**
  - Checks `import z3` (:198-204). `z3-solver` is in `requirements.txt:76`. If z3 is missing, the verdict is PARTIAL.
  - `_find_py_files` takes ≤ 50 files from src/, app/, api/, routers/ and the root (:42-56). It excludes only `__pycache__`, so in a project root it can pick up scaffolding and p07a test files.
  - `_parse_file` skips files over 200 KB.
  - `Z3Encoder(module_ast).verify_all()` runs for each file that has routes (:232-246).
- **Route extraction** (`z3_encoder.py:215-322`).
  - A function is a route if it has `@<x>.get|post|...` decorators.
  - Any `try`, `yield`/`yield from`, or `getattr` in the function body marks it UNVERIFIABLE for all 7 invariants (:254-270).
  - Auth is detected from `Depends(<name>)` where `<name>` is in a 7-name allowlist (:82-90) and appears in decorators, annotations or defaults.
  - Router-level or app-level `dependencies=[...]` are **not** recognised.
- **Invariants** (all use "Z3" as `flag==bool ∧ ¬flag`):

| ID | Real check | Location |
|---|---|---|
| INV-001 auth | `has_auth_depends`. Every public route (/health, /login, /register) is VIOLATED | z3_checkers.py:55-97 |
| INV-002 input | no `request.body/json/form()` | :100-113 |
| INV-003 state machine | if `ALLOWED_TRANSITIONS` is referenced, `fact=True` (cannot fail), else N/A | :116-140 |
| INV-004 SQL | no f-string argument to `.execute/.query/.raw/.text/.exec_driver_sql` | :143-158; z3_encoder.py:147-164 |
| INV-005 tenant | tenant column plus select present but no `.where/.filter(...org_id...)` regex match | z3_invariants.py:52-117 |
| INV-006 ownership | DELETE/PUT/PATCH with auth and an id lookup but no ownership regex match | :143-227 |
| INV-007 tx boundary | more than 1 `await db.commit()/flush()` | :241-303 |

- **Report** (`task_agent.py:80-159`).
  - Deduplicates on `(invariant_id, route_name)` across all files (:100-105), so a VIOLATED result for a same-named route in a second file is hidden.
  - N/A counts as "verified".
  - Verdict: FAIL if any violation, PARTIAL if z3 is missing or no routes were found, otherwise PASS.
  - Confidence = verified / total.
  - Written to the phase directory and the project root (:273-295).
  - `success = verdict in (PASS, PARTIAL)`.
- **Gate** (`gate.py`): FAIL blocks. It is not wired, so in s05 a FAIL only adds `issues` strings (`s05/supervisor.py:92-95`) and a `verification_report` in the metadata. The docstring claim that a FAIL raises `PipelineBlockedError` (`task_agent.py:10`) is false.
- **LLM:** none, although `core/llm/phase_config.py:37` configures one.

### p07_testing (consolidator)

- `task_agent.run` (:24-111) imports p07a, p07b_perf, p07c and p07d and awaits them **sequentially**, each with a 150 s timeout.
  - Idempotency cache: if `consolidated.json` already shows a pass, it is returned without re-running (:29-43).
- Aggregation (:73-95): `passed_tests` comes from `metadata.passed_tests` or `metadata.passed`.
  - Bug: p07b_perf and p07c put a **bool** into `passed`. True counts as 1/1, which sets `pytest_actually_passed=True` even when pytest failed.
  - Flag: pass if ≥ 70%, warn if ≥ 40%, otherwise fail. `success=True` always (:109).
- Only reached from the legacy `orchestrator/pipeline_helpers.py:220-260`. That path passes only `generated_code`, `language` and `project_name`, so p07a has no `project_dir` and falls back to its fallback tests.
- s06 has a copy of this aggregation logic in `_consolidate_results` (`stages/s06_testing/supervisor.py:199-290`).

### p07a_unit_testing (the only test layer that runs in the stage pipeline, via s06)

- **Inputs:**
  - `canonical_src_dir`, `backend_src_dir` or `main_py`.
  - Otherwise `project_dir` and the candidate paths `p04_backend/backend_codegen/src`, `p04a_backend_codegen/src`, `src`.
  - Otherwise the deepest `main.py` found by glob (:18-60).
  - Also `entities` and `project_name`.
- **Generation is TEMPLATE, not LLM** (the docstring at :1 is stale).
  - `_generate_crud_tests` (:63-166) produces 4 tests:
    - `GET /health` == 200.
    - `GET /api/{table}/` == 200, after register and login at `/api/auth/register|login`.
    - `POST /api/{table}/` in (200, 201).
    - `GET /api/{table}/1` in (200, 404).
  - With no entities, `_fallback_tests` (:169-220) produces a health check plus `app is not None`. The generated code references an undefined `logger` at :203, so the except branch would raise NameError.
- **Execution (REAL):** `python3 -m pytest tests/test_main.py -v --tb=short -p no:cacheprovider --timeout=30`, with cwd = src_dir, `DATABASE_URL=sqlite+aiosqlite:///./test.db` and a 60 s timeout (:351-366).
  - Uses the **AetherOS host interpreter**, not the generated app's venv.
  - Writes `test.db` into the generated `src/`.
  - Pass and fail counts are regex-parsed from the output (:370-375).
- **Import smoke check (REAL):** `_exec_validate_startup` (:223-318) runs `python3 -c "from src.main import app"` with a 20 s timeout.
  - On failure, if `routers/crud.py` exists and the error mentions crud or import, it sends an LLM repair prompt ("Fix the import error … Return ONLY the complete fixed crud.py") via `llm.call(task_type="code_generation", max_tokens=4000)` with a 60 s timeout.
  - The returned crud.py is **written over the original without backup**, then re-validated once.
- **Output:** `tests/test_main.py`, `pytest_output.txt`, `summary.json` `{tests_written, test_file, passed, failed, errors, exec_validation}`. `success=True` always (:409).
- **Gate:** placebo. It blocks only if `success` is false, and it checks a `test_files` key that is never written (`gate.py:28`).

### p07b_performance_testing

- With no `backend_port`, it is skipped (:38-50). With a port, it requires a /health status below 400, otherwise `success=False` (:63-80).
- Load: `asyncio.gather` of 50 `httpx.AsyncClient().get(/health)` calls, with a new client per request (:19-28, :83-84).
- Metrics: p50, p95, p99, mean, error_rate_pct. `passed = error_rate < 10% and p95 < 2000 ms` (:102).
- Writes a Locust file with `/health` plus `/api/{slug}s` per entity (:110-147). That URL scheme differs from p07a's `/api/{table}/`. **The Locust file is never executed.**
- **Gate:** reads `error_rate` or `errors_pct`, but the task writes `error_rate_pct` (`gate.py:36`), so the error-rate branch is dead.

### p07c_accessibility_testing

- Skipped unless `frontend_url` or `app_url` is set (:67-78).
- Writes a Node script (`_AXE_SCRIPT`, :13-47) that `require`s the npm packages `playwright` and `axe-playwright`. Only the Python `axe-playwright-python` is listed in `requirements.txt:83`, and the script runs from `output_dir`, which has no `node_modules`.
- It calls `checkA11y(..., skipFailures=true)`, which **does not throw**. The script then prints `violations: 0`, so a run that reaches it reports a false pass. If `require` fails, `{error}` JSON is merged and `violations` stays 0, so `passed=True` (:130).
- Static check: per-file "`<img` present and no `alt=` anywhere in the file" (:118-128). The button check is a `pass` no-op (:124-125).
- A static WCAG checklist is embedded but never evaluated.
- **Gate:** iterates `violations`, which is an int, as a list (`gate.py:31-32`). That raises TypeError, which is swallowed into an issue string.

### p07d_e2e_testing

- Skipped unless `frontend_url` or `app_url` is set.
- LLM prompt: "Generate Playwright TypeScript e2e tests … load homepage, /health, list pages, navigation", via `llm.call(task_type="code_generation", max_tokens=2000)` (:73-82).
- If the LLM fails, a 3-test template is used. It hard-codes `http://localhost:8000` and `body.status == 'ok'` (:16-40).
- Writes `playwright.config.ts`, then runs `npx playwright test e2e.spec.ts --reporter=json` from output_dir with a 120 s timeout (:117-123). There is no package.json and no `@playwright/test` install there.
- Stats are parsed from the JSON (`expected` / `unexpected`). `success=True` always.
- **Gate:** `output_path` is the `.ts` file, so no JSON candidate is ever found and the gate passes (`gate.py:23-27`).

## 4. Self-healing loop (p07b_self_healing/task_agent.py)

- **Entry.** s07 calls `heal_run` (`stages/s07_healing/supervisor.py:127`).
  - If the quality hook set `accumulated_context["s07_healing_done"]` (static score ≥80) and s06's unit tests all passed, s07 first starts and probes the app without the repair loop (`_probe_only`); it calls `heal_run` only if that live check fails. The static score never skips the app start (KAN-247).
  - The s07 gate blocks when the app did not start, a spec'd `/api/<table>` list endpoint returned 5xx/404, or healing ended exhausted (`stages/s07_healing/run_verdict.py`). Live perf/a11y/e2e tests that did not run or failed go to `metadata["not_verified"]`, which keeps the run from `completed` (`orchestrator/stage_gate.py:final_run_status`).
  - The quality hook calls `run_phase_fn("s07_healing")` up to 2 times when the score is below 80 (`orchestrator/phase_hooks.py:94-127`). Total worst case: 2 hook calls plus the scheduled s07 run, each with up to 5 attempts.
- **Hard cap.** `_PHASE_HARD_TIMEOUT = 5 × (60 + 45 + 15) = 600 s` (:34-38). On timeout it returns `status=phase_timeout` with `success=True` (:95-109).
- **Workspace.** `project_dir` is hard-coded to `~/.aether_os/projects/{phase_input.run_id}` (:116). It ignores `input_data.project_dir`, and other phases key on `project_id`.
  - `main_py` and `test_file` are taken as the **deepest** `main.py` and `test_*.py` anywhere under the project (`_find_file`, :594-600). This is typically p07a's `s06_testing/unit_testing/tests/test_main.py`, but it could be another main.py (CLI, desktop).
  - If either file is missing, it returns `skipped` (:134-143).
- **Context passed to the repair:** `entities`, `quality_score_details` (the hook injects the metric breakdown at `phase_hooks.py:114-125`), and `council_feedback`.

**Per-attempt loop (`while attempt < MAX_ATTEMPTS = 5`, :148-252):**

1. **Detect.** `_run_tests` runs `python3 -m pytest <test_file> -v --tb=short --timeout=30`, with cwd = `test_file.parent.parent`, sqlite env and a 60 s timeout. Pass means returncode == 0 (:277-311).
2. **If tests pass, verify live.** `_quality_probe` (:437-591):
   - Picks a free port and writes a temporary `.env` (DATABASE_URL sqlite, random SECRET_KEY, random ADMIN_PASSWORD) **only if no `.env` exists**. If one exists, the probe password does not match the admin seed, which likely produces a false `auth_failure`.
   - Starts `uvicorn src.main:app` from the backend directory, waits up to 10 s, and runs `core.quality_monitor.QualityMonitor(...).run_full_check()` (L1–L4).
   - Deterministic fixes:
     - `auth_failure` → `fix_seed_unique_violations` (adds `_n` suffixes to duplicate email, username, slug, file_path, code or sku values in seed.py).
     - `empty_crud` → `fix_crud_relative_imports`.
   - Each fix calls `_record_repair` → `core.error_registry` and `core.repair_learning.learn_from_repair` (`quality_helpers.py:27-51`).
   - If a fix was applied, the loop `continue`s to re-test, consuming an attempt (:168-170). Otherwise it returns `status=all_tests_passing` with confidence 0.9, 0.7 or 0.5 depending on the attempt number, capped at 0.5 if the probe found a failure (:172-203).
3. **If tests fail, diagnose.** `_identify_failing_file` (:41-90) picks the **last** `File "...py"` traceback frame that is not under site-packages or pytest. Fallbacks: `ERROR collecting`, `FAILED x.py::`, `ImportError … in`, and finally main.py.
4. **Patch (LLM).** `_get_fix` (:314-434):
   - Re-derives the target from the **first** traceback frame and may switch `target_file` to it (:324-332). That frame is often the test file.
   - Context:
     - the full target file;
     - siblings main.py, models.py, schemas.py, routers/crud.py, auth.py and database.py, with the total capped at 12,000 chars;
     - the test file (2,000 chars);
     - the failure output (2,000 chars);
     - quality metrics below 80;
     - council feedback;
     - 13 hard rules (no relative imports, `all_routers` export, bcrypt, `scalars().all()`, timezone-aware datetimes, lifespan decorator placement).
   - Prompt opening: "You are a senior Python backend engineer. Fix the FastAPI backend so all tests pass … Return ONLY the fixed complete {file}".
   - Calls `llm.call(prompt, "code_generation", {})` with a 45 s timeout. On failure it retries once with an "Output ONLY valid Python" prefix. Each response must `compile()`.
5. **Apply.**
   - `compile()` check, then a regex that strips relative imports, then `compile()` again. For crud.py, `all_routers = [...]` is auto-appended (:220-245).
   - Then `failing_file.write_text(fix)` (:247), with **no backup, no diff limit, and no rollback** if the next run is worse.
   - **Target mismatch bug.** `_get_fix` may have produced a rewrite of a *different* file (first traceback frame) than the one written (`failing_file`, from the last frame). That can overwrite file B with file A's content. The test file can also be "healed", which makes tests pass by editing the test.
6. **Last attempt.** Calls `_apply_deterministic_fallback(...)` (:217, :252). **That name is undefined**: only `apply_deterministic_fallback` is imported (:22-29). This raises `NameError`, which escapes `run()` because only TimeoutError is caught (:95-97). So the intended "regenerate crud.py and seed.py from `p04a_backend_codegen.crud_generator._fallback_*`" step (`quality_helpers.py:226-249`) never runs.
7. **Exhausted** (only if the NameError path is avoided, which is impossible once attempt 5 is reached with a failure): `status=max_attempts_reached`, `success=False`, `self_healing_exhausted=True` (:256-274).

- **Re-verify.** It re-runs the same pytest file on the next iteration. There is no regression suite, so only one test file is ever the oracle.
- **After healing in s07.**
  - Runs `core.validators.run_all_validators(backend_path)`, additive only.
  - Records stage feedback.
  - Computes `healing_passed = status == all_tests_passing` (`supervisor.py:169-172`).
  - Live perf, a11y and E2E tests are gated on `quality_probe.l1_passed`, a key no code writes, so they never run.
- **Gate** (`p07b_self_healing/gate.py`): force-passes even when `max_attempts_reached` (:41-61). It is unwired anyway.

## 5. Plane mapping

**STLC test levels**

| Level | Component | Generated by | Executed? | Blocks? |
|---|---|---|---|---|
| Unit / API smoke | p07a CRUD tests | TEMPLATE | YES, pytest subprocess (s06) | Only indirectly via `score_project`, and the test_score read path misses s06's output (constant 0.5) |
| Startup / import | p07a `_exec_validate_startup` | – | YES | No |
| Integration (live app) | p07b_self_healing `_quality_probe` with QualityMonitor L1–L4 | – | YES, uvicorn on a temp port | No (lowers confidence) |
| Regression (heal oracle) | p07b_self_healing `_run_tests` | reuses p07a file | YES, up to 5× | No (`healing_passed` flag only) |
| Performance | p07b_perf httpx burst on /health; Locust file | TEMPLATE | Burst only if a port is set; **never in stage path**; Locust never | No |
| Accessibility | p07c axe + `<img alt>` regex | TEMPLATE JS | Only if frontend_url is set; **never in stage path**; false pass | No |
| E2E | p07d Playwright | LLM-DRIVEN or TEMPLATE | Only if frontend_url is set; **never in stage path** | No |
| Security SAST | p06 bandit, CodeScanner, compliance scanner, LLM review | – | YES (s05) | No (s05 gate always passes; findings flow to `healing_priority`, `s05/supervisor.py:196-198`) |
| Formal | p06b heuristic + Z3 | – | YES (s05) | No |
| Coverage | `p07_testing/coverage.py` | – | DEAD | – |

- **SDLC:** this plane is the verification and validation stage between codegen (s03, s04) and DevOps (s09). It feeds `score_project`, which is the single real quality gate (threshold 80, 3 tries, `PipelineBlockedError`). It also writes in-place fixes back into the generated source: compliance injection, AST patch, LLM crud repair, heal rewrites, seed and crud fixes.
- **Security:** OWASP review (LLM), bandit, secret, domain and pip-audit checks (CodeScanner), CORS and secret hardening, rate limiting, audit middleware injection, the 7-invariant heuristic verifier, and the dimension critic.
- **Compliance:** domain packs (HIPAA, GDPR, PCI-DSS, SOC2 version strings hard-coded at `manifest.py:93-98`), the scan PDF, `compliance_manifest.json` with a `drift_fingerprint` meant for a CI drift gate ("Gap 3", which is elsewhere), and `domain_knowledge.json`.
- **SRE:** self-healing loop, QualityMonitor health layers, latency percentiles, and learning from repairs (`core/repair_learning`, `core/error_registry`). There is no SLO enforcement.

## 6. Interfaces and dependencies

- **Contracts:** `phases.base.TaskResult` (output_path, confidence, metadata, success, issues, artifacts, confidence_reason) and `GateOutcome`. The entrypoint signature is `run(phase_input, memory_ctx, output_dir)`.
- **Core services used:**
  - `core.llm.client.get_llm_client().call(prompt, task_type, context, …)` (`core/llm/client.py:123`).
  - `core.compliance.code_scanner.scan_file`, `core.compliance.pdf_report.generate_pdf`.
  - `core.domain_knowledge.loader.build_compliance_summary` and `load_pack`.
  - `core.security.code_scanner.CodeScanner`, `core.quality.dimension_critic.critique_directory`.
  - `core.quality_monitor.QualityMonitor`, `core.error_registry`, `core.repair_learning`.
  - `orchestrator.events.emit`, `phases.utils.memory_hint`.
  - `phases.p04a_backend_codegen.crud_generator._fallback_crud_routers` and `_fallback_seed`.
- **External tools:** bandit (pip-installed at runtime), python3, pytest (with pytest-asyncio, pytest-timeout, httpx and aiosqlite in the host env), uvicorn, z3-solver, node with the npm packages playwright and axe-playwright (not provisioned), npx `@playwright/test` (not provisioned). `astor` is required but absent.
- **input_data keys read:** project_dir, backend_output_path, domain, project_name, entities, canonical_src_dir, backend_src_dir, main_py, backend_port, frontend_url, app_url, frontend_port, frontend_src_dir, quality_score_details, council_feedback.
- **input_data keys written:** compliance_score, compliance_pdf_path, compliance_manifest_path, dimension_critique, dimension_critique_summary.
- **Callers:** s05 (p06, p06b), s06 (p07a), s07 (p07b_self_healing, plus p07b_perf, p07c and p07d via the dead `LIVE_TEST_PHASES` path), the legacy `orchestrator/pipeline_helpers.py` (p07_testing.task_agent), and `artifact_collector.py:115-117` (artifact grouping).

## 7. Reality check

**Placebo gates**
- All 8 `gate.py` files are unwired in the stage pipeline.
- s05, s06 and s07 stage gates hard-code `passed=True`.
- Every task_agent here returns `success=True` regardless of findings, except p06b (FAIL → False), p07b_perf (unreachable app → False) and p07b_self_healing (exhausted → False). None of those False values blocks anything.

**Hollow test-score signal**
- `metrics._check_test_score` looks for `p07_testing/unit_testing/summary.json` or `p07a_unit_testing/summary.json`. s06 writes `s06_testing/unit_testing/summary.json`, so the score is a constant 0.5 (`core/quality/metrics.py:184-200`).

**Bugs, with locations**
1. `p07b_self_healing/task_agent.py:217,252`: `_apply_deterministic_fallback` is undefined, so NameError on attempt 5.
2. `p07b_self_healing/task_agent.py:211-212,247` vs `:324-332`: the fix target and the written file can differ, so the wrong file is overwritten. Test files can also be rewritten to pass.
3. `p06_review_security/patcher.py:37-42`: astor is not installed (absent from requirements.txt, uv.lock and requirements.lock), so `patch_file` raises. In `subtasks.py:240-264,285-287` that discards the entire bandit result whenever a HIGH finding exists.
4. `patcher.py:19`: the CORS AST patch matches a call whose attribute is `CORSMiddleware`. Real code is `app.add_middleware(CORSMiddleware, allow_origins=...)`, so it never fires.
5. `p06_review_security/gate.py:22-35,55-59,75,82,87`: severity keys don't match bandit's, consolidated.json holds counts only, the glob path is stale, and high can never reach 5.
6. `p06b`:
   - INV-001 flags every public route as a violation, so the verdict is FAIL for nearly any app with /health or /login, unless the handler has a `try` block, which makes it UNVERIFIABLE.
   - The Z3 calls are decorative.
   - INV-003 can never fail.
   - Deduplication across files hides violations (`task_agent.py:100-105`).
   - The file scan includes non-app files.
7. `p07_testing/task_agent.py:76-84` and `stages/s06_testing/supervisor.py:229-239`: bool `passed` counted as 1/1 sets `pytest_actually_passed` to true incorrectly.
8. `p07a_unit_testing/task_agent.py:203`: the generated fallback test uses an undefined `logger`. `:354,363`: `test.db` is written into the generated src/.
9. `p07b_performance_testing/gate.py:36`: wrong key (`error_rate` vs `error_rate_pct`).
10. `p07c`: `skipFailures=true` means axe never reports violations (`task_agent.py:23`). The gate iterates an int (`gate.py:31`).
11. `p07d/gate.py:23-27`: the `.ts` output path means results are never parsed.
12. `stages/s07_healing/supervisor.py:196`: `l1_passed` is never produced, so the live tests are dead.
13. `p07b_self_healing/task_agent.py:477-492`: the probe password only matches when `.env` was absent.
14. p06 audit middleware (`task_agent.py:274-279`) decodes the JWT without verification, for logging only. The user identity in audit logs is therefore spoofable.
15. p06 runs `pip install bandit` on every run (`subtasks.py:145-150`). That needs network access and mutates the server environment.

**Dead code** (grep-verified: no importers)
- `p07_testing/agents.py`, `tools.py`, `engine.py`, `coverage.py` (860 LOC).
- `p06b_formal_verification/prompts.py`.
- All `supervisor_agent.py` files in scope, which are reached only by tests.
- `PipelineBlockedError`, `os` and `_SUBTASK_TIMEOUT` are imported or defined but unused in `p06_review_security/task_agent.py:6,12,40`.

**Duplication**
- `p06_review_security/manifest.py` vs `core/compliance/manifest_writer.py` (same function name, different signature).
- The dimension critic runs twice (p06 and s05).
- The p07 aggregation is copied into s06 `_consolidate_results`.
- `_TENANT_FILTER_RE` and the commit regex appear in both `z3_encoder.py:329-342` and `z3_invariants.py:40-43,235-238`.

**Stale docstrings**
- p07a "generates via LLM".
- p07b_self_healing "using Ollama".
- p06b "FAIL raises PipelineBlockedError".
- `critique_integration.py:4` "task_agent.py is at the 580-line limit" (it is 300 lines).

**Files over 600 lines:** none. `p07b_self_healing/task_agent.py` is exactly 600, at the cap, and `z3_encoder.py` is 565.

## 8. Open questions

1. Is `phase_input.run_id == project_id` always true in the stage pipeline? p07b_self_healing builds its path from `run_id` (:116), while s05 and s06 use `project_id`.
2. Is the legacy `orchestrator/pipeline.py` single-code path (which calls p07_testing) still reachable from any API route, or is it fully superseded by the 12 stages?
3. Does `core/quality_monitor.QualityMonitor.to_dict()` expose an L1 result that s07 was meant to read as `l1_passed`? If so, the key-name mismatch is the only thing disabling the live tests.
4. Does the generated app's seed read `ADMIN_PASSWORD` and `admin@example.com`, the credentials the probe uses (`task_agent.py:521-526`)?
5. Where is the "Gap 3" CI drift gate that recomputes `drift_fingerprint`? It is outside this scope and should be confirmed in the p08 / s09 sections.
6. Does `s05_quality/gate_functions.detect_critical_issues` consume p06's findings in a way that triggers real regeneration? p06 metadata carries only counts and not the LLM findings, so it is unclear what s05 reads.
7. Does any deployment image install astor, node `axe-playwright` and `@playwright/test`? If not, the AST patching and the a11y/E2E layers can never succeed even if wired.
