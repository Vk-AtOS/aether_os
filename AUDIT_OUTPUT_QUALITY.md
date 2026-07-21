# AetherOS Output-Quality Audit — 2026-07-20

Goal: explain why builds complete but output quality is unsatisfactory, and what to change to beat Lovable/v0/Bolt-class competitors. All findings verified directly in source.

---

## Root Cause (the one-sentence version)

**AetherOS is a template-stamping machine with an LLM garnish. Competitors are LLM-first with agentic feedback loops. The output ceiling is fixed by your templates, so every app looks like the same CRUD skeleton no matter what the user asks for.**

---

## Findings (grounded in code)

### F1 — Generation is almost entirely deterministic templates
- `phases/p04a_backend_codegen/task_agent.py:3-4` — *"All structural files are generated deterministically (no LLM calls in this phase). LLM is intentionally excluded to eliminate the 30% relative-import failure rate."*
- `phases/p05_frontend/code_writer.py` — 5,822 lines, 62 fixed f-string generators (`_generate_dashboard`, `_generate_entity_page`, `_generate_data_table`, …). Every generated app gets the same DataTable + CRUD modal + stat-card dashboard.
- The **only** LLM-generated UI is one optional `DomainWidget` (`task_agent.py:355-367`) with a hardcoded fallback. The run metadata literally records `"used_llm": domain_widget_generated` — one boolean for one widget.
- "Domain intelligence" is lookup tables: `DOMAIN_STAT_LABELS`, `DOMAIN_COLOR_HINTS`, `DOMAIN_COMPONENT_DESC` in `prompts.py`/`helpers.py`. Canned labels, canned Tailwind palettes, canned widget descriptions. The user's actual request barely influences the UI.

**Consequence:** two different prompts ("build a vet clinic manager" vs "build a sneaker resale marketplace") produce nearly identical apps with different nouns. That is exactly the "output isn't satisfactory" symptom.

### F2 — Default LLM is local Ollama; degradation is silent
- `core/llm/client.py:87` — `PRIMARY_LLM` defaults to `"ollama"`; prompt style drops to `"minimal"` for local models.
- Fallback chain: Anthropic → Gemini → Ollama. If keys are missing/rate-limited, codegen silently drops to a small local model with no run-level flag.
- Models pinned to `claude-sonnet-4-6` / `claude-haiku-4-5` with 30s router timeout (Anthropic tier; Gemini 45s, Ollama 90s); business-logic generation now at `max_tokens=12000` (`p04b_business_logic/task_agent.py:244`; was 3000 when this audit was written).

### F3 — Every LLM failure silently downgrades to canned code
Pattern repeated across p04b, p05, p07b: `except → logger.warning → use fallback template`. The delivered app quietly degrades and nothing in the result tells anyone.

### F4 — Confidence and gates are theater
- `p05_frontend/task_agent.py:453-457` — npm build failure is only `logger.error`; the phase still returns `success=True, confidence=1.0`.
- Frontend stage gate: *"passes if frontend_output_path contains at least an index.html or App.tsx"* (`stages/s04_frontend/supervisor.py`).
- `stages/s05_quality` dimension critic scores **only `.py` files** with regex heuristics (`core/quality/dimension_scorer.py`). The frontend — the thing the user judges — has zero quality scoring.
- Testing stage is non-critical; perf/a11y/E2E deferred; failures never block (`stages/s06_testing/supervisor.py`).

### F5 — No agentic iteration loop
Generation is one-shot per file. There is no loop of: generate → `tsc`/`vite build` → feed errors back to LLM → fix → screenshot → critique → polish. The screenshot infrastructure exists (`p05_frontend/preview.py`, Playwright) and an LLM revision function exists (`apply_gate2_revisions`) — but the revision loop only fires on **human** Gate-2 feedback, never autonomously. This loop is the entire quality advantage of Lovable/v0/Bolt.

### F6 — Self-healing heals toward templates
`stages/s07_healing` — attempt 1 is LLM repair, attempts 2-3 are "deterministic fallbacks," i.e. failures converge back to canned code. Good for uptime, bad for quality.

### F7 — Hygiene (secondary)
- 0 screenshots/PNGs at repo root (deleted in H1 cleanup session; previously ~100).
- 33 test files vs ~800 source files.
- Several files at/over the 600-line rule (CLAUDE.md requires flagging): `code_writer.py` (5,822 — pre-approved), `factory_pipeline.py` (1,223 — pre-approved), plus `tests/test_integration_pipeline.py` (661) and `tests/test_factory.py` (653) not on the pre-approved list.

---

## Recommendations (priority order)

### P0 — Invert templates vs LLM (the big lever)
1. **Templates become the contract, LLM writes the product.** Keep deterministic codegen for what it's good at — build config, auth, API client, router shell, backend structure (your backend determinism is actually a *strength*; competitors ship broken backends). But every user-visible surface (pages, dashboard, components, landing page, copy) should be written per-app by a frontier model, given: Domain IR + API contract + a strict design system + the user's raw prompt.
2. **Kill the silent Ollama fallback for codegen.** Model tier is a run requirement: fail loudly or queue, never degrade silently. Route UI generation to your strongest model; raise `max_tokens` far beyond 3000; allow multi-file generation per call.
3. **Close the compile loop.** `tsc --noEmit` + `vite build` errors go back into the LLM (bounded, e.g. 3 rounds) until clean. Today build failures don't even affect `success`. This alone fixes the p04a "30% import failure" reason LLMs were removed — the fix for unreliable LLM output is a feedback loop, not templates.

### P1 — Evaluate what users actually see
4. **Autonomous visual critique loop.** You already build, serve, and screenshot the app. Add: screenshot every route → VLM scores against a design rubric (hierarchy, spacing, contrast, emptiness, genericness, brand fit) → feed critique into `apply_gate2_revisions` automatically in autonomous mode → re-screenshot. 2 rounds. This is the single most direct path to "looks better than the giants."
5. **Score the frontend for real.** Extend the dimension critic to TS/TSX using real tools (eslint, tsc, axe-core) instead of Python-only regex. Make the s04 gate require a passing production build, not the existence of App.tsx.
6. **Real seed data in the UI.** Empty tables and placeholder stats are what make generated apps feel fake. Guarantee L3/L4 seed data is visible on every generated page; have the LLM generate domain-plausible seed content.
7. **One opinionated, modern design system** (tokens + shadcn/radix-quality components, real typography scale, dark mode) instead of 20 hand-mapped Tailwind palette hints — then let the LLM theme it per brand.

### P2 — Honest metrics and a benchmark loop
8. **Stop hard-coding `confidence=1.0`.** Derive it from build result, tsc errors, test pass rate, and % of files that fell back to templates.
9. **Track "template debt" per run:** % LLM-authored vs template-stamped content. Make raising it a KPI.
10. **Golden-set benchmarking:** run ~10 fixed prompts weekly through the pipeline, score with the VLM rubric + build pass rate, and diff against competitor outputs for the same prompts. You cannot beat the giants without measuring against them.

### Quick wins (this week)
- Set `PRIMARY_LLM` explicitly and alert when any codegen call lands on Ollama.
- Make npm build failure fail the s04 gate.
- Wire the existing screenshot → `apply_gate2_revisions` pair into an autonomous loop (most of the code already exists).
- Raise `max_tokens` on p04b calls (now 12000; was 3000 when this audit was written).

---

## What NOT to change
- Deterministic backend scaffolding, checkpointing/resume, DAG waves, the 12-stage supervisor structure, the self-healing probe layers — these are solid infrastructure and better than most competitors' reliability story. The problem is confined to *what gets generated* and *what gets measured*, not the pipeline machinery.
