> **HISTORICAL RECORD. Audit dated 2026-07-20. Superseded.** All numbers and findings below are as of that date (about 748 Python files, 852 commits). Current state is in Jira project KAN (owner register KAN-204) and in `SALE_READINESS.md`, which has measured numbers at commit `e5c23fd` (15 Nov 2026: 1141 tracked Python files, 1237 commits). Correction to section 10 below: the "purge git history" priority is NOT done. The rewrite is pending owner approval (KAN-175); rotation is tracked in KAN-173. The Python line count in this audit (~143,800) is also not comparable to the current 181935.

# AetherOS — Independent Due-Diligence Audit
**Date:** 2026-07-20 · **Auditor:** Claude (full-codebase pass) · **Scope:** all first-party code, config, git history, docs, tests

Method: every subsystem inventoried; generation path, orchestrator, quality gates, LLM stack, and config read line-by-line; core/gateway/dashboard/tests audited by module with targeted deep reads; all 748 Python files syntax-validated; test suite executed in sandbox; git history inspected. Figures below are measured, not taken from existing docs.

---

## 1. Measured Inventory (vs. what the docs claim)

| Metric | AETHEROS_ACQUISITION_DUE_DILIGENCE.md claims | Measured today |
|---|---|---|
| Python files | 392 | 748 (excl. caches/vendor) |
| Lines of production Python | ~65,000 | ~143,800 |
| Tests | 258 | 584 test functions, 33 files |
| Pipeline | "20-phase" | 12 stages wrapping ~50 phase dirs |
| Commits | 240 | 852 |
| Bare except clauses | "none" | none (verified — the single grep hit is a few-shot *negative example* string in `prompt_compiler.py`) |
| Hardcoded credentials in code | "none" | none found in source (verified) |

The existing DD document is ~6 weeks stale and materially understates the codebase. It also **publishes the live demo credentials and VPS IP in its header** — it cannot be handed to a buyer as-is.

## 2. The Headline Finding: the product is running on crippled models

`.env` (present in the working folder, not git-tracked — good):

- `PRIMARY_LLM=bedrock`; `ANTHROPIC_API_KEY` deliberately empty.
- Comment in file: *"Anthropic models on Bedrock are blocked on this account by INVALID_PAYMENT_INSTRUMENT. Using Amazon Nova."*
- Active model chain: **Amazon Nova Pro / Nova Lite / Llama-3.3-70B → Ollama local**.
- `PHASE_TIMEOUT_SECONDS=180` with the comment *"each phase makes at most ONE LLM call now"*.

So the production system generates apps with mid-tier models, one LLM call per phase, on top of a template engine. The code's advertised chain (Anthropic → Gemini → Ollama, `core/llm/client.py`) is dead in production config. **The single biggest output-quality lever in the entire project is fixing a payment instrument.** This corroborates and deepens the finding in AUDIT_OUTPUT_QUALITY.md.

## 3. Generation Core (read line-by-line — see AUDIT_OUTPUT_QUALITY.md for full detail)

- Backend codegen: deliberately zero LLM calls (`p04a/task_agent.py:3-4`).
- Frontend: 5,822-line template file, 62 generators; one optional LLM widget.
- npm build failure → still `success=True, confidence=1.0` (`p05/task_agent.py:453-457`).
- Quality critic scores only `.py` files with regex; frontend unscored.
- Screenshot + LLM-revision machinery exists but only fires on human feedback.
- DeliveryCouncil / PreFlightCouncil (`core/council/council.py`): real LLM review gates, but `COUNCIL_STRICT_MODE=false` — **council verdicts never block anything** in the shipped config.

## 4. Core Subsystems — real or scaffold?

Verdict per module (lines measured, heads/key paths read):

- **Real and substantial:** orchestrator (DAG waves, checkpoint/resume, message bus, control signals — the best code in the repo); approval/decision engine (1,603); memory (1,165); compliance (1,028); guardian watchdog/snapshot/recovery (1,285); domain_packs (2,920); plugins registry (1,723); services (1,873); sandbox manager (808); 54 Alembic migrations.
- **Real but thin:** learning (287), decisions (300), capacity_planner (326), security (232), intelligence (541), cell_architecture (530), identity/zero-trust (91 — HMAC tickets, more gesture than enforcement).
- **Honest about what they are:** knowledge_graph (817 across 4 files — a JSON dict-graph, docstring says so plainly); chaos_engineering (435 — deterministic LitmusChaos YAML templates, no LLM, says so).
- **Misleading layout:** `billing/` (21 lines) vs `billing_impl.py` elsewhere; 3+ knowledge_graph files; `pipeline.py` alongside `factory_pipeline.py`; ~50 INACTIVE_PHASE_DIRS still on disk.

Overall: **not vaporware.** Most modules do what their docstrings say. The problem is breadth-over-depth and that many subsystems are wired to never block (strict mode off, gates non-critical), so their existence doesn't translate into output quality.

## 5. Gateway & Dashboard

- Gateway: 53 routers, ~15,250 lines. Spot-check of auth coverage: routers lacking `Depends` are the expected public set (health, metrics, SPA, legal, token refresh); `/metrics` correctly 401s without its API key. No obvious unauthenticated business endpoints found in sampling. CLAUDE.md's 400-line router rule appears respected post-refactor.
- Dashboard: real React/Vite app — 88 JSX components, ~22,400 lines, contexts, settings panels, error boundaries. Competent internal tool.

## 6. Tests — executed

- All 748 Python files parse clean (`ast.parse`: 0 errors).
- Sandbox run: `test_core` + `test_quality_metrics`: **53/53 passed**. `test_phases` + `test_model_router` + `tests/unit`: **95 passed, 3 failed**.
- The 3 failures are in **model-router provider-selection/fallback logic** — the exact subsystem that decides which LLM generates code. Failing router tests in a product whose whole value is routed LLM calls is a red flag a buyer's engineer will find in hour one.
- Coverage surface: 584 test functions vs ~800 modules — thin; pipeline treats test failures as non-blocking.
- Two test files exceed the 600-line rule without pre-approval: `test_integration_pipeline.py` (661), `test_factory.py` (653).

## 7. Security & Secrets

- **`token.txt` (a JWT) is in git history at commit `cf06c57` and still retrievable — confirmed by extraction.** The old DD doc flagged this in June; it was never purged. Must run `git filter-repo` before any code-room access.
- `.env` in the working folder carries live AWS keys, admin password, JWT signing secret, zero-trust HMAC secret. Not tracked, but sitting next to a DD doc containing demo creds + server IP. Rotate everything before diligence; scrub the DD doc.
- Source code itself: clean — no hardcoded secrets, no bare excepts, structured logging discipline is genuinely followed.
- CLAUDE.md embeds the VPS IP; launch/ contains marketing docs with claims that must match measured reality.

## 8. Git & Engineering Culture

852 commits, disciplined conventional messages with root-cause style (`fix(V31): …`), evidence of systematic session-based fixes and real refactors (3,317-line router reduced; 50 phases consolidated to 12 stages). This history is an asset — it reads like a maintained project, not a code dump.

## 9. Repo Hygiene

~100 screenshots/PNGs at root (sessions' working artifacts), `graphify-out/`, `vkatos_deploy/`, console captures, Gmail screenshots. Cosmetic but the first thing anyone opening the repo sees. One hour of cleanup, large first-impression payoff.

---

## 10. Verdict

**Acquisition-readiness today: 5.5/10** (the June doc's 7.4 was generous even then, and it predates the codebase doubling).

What a buyer is actually looking at:

1. **Infrastructure: genuinely good** — orchestration, self-healing, migrations, multi-tenant gateway, dashboard, git discipline. Better reliability story than most AI-builder startups.
2. **Product output: currently uncompetitive** — template-stamped apps generated by Nova Lite/Llama with one LLM call per phase and no gate that can fail. This is fully explained, and fully fixable, by the two audits combined.
3. **Honesty debt: the deal-killer if unfixed** — stale DD doc with credentials in it, JWT in git history flagged six weeks ago and still there, "quality gates" that never block, `confidence=1.0` hardcoded. None are hard to fix; all are fatal to trust if a buyer finds them first.

**Priority order to become sale-ready:** (1) purge git history + rotate all secrets + scrub/regenerate the DD doc from measured numbers; (2) fix the payment instrument / wire a real frontier-model key — instant quality jump for near-zero engineering; (3) execute the AUDIT_OUTPUT_QUALITY.md fix list (gates that fail, compile loop, LLM-first UI, visual critique loop); (4) fix the 3 failing router tests; (5) cut dead phase dirs and root clutter; (6) build the benchmark harness + 20-app gallery as the sales asset.

Items 1, 2, 4, 5 are days. Item 3 is the 5–7 week program already scoped. Item 6 rides on top of it.
