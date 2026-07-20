# AetherOS — Master Fix List
**Compiled:** 2026-07-20 · **Sources:** AUDIT_OUTPUT_QUALITY.md (fact-checked), DUE_DILIGENCE_AUDIT.md (fact-checked), structural audit HEAD c1eb396

Items are ordered by priority within each category. Nothing omitted.

---

## CATEGORY 0 — SECURITY (do before anything else, including any code-room access)

| ID | Item | File / Location | Action | STATUS |
|----|------|----------------|--------|--------|
| S1 | **JWT in git history** | `auth_res.json` in commit `cf06c57` (May 8 2026) | Run `git filter-repo --path auth_res.json --invert-paths` — purges it from all history. Force-push after. Anyone with the repo can extract this token today. | ✅ DONE (history rewritten; force-push pending human confirmation) |
| S2 | **Rotate all secrets** | `.env` on disk | AWS keys (`AKIAV7DCRLLWRKABRC7Q` + secret), admin password, `AETHER_SECRET_KEY`, `AETHER_ONE_ZT_SECRET`, `SCIM_BEARER_TOKEN` are all present in plaintext `.env`. Rotate every one before any handoff or code-room access. | ⏳ WAITING ON HUMAN |
| S3 | **Scrub the DD document** | `AETHEROS_ACQUISITION_DUE_DILIGENCE.md` | Contains demo credentials and VPS IP in its header. Cannot be handed to a buyer as-is. Regenerate from measured numbers (see S4), remove all credentials. | ✅ DONE 4cadf4e |
| S4 | **CLAUDE.md embeds VPS IP and password** | `CLAUDE.md` root | VPS IP `139.59.87.218` and password `Shadow@317!` are in the file. Remove before any repo is shared. | ✅ DONE 98c12b1 |

---

## CATEGORY 1 — PRODUCTION BLOCKERS (VPS is currently broken)

| ID | Item | File / Location | Action | STATUS |
|----|------|----------------|--------|--------|
| P1 | **Login 500 on VPS** | `alembic/versions/` — `add_must_change_password` migration not applied | `alembic upgrade heads` via DigitalOcean console. No code change. | ⏳ WAITING ON HUMAN |
| P2 | **28 commits not deployed** | All July 17/18/19 fix sessions (V1–V31, 9 CRITICAL, 15 HIGH, 22 MEDIUM/LOW) | `git pull` on VPS + `systemctl restart aetheros`. VPS is running pre-sprint code. | ⏳ WAITING ON HUMAN |
| P3 | **Anthropic payment instrument blocked** | `.env`: `ANTHROPIC_API_KEY=` empty; comment says "INVALID_PAYMENT_INSTRUMENT" | Fix the payment on the Anthropic account. This is the single biggest output-quality lever — switches from Nova Lite/Llama-3.3-70B back to claude-sonnet-4-6. One afternoon of work, instant quality jump. | ⏳ WAITING ON HUMAN |
| P4 | **No frontier model key on VPS** | VPS `.env` unknown | Confirm `ANTHROPIC_API_KEY` (or `GOOGLE_API_KEY` / `OPENROUTER_API_KEY`) is set in VPS production `.env`. Without one, every pipeline run silently falls back to Ollama which is not installed on VPS. | ⏳ WAITING ON HUMAN |
| P5 | **`AETHER_ADMIN_PASS` on VPS** | `core/seed.py` reads it at startup | Confirm it is set in VPS `.env`. If missing, seed crashes on startup and no admin account is created. | ⏳ WAITING ON HUMAN |

---

## CATEGORY 2 — CODE DEFECTS (bugs in shipped code)

| ID | Item | File / Location | Action | STATUS |
|----|------|----------------|--------|--------|
| C1 | **npm build failure returns `success=True, confidence=1.0`** | `phases/p05_frontend/task_agent.py:455–459` | Catch the build exception, set `success=False`, propagate to s04 gate. This means a broken frontend currently ships as "complete." | ✅ DONE 8c48435 |
| C2 | **s04 frontend gate only checks file existence** | `stages/s04_frontend/supervisor.py:264` — gate passes if `index.html` or `App.tsx` exists | Add: gate must require a passing `npm run build`. File existence is not a passing build. | ✅ DONE 01ee4e3 |
| C3 | **Circular import: `core` → `gateway`** | `core/services/run_app_service.py:53` — `from aether_os.gateway.routers.run_app_router import start_run_app` | Deferred import hides it now. Will crash in any worker or test that imports this service before gateway init. Inline the function or pass as a callable argument. | ⬜ TODO |
| C4 | **`main.py` startup banner hardcodes "153 passing"** | `main.py:110` | Update to current count (639) or derive it dynamically. Misleading to any technical evaluator who runs the server. | ✅ DONE e3a87d0 |
| C5 | **`PRIMARY_LLM` defaults to `"ollama"` silently** | `core/llm/client.py:87` — `os.environ.get("PRIMARY_LLM", "ollama")` | If codegen falls back to Ollama, log a WARNING at run start that output quality will be degraded. Currently completely silent. | ✅ DONE adb242d |
| C6 | **`COUNCIL_STRICT_MODE=false` — council verdicts never block** | `.env:38` + `core/council/council.py` | Council reviews run but their FAIL verdict is non-blocking. Either set `COUNCIL_STRICT_MODE=true` in production or document explicitly that it is review-only. As-is it implies quality enforcement that doesn't exist. | ✅ DONE 6cde4c8 |
| C7 | **3 failing model-router tests** | `tests/test_model_router.py` — provider-selection and fallback-logic tests | Fix root cause in `core/model_router.py`. These are the exact tests covering the subsystem that decides which LLM generates code — failing tests here are a red flag in any technical review. | ⬜ TODO |
| C8 | **Circular import: `core/model_router.py` → `orchestrator`** | `core/model_router.py:57` — lazy import of `orchestrator.routing.ahm` | Same pattern as C3. Will surface if load order changes. Extract shared piece or pass as argument. | ⬜ TODO |

---

## CATEGORY 3 — OUTPUT QUALITY (the "template-stamping machine" problem)

Items in priority order from AUDIT_OUTPUT_QUALITY.md P0 → P2.

| ID | Item | File / Location | Action | STATUS |
|----|------|----------------|--------|--------|
| Q1 | **Every user-visible frontend surface is a static template** | `phases/p05_frontend/code_writer.py` — 60 f-string generators, zero LLM | Every page (dashboard, entity pages, data tables, customer portal) should be written per-app by a frontier model given: Domain IR + API contract + design system + raw user prompt. Keep deterministic scaffolding for build config, auth, router shell — those are correct and stable. | ⬜ TODO |
| Q2 | **`max_tokens=3000` on business logic generation** | `phases/p04b_business_logic/task_agent.py:244,296` | Raise significantly (8000–16000). Entire workflow engines are being generated in a single 3k-token call. Truncated output = broken business logic. | ⬜ TODO |
| Q3 | **Compile loop does not exist** | `phases/p05_frontend/` — `tsc --noEmit` + `vite build` errors not fed back to LLM | Wire: build → catch errors → LLM fix call → rebuild, up to 3 rounds. This alone addresses the "30% import failure" reason LLMs were removed from p04a. The fix for unreliable LLM output is a feedback loop, not templates. | ⬜ TODO |
| Q4 | **Screenshot → revision loop skipped in autonomous mode** | `phases/p05_frontend/domain_assembler.py:468,472` — `if not is_autonomous` guard | In autonomous mode, gate-2 screenshot-and-revise is entirely skipped. The infrastructure exists (`apply_gate2_revisions` in `preview.py`). Wire it to run automatically (2 rounds) in autonomous mode with a VLM design rubric. | ⬜ TODO |
| Q5 | **Quality critic scores Python only — frontend unscored** | `core/quality/dimension_scorer.py` — uses `ast.parse` throughout, no TS/TSX handling | Extend to TS/TSX using real tools: `tsc --noEmit`, `eslint`, `axe-core` for a11y. The thing users judge (the frontend) currently has zero quality measurement. | ⬜ TODO |
| Q6 | **Domain intelligence is lookup tables, not AI** | `phases/p05_frontend/prompts.py:11,31,167` — `DOMAIN_STAT_LABELS`, `DOMAIN_COLOR_HINTS`, `DOMAIN_COMPONENT_DESC` | These canned labels and palettes are the reason "vet clinic" and "sneaker marketplace" generate identical apps with different nouns. Replace with LLM-generated domain briefs keyed to the user's actual prompt. | ⬜ TODO |
| Q7 | **`confidence=1.0` hardcoded regardless of actual result** | `phases/p05_frontend/task_agent.py:459` | Derive confidence from: build pass/fail, tsc error count, % of files that fell back to templates, test pass rate. Make it a real signal. | ⬜ TODO |
| Q8 | **No "template debt" tracking per run** | No run metadata field for LLM-authored vs template-stamped % | Add `template_debt_pct` to run metadata. Track it as a KPI so raising LLM coverage is measurable. | ⬜ TODO |
| Q9 | **Silent model degradation at run level** | No run-level flag when codegen falls back to Ollama or Nova Lite | Add `model_used` and `degraded: true/false` to run metadata and surface it in the dashboard. Users deserve to know their app was built by a smaller model. | ⬜ TODO |
| Q10 | **Empty tables and placeholder stats in generated UIs** | `phases/p05_frontend/` seed data path | Guarantee L3/L4 seed data is visible on every generated page. Have the LLM generate domain-plausible seed content, not generic "Lorem ipsum" placeholders. | ⬜ TODO |
| Q11 | **No opinionated design system** | `phases/p05_frontend/prompts.py:167` — 20 hand-mapped Tailwind palette hints | Replace with one real design system (tokens + shadcn/radix-quality components, typography scale, dark mode), then let LLM theme it per brand. | ⬜ TODO |
| Q12 | **No benchmark harness** | No existing test for "does this prompt produce a competitive app?" | Run ~10 fixed prompts weekly through the pipeline. Score with VLM rubric + build pass rate. Diff against competitor output. Cannot beat Lovable/v0/Bolt without measuring against them. | ⬜ TODO |

---

## CATEGORY 4 — ARCHITECTURE / TECH DEBT

| ID | Item | File / Location | Action | STATUS |
|----|------|----------------|--------|--------|
| A1 | **`core/services/run_app_service.py:53`** — `core` imports `gateway` | See C3 | Fix the inversion. `core` must not depend on `gateway`. | ⬜ TODO |
| A2 | **1,028 function-scoped imports** | Concentrated in `phases/` task agents | Incremental cleanup. Not circular-import-forced — just a habit. Move to module top. 1,028 instances remain (down from 1,694). | ⬜ TODO |
| A3 | **5 files at the 600-line limit** | `p07b_self_healing/task_agent.py` (600 exact), `p05_frontend/helpers.py` (599), `core/sandbox/manager.py` (599), `p08_cicd/task_agent.py` (598), `p02b_domain_ir/ir_extractor.py` (593) | Any addition to these files will violate CLAUDE.md. Flag before next touch; split if any new code is needed. | ⬜ TODO |
| A4 | **`tests/test_integration_pipeline.py` (661 lines) and `tests/test_factory.py` (653 lines)** | `tests/` | Both exceed 600-line rule without pre-approval. Split into focused test modules. | ✅ DONE 2eb4b51 |
| A5 | **pgvector (M6)** | `core/models.py:244–253` — `ArtifactEmbedding.embedding` stored as JSON | `CREATE EXTENSION vector` on Postgres + migration to alter column to `VECTOR(1536)` + pgvector SQLAlchemy adapter. Semantic retrieval is currently O(n) cosine scan in Python. | ⬜ TODO |
| A6 | **`billing/` is 21 lines, `billing_impl.py` is elsewhere** | `core/billing/` (21 lines) vs `core/billing_impl.py` | Confusing split. Consolidate or make the separation explicit. | ⬜ TODO |
| A7 | **`pipeline.py` alongside `factory_pipeline.py`** | `orchestrator/` | Naming creates ambiguity. Clarify which is canonical or remove the other. | ⬜ TODO |
| A8 | **~50 INACTIVE_PHASE_DIRS still on disk** | `orchestrator/phase_sequence.py:30–55` — all listed as inactive | These are still called by stage supervisors so they are not dead, but the naming is misleading. Rename the constant or add a comment explaining they are a library, not a sequence. | ⬜ TODO |

---

## CATEGORY 5 — HYGIENE (repo cleanup)

| ID | Item | File / Location | Action | STATUS |
|----|------|----------------|--------|--------|
| H1 | **106 PNGs at repo root** | `/Users/apple/Desktop/aether_os/*.png` | Move to `docs/assets/` or delete working screenshots. First thing anyone opening the repo sees. | ✅ DONE 86754de |
| H2 | **`graphify-out/` at root** | `/Users/apple/Desktop/aether_os/graphify-out/` | Move or delete. | ✅ DONE 7998f09 |
| H3 | **`vkatos_deploy/` at root** | `/Users/apple/Desktop/aether_os/vkatos_deploy/` | Move or delete. | ✅ DONE 7321902 |
| H4 | **21 stale Claude worktrees** | `/Users/apple/Desktop/aether_os/.claude/worktrees/` | `git worktree prune` — removes them. Each is a full codebase copy (~150–200 MB total wasted). Do before VPS deploy. | ✅ DONE 229169c |
| H5 | **DD document is 6 weeks stale** | `AETHEROS_ACQUISITION_DUE_DILIGENCE.md` | Regenerate from measured numbers: 808 Python files, 639 test functions, 852 commits, 12 stages, 53 routers, 88 components, 808 source files. Remove credentials (see S3). | ✅ DONE 4cadf4e |

---

## CATEGORY 6 — DOCUMENTATION

| ID | Item | Location | Action | STATUS |
|----|------|----------|--------|--------|
| D1 | **DD doc claims "20-phase pipeline"** | `AETHEROS_ACQUISITION_DUE_DILIGENCE.md` | Correct to "12 stages wrapping ~50 phase agent libraries." | ✅ DONE 4cadf4e |
| D2 | **DD doc claims 392 Python files, ~65k lines, 258 tests, 240 commits** | Same doc | All materially understated. Update to measured values. | ✅ DONE 4cadf4e |
| D3 | **`main.py` banner: "Tests: 153 passing"** | `main.py:110` | Update (same as C4 above). | ✅ DONE e3a87d0 |
| D4 | **AUDIT_OUTPUT_QUALITY.md: "30s router timeout" claim** | Doc only | No 30s timeout exists in `core/llm/client.py`. Remove or correct. | ⬜ TODO |
| D5 | **AUDIT_OUTPUT_QUALITY.md: "~100 PNGs at repo root"** | Doc only | Correct — there are 106 PNGs. Minor. | ⬜ TODO |

---

## CATEGORY 7 — OPEN / DEFERRED (known, not new)

| ID | Item | Notes | STATUS |
|----|------|-------|--------|
| OD1 | **M9 — 1,028 function-scoped imports** | Down from 1,694. Incremental; no single session fix. | ⏳ DEFERRED |
| OD2 | **M6 — pgvector** | Requires PostgreSQL pgvector extension on server. Listed as A5 above. | ⏳ DEFERRED |
| OD3 | **`ProjectView.jsx` — 2,233 lines** | Pre-existing; panels already extracted. No active split plan. | ⏳ DEFERRED |
| OD4 | **VPS deploy** | Blocked by payment. Unblocks when payment restored. Full checklist in RUNBOOK. | ⏳ WAITING ON HUMAN |

---

## Summary Count

| Category | Items | Est. effort |
|----------|-------|-------------|
| S — Security | 4 | 1 day |
| P — Production blockers | 5 | 1 day (after payment fix) |
| C — Code defects | 8 | 3–5 days |
| Q — Output quality | 12 | 5–7 weeks (the core engineering program) |
| A — Architecture/debt | 8 | 2–3 weeks (incremental) |
| H — Hygiene | 5 | 2–4 hours |
| D — Documentation | 5 | 2–4 hours |
| OD — Open/deferred | 4 | TBD |
| **Total** | **51** | |

**Critical path to sale-ready:**
1. S1–S4 (security/secrets) — must be first, before any code-room access
2. P3 (fix Anthropic payment) — instant quality jump, near-zero engineering
3. C1, C2, C7 (npm gate + failing tests) — days of work
4. Q1–Q5 (core quality program) — 5–7 weeks
5. H1–H5, D1–D5 (cleanup + docs) — one day
