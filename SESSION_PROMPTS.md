# AetherOS — 4-Session Parallel-Agent Execution Prompts
**Purpose:** copy-paste prompts that drive Claude/Sonnet + parallel subagents through all 51 open items in `plans2.md`, at minimum token cost.

---

## Why these prompts are token-cheap (the 7 rules baked into them)

1. **One source of truth, referenced by ID.** Never paste audit text into a prompt. `plans2.md` already contains file paths and line numbers for every item. The prompt says "execute S1–S4" — the agent reads only that table.
2. **Forbid re-auditing.** The single biggest token waste is an agent re-reading the codebase to convince itself. Every prompt says: *trust plans2.md, open only the files your items name.*
3. **A status ledger carries memory between sessions.** Each session ends by updating a `STATUS` column in plans2.md. The next session's prompt is two lines because the state lives in the repo, not the conversation.
4. **Partition agents by file ownership, not by topic.** Two agents editing `p05_frontend/task_agent.py` = merge conflicts = redone work = double tokens. Each agent below owns disjoint files.
5. **Terse reporting contract.** Agents report `ID → commit → pass/fail`, nothing else. No narration, no summaries of what the code does.
6. **Right-size the model per agent.** Mechanical items (hygiene, docs, renames) → cheapest model. Generation-core items (Q1, Q3, Q4) → strongest model. Say so explicitly.
7. **History rewrite runs solo.** `git filter-repo` (S1) invalidates every worktree and clone. It runs first, alone, before any parallel agent starts. Same reason: `git worktree prune` (H4) immediately before it.

**Your manual items (no agent can do these — do them between sessions 1 and 2):**
P3 fix Anthropic payment · S2 rotate AWS/JWT/admin secrets in consoles · P1/P2 VPS console: `alembic upgrade heads`, `git pull`, restart · P4/P5 set keys in VPS `.env`.

---

## SESSION 1 — Security, hygiene, honest gates (items: S1–S4, H1–H5, D1–D5, C1, C2, C4, C5, C6, A4)

```
Read plans2.md. Add a STATUS column to every table if not present. This session executes: S1-S4, H1-H5, D1-D5, C1, C2, C4, C5, C6, A4. Do not re-audit anything; trust plans2.md and open only files named in those items.

Order:
1. SOLO, before any subagents: H4 (git worktree prune), then S1 (git filter-repo purge of auth_res.json). Verify with: git log --all -- auth_res.json returns empty. Do NOT force-push; leave that for my confirmation.
2. Then spawn 4 parallel subagents with worktree isolation, partitioned by file ownership:
   - Agent A (files: CLAUDE.md, AETHEROS_ACQUISITION_DUE_DILIGENCE.md, README.md, launch/): S3, S4, D1, D2, H5. Use measured numbers already written in DUE_DILIGENCE_AUDIT.md section 1 — do not recount.
   - Agent B (files: repo root PNGs, graphify-out/, vkatos_deploy/): H1, H2, H3. Move to docs/assets/, delete obvious working screenshots.
   - Agent C (files: phases/p05_frontend/task_agent.py, stages/s04_frontend/supervisor.py, core/llm/client.py, .env.example): C1, C2, C5, C6.
   - Agent D (files: main.py, tests/test_integration_pipeline.py, tests/test_factory.py): C4, D3, A4.
3. Merge agents sequentially, one commit per item, commit message = "fix(<ID>): <root cause>".
4. Verify: run ./scripts/smoke_test.sh http://localhost:8000 if runnable, else pytest tests/test_core.py tests/test_phases.py -q. All 748 files must still ast.parse.
5. Update STATUS in plans2.md for every completed item. Report ONLY: table of ID → commit hash → pass/fail. Flag S2, P1-P5 as "waiting on human".

Cheapest model for agents A, B, D. Do not deploy to VPS.
```

---

## SESSION 2 — Code defects, honest metrics, architecture debt (items: C3, C7, C8, Q2, Q7, Q8, Q9, A1, A6, A7, A8, A3-flag)

```
Read plans2.md STATUS column. This session executes: C3, C7, C8, Q2, Q7, Q8, Q9, A1, A6, A7, A8. No re-auditing; open only files named in those items.

Spawn 4 parallel subagents, worktree isolation, disjoint files:
- Agent A (core/model_router.py, tests/test_model_router.py, orchestrator/routing/): C7 first — fix root cause until all 3 tests pass — then C8. Strongest model.
- Agent B (core/services/run_app_service.py, gateway/routers/run_app_router.py): C3 + A1 (same inversion, one fix, two IDs).
- Agent C (phases/p04b_business_logic/task_agent.py, phases/p05_frontend/task_agent.py metadata block, core/pipeline_state.py or run metadata model): Q2, Q7, Q8, Q9. Confidence formula: build_pass AND tsc_errors==0 AND template_fallback_pct — document the formula in code comment.
- Agent D (core/billing/, core/billing_impl.py, orchestrator/pipeline.py, orchestrator/phase_sequence.py): A6, A7, A8 — consolidate/rename only, zero behavior change, verify imports still resolve.

Rules: one commit per item, root cause in message, no file may cross 600 lines (A3 files are at the limit — split before touching if needed). After merge: pytest tests/ -q (skip network-dependent), report pass count vs last session. Update plans2.md STATUS. Report only ID → commit → pass/fail.
```

---

## SESSION 3 — The generation core (items: Q1, Q3, Q6, Q10, Q11, Q5) — the hard session

```
Read plans2.md STATUS. This session executes Q1, Q3, Q6, Q10, Q11, Q5. This is generation-core work: use the strongest model for agents A and B. No re-auditing.

Spawn 4 parallel subagents, worktree isolation, disjoint files:
- Agent A — LLM-first UI (owns phases/p05_frontend/ EXCEPT prompts.py and code_writer.py config generators): Q1 + Q6. New module llm_page_writer.py: for each entity page, dashboard, and portal page, one frontier-model call with Domain IR + api_routes + design tokens + raw user prompt; template generators become the fallback, not the default. Record template_debt_pct (wired in session 2). Do not delete code_writer.py — demote it.
- Agent B — compile loop (owns new file phases/p05_frontend/build_loop.py + task_agent.py build section): Q3. tsc --noEmit + vite build → parse errors → one LLM fix call per round → max 3 rounds → gate result feeds C1/C2 logic from session 1.
- Agent C — design system + seed data (owns phases/p05_frontend/prompts.py, new design_system.py, seed path in phases/p04a_backend_codegen/crud_generator_seed.py): Q11 + Q10. One token set + component conventions; LLM-generated domain-plausible seed content, verify seed renders in list pages.
- Agent D — frontend scoring (owns core/quality/): Q5. Extend dimension critic to TS/TSX via tsc + eslint + axe-core subprocess calls; score frontend files in s05.

Merge order: C → A → B → D (A and B both touch task_agent.py sections — B rebases on A).
Verify: run one full local pipeline build (any domain prompt), confirm: build passes, pages are LLM-authored (template_debt_pct < 50%), seed data visible. Update plans2.md STATUS. Report ID → commit → template_debt_pct → build result only.
```

---

## SESSION 4 — Visual loop, benchmark, remaining debt, sale package (items: Q4, Q12, A2, A5, OD3, final verification)

```
Read plans2.md STATUS. Final session: Q4, Q12, A2, A5, OD3, plus release verification. Strongest model for Agent A.

Spawn 5 parallel subagents:
- Agent A (phases/p05_frontend/domain_assembler.py:468-472, preview.py): Q4 — remove the "if not is_autonomous" guard; autonomous loop = screenshot → VLM rubric critique (hierarchy, spacing, contrast, emptiness, genericness) → apply_gate2_revisions → re-screenshot, 2 rounds max.
- Agent B (new: scripts/benchmark_harness.py, benchmarks/prompts/*.md): Q12 — 10 golden prompts across domains; per run score: build pass, pytest pass, template_debt_pct, VLM rubric; output benchmarks/results/<date>.json + md summary. Make it runnable by a buyer with one command.
- Agent C (docs): regenerate AETHEROS_ACQUISITION_DUE_DILIGENCE.md from current measured state (git count, file count, test count, benchmark results), zero credentials, zero unverifiable claims. Mark D4/D5 resolved.
- Agent D (A2 bounded pass — cheapest model): grep function-scoped imports, rank files by count, fix the top 20 offender files only (move imports to module top unless a comment marks circular-import necessity). Record remaining count in plans2.md so the next pass is measurable. A2/OD1 is incremental by design — do not attempt all 1,028.
- Agent E (A5 code side + OD3): A5 — write the Alembic migration to VECTOR(1536), the pgvector SQLAlchemy adapter, and a runtime feature-flag fallback to the JSON path; mark the server-side CREATE EXTENSION step as WAITING-ON-HUMAN. OD3 — split dashboard/src ProjectView.jsx (2,233 lines) into route-level chunks; zero behavior change, verify dashboard builds.

Then SOLO final verification (no subagent):
1. pytest tests/ -q — record exact pass/fail vs session 1 baseline.
2. Run benchmark harness once; attach results.
3. Run 2 full pipeline builds (different domains); confirm the two apps are visibly different (screenshots) and both build clean.
4. Sweep plans2.md: every item either DONE (commit ref) or explicitly WAITING-ON-HUMAN with reason. Zero silent skips.
5. Update STATUS, write SALE_READINESS.md: one page, measured claims only.

Report: final STATUS table + benchmark scores + the list of remaining human-only items. Do not deploy to VPS without my confirmation.
```

---

## DELTA — open items from the desktop "plans 2.md" (master history, §20E/§23C/§25A/§25B)

The desktop master document adds open items beyond the folder's 51-item list. Fold these into the sessions as follows (reference them by these IDs; full detail is in "plans 2.md" sections §23C, §25A, §25B, §20E):

**Add to SESSION 2 (backend/DB mediums — new Agent E, files: core/models.py, core/services/learning_service.py, gateway/routers/webhooks_router.py, core/run_app/process_manager_helpers.py, alembic/):**
- §25A M1 — occurrence_count non-atomic increment race
- §25A M2 — hardcoded preview JWT secret baked into generated apps
- §25A M3 — webhook secrets stored plaintext (hash on write)
- §25A M4 — AuditLog.org_id missing index
- §25A M5 — SamlConfig missing unique constraint on org_id
- §25A M7 — Organisation/User missing updated_at
- §25A M10 — admin_router.py 479 lines, business logic in router (split to service)

**Add to SESSION 3 (generated-app quality gaps — these belong with the generation-core work):**
- §23C-1 — ABAC permission model never enforced in generated CRUD: map permission_model.json to route-level require_role guards in p04a/crud_generator.py (~100–150 lines). The model is currently cosmetic.
- §23C-2 — FK fields render as number inputs: generate <select> with useEffect fetch of related entities (p05_frontend/ir_generators.py:27). Fold into Agent A (Q1) scope explicitly.
- §23C-3 — BackendAuditCouncil reads only main.py: concatenate main.py + crud.py + models.py + schemas.py (orchestrator/phase_hooks.py:503). One-line change, large review-quality impact.
- §23C-4 — p07c/p07d live tests silently skip when Docker/port absent: pipeline must record "live tests did not run" as a run-level flag, not silence.
- §20E — domain pack constraints (HIPAA PHI masking, FinTech Numeric, audit columns) not wired into schema_builder/ir_generators: inject during generation.
- §23C-16 — p16_iam OPA policies built from hardcoded template: read permission_model.json instead.

**Add to SESSION 4 (dashboard + cleanup — new Agent F, files: dashboard/src/, orchestrator/phase_hooks.py):**
- §25A M11 — RunDetail calls GET /factory/runs/{id}/events; no backend route: add route or remove tab
- §25A M12/M17 — unguarded console.error in production (Settings.jsx, FeedbackPanel.jsx)
- §25A M13/M14 — Pricing INR-only fallback + flash of hardcoded plans
- §25A M15 — key={index} on dynamic lists (PromptInput, IntelligenceHub)
- §25A M16 — bare catch {} with no error state (AuditLogs.jsx)
- §25B L1–L3 — OAuthCallback ErrorBoundary, download catch feedback, dead import
- §25B L4–L6 — Settings.jsx (1,814), ProjectDesigner.jsx (1,564), NewProjectWizard/RunDetail/IntelligenceHub/AdminUsers over 600: split the two worst (L4, L5); log the rest as approved-or-split decisions
- §25B L7 — phase_hooks.py at 613 lines: split (it's over the hard limit)
- §23C cleanup — delete dead LLM CRUD path + dead PromptCompiler call sites in p04a, or wire them; remove p04_uiux_design dead phase; fix p04b bare `pass` (task_agent.py:132); p02b stale comment
- §20E — D8: stop describing AST linting as "formal verification"; remove hardcoded patent_eligible flag

**Already covered by existing sessions (no action):** §25A M6 = A5 (pgvector), M8 fixed, M9 = A2 (function-scoped imports — note desktop says 1,694, folder says 1,028; Agent D records the true count). V1–V31 were fixed in the undeployed July 17–19 commits — they ship with the human VPS deploy (P2). OD3 = ProjectView.jsx already assigned.

**Human-only additions from the desktop file:** demo video (5-min end-to-end recording — required for any sale conversation; record it after session 4's verification run), E2E pipeline run on VPS, Microns listing decision.

---

## Coverage matrix — all 51 plans2.md items

| Session | Items |
|---|---|
| 1 | S1, S3, S4, H1–H5, D1–D3, C1, C2, C4, C5, C6, A4 |
| 2 | C3, C7, C8, Q2, Q7, Q8, Q9, A1, A3 (flag/split rule), A6, A7, A8 |
| 3 | Q1, Q3, Q5, Q6, Q10, Q11 |
| 4 | Q4, Q12, A2/OD1 (bounded pass), A5/OD2 (code side), OD3, D4, D5 |
| Human-only (between sessions) | S2 (rotate secrets), P1, P2 (VPS console), P3 (Anthropic payment), P4, P5 (VPS .env), A5 server step (CREATE EXTENSION), OD4 (VPS deploy — unblocks after P3) |

Every item is either assigned to a session or explicitly human-only. A2/OD1 is bounded (top-20 files per pass) because plans2.md itself marks it incremental — the remaining count is recorded each pass so it converges measurably.

## SESSION 5 — Mop-up + first real E2E run (no VPS needed)

```
Read PROJECT_STATE_AUDIT.md (W6/W7 sections) and plans2.md STATUS. This is the final engineering session. No re-auditing — open only files named here. One commit per item, root cause in message.

Part 1 — remaining code items (spawn 2 parallel subagents, worktree isolation):
- Agent A (phases/p05_frontend/: domain_assembler.py, llm_page_writer.py, helpers.py, task_agent.py metadata block):
  1. W6 — extend LLM-first authorship to Dashboard.tsx and customer portal pages (same pattern as write_entity_page_llm: raw prompt + IR + design tokens, template fallback, counted in template_debt). Landing page optional if time allows.
  2. W6b — make template_debt_pct count ALL generated pages (dashboard, layouts, portal), not just entity pages. Document the denominator in a code comment.
  3. W7 — raise vlm_rubric_critique max_tokens 300→1000; widen apply_gate2_revisions candidate list to include all files in src/pages/; confirm task_type="ui_critique" is registered in model_registry (add it if missing).
  4. W3b — degraded flag: treat bedrock-Nova as degraded=true; only anthropic/gemini frontier tiers count as non-degraded. Keep model_used accurate.
- Agent B (repo-wide, cheapest model):
  5. A2 second pass — next 20 offender files for function-scoped imports; record remaining count in plans2.md.
  6. Regenerate local secrets in .env: new AETHER_SECRET_KEY, AETHER_ONE_ZT_SECRET, AETHER_ADMIN_PASS(WORD) via secrets.token_urlsafe; sync both env var names; update .env.example placeholders. Do NOT touch AWS keys — flag them as HUMAN (AWS console rotation).

Part 2 — SOLO, after merge (sequential, this is the first-ever real E2E):
7. git remote add origin https://github.com/Vk-AtOS/aether_os.git, then STOP and ask me to confirm before running: git push --force origin main (history was rewritten — this replaces GitHub history and kills the leaked JWT).
8. Boot the server locally (python main.py start or uvicorn per RUNBOOK), seed admin, verify /health.
9. Run ./scripts/smoke_test.sh http://localhost:8000 — report results.
10. Trigger ONE real pipeline build via the API with prompt: "Build a veterinary clinic management app with appointments, patients, owners, invoices, and a vaccination schedule." Watch it end-to-end. Report: per-stage status, template_debt_pct, model_used, build_loop rounds/tsc_errors, confidence, whether Gate-2 critique ran with vision, and paste the final app's file tree (top 2 levels).
11. If the run fails at any stage: diagnose root cause, fix (one commit), re-run once. Do not patch forward more than once — report instead.
12. Update plans2.md STATUS + CURRENT_STATE.md. Final report: table of item → commit → status, then the E2E run summary. Nothing else.

Known constraint: PRIMARY_LLM=bedrock (Nova) until the Anthropic payment is fixed — the E2E run validates wiring, not final output quality. Note in the report anywhere Nova visibly hurt output.
```

---

## Honest expectations

- 4 sessions closes every **agent-doable** item if sessions 1–2 go clean. Q1/Q3/Q4 quality (not just "implemented") depends on iteration — the benchmark harness in session 4 tells you truthfully whether output now competes, and session 4's build comparison is the acceptance test.
- "Sale-worthy" additionally requires your manual items (payment fix above all — without a frontier model key, session 3's work runs on Nova Lite and will not look better) and the 20-app gallery, which is compute + curation on top of session 4's harness, not new engineering.
- If a session dies mid-way, restart cost is two lines — "Read plans2.md STATUS, continue the session N block" — because all state lives in the ledger. That is the design.
