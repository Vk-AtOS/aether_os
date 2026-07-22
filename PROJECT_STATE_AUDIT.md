# AetherOS — Project State Audit (Post-Fix Verification)
**Date:** 2026-07-22 · **HEAD:** 91e6200 · **Method:** line-level read of every new module, execution-path trace of the full generation chain, independent test runs

This is the "are the loops actually connected" audit. Every claim below was verified in source, not taken from session reports.

---

## 1. Where the project stands

All 51 items from plans2.md are closed. The delta items from the master history are closed (Sonnet's audit wrongly marked ABAC and domain-pack wiring as open — both were fixed July 10–11 in commits `3e6bee7` and `5bbcefc`). Sessions 1–4 verified commit-by-commit. Docs are truthful, secrets scrubbed from working tree and history, repo hygiene clean, 4/4 E2E smoke tests pass, 27/27 model-router tests pass, subset suites green in an independent environment (full 647-test run verified by the session's own 924s run).

**Engineering completion: ~85%.** What remains is three newly discovered wiring defects (below), one small leftover (C8), the human-side items, and then proof (benchmark + gallery).

## 2. What is genuinely wired end-to-end (verified by execution trace)

- **LLM-first entity pages are the primary path, not garnish.** `domain_assembler.assemble_domain_pages()` calls `write_entity_page_llm()` first in *both* the IR and non-IR branches; the 62 template generators are now the fallback. Debt counters (`llm_count`/`template_count`) feed `template_debt_pct` in run metadata. The prompt includes the user's raw request, typed fields, filtered API routes, FK relationship hints, and design tokens. Real.
- **Compile loop is wired and consumed.** `run_build_loop()` (tsc + vite → LLM find/replace patches → ≤3 rounds, early-bail on zero progress) runs in Step 6; its `success` becomes the phase's `success`, its `tsc_errors` feeds the confidence formula (`build*0.6 + tsc*0.3 + (1-debt)*0.1`), and the s04 gate fails on `success=False`. The module even ships a self-check. Real.
- **The autonomous critique loop fires.** `run_gate2_preview()` in autonomous mode: screenshot → critique → revise → re-screenshot → critique → revise (2 rounds). Real machinery — but see defect W1.
- **Backend depth is there:** ABAC `require_role()` guards generated per-action from the p02c permission model; domain-pack constraints (HIPAA PHI annotation, `Numeric(12,2)` for money domains) wired into schema_builder; council reviews crud/models/schemas/auth, not just main.py; FK fields emit `fk-select` with fetch logic.

## 3. New defects found (the vertical-depth gaps)

### W1 — The "visual" critique loop is blind (HIGH)
`preview.py:vlm_rubric_critique()` base64-encodes the screenshot **and never sends it**. The code's own comment admits it: *"text-only critique — inject img_b64 into messages when vision model confirmed available."* The LLM is asked to score a screenshot it cannot see, so both critique rounds produce generic guesses, not visual feedback. The loop runs; the eye is missing. Fix: route through the existing `_call_bedrock_vision` / a vision-capable model (~20 lines). Until then, the flagship "screenshot → critique → revise" feature is decorative.

### W2 — Import alias mismatch will break every LLM-generated page (HIGH)
`llm_page_writer` **mandates** imports from `'@/components/ui/*'` (and helpers.py's portal prompt does the same), but the generated `vite.config.ts` and `tsconfig.json` define **no `@` path alias**. Every LLM-authored page should fail module resolution at tsc/vite, forcing build_loop to spend its 3 rounds rewriting import paths via find/replace — fragile, token-burning, and likely to end in `success=False` on entity-heavy apps. Classic cross-agent wiring bug (two modules written in different sessions, never integration-tested together). Fix: add `resolve.alias` + tsconfig `paths` to the templates (~10 lines).

### W3 — The brain is still Nova (BLOCKER, human-side, known)
`.env`: `PRIMARY_LLM=bedrock`, `ANTHROPIC_API_KEY` empty. All the new LLM-first machinery amplifies whatever model sits behind it — currently Amazon Nova Pro/Lite + Llama-3.3. Also note: `degraded` in run metadata treats `bedrock` as non-degraded, so the flag will never fire in the current config even though quality is degraded relative to frontier models.

### W4 — Ordering: Gate-2 screenshots a pre-build_loop app (MEDIUM)
The preview/critique loop (Step 5) runs **before** the compile-fix loop (Step 6). If LLM pages have compile errors (guaranteed under W2), the Gate-2 screenshot shows a broken or stale build, and the critique loop revises against the wrong artifact. Move build_loop before the preview, or rebuild before screenshotting.

### W5 — Sequential page generation vs the watchdog (MEDIUM)
Entity pages generate one LLM call at a time (`await` in a loop, ≤120s each). A 12-entity ERP app can burn 20+ minutes against the 25-minute phase watchdog, which then silently skips remaining pages. Use bounded concurrency (`asyncio.gather` with a semaphore of 3–4).

### W6 — LLM-first coverage is entity pages only (MEDIUM)
Dashboard, layouts, customer portal, landing page, and login are still template-generated. `template_debt_pct` counts only entity pages, so it overstates LLM coverage of the whole app. Honest metric fix + gradual expansion of LLM authorship to Dashboard and portal next.

### W7 — Small leftovers (LOW)
C8 (lazy `orchestrator.events` imports in model_router) remains open despite plans2.md marking it done. `vlm_rubric_critique` caps at `max_tokens=300` and `apply_gate2_revisions` only touches 3 candidate files + customer pages — narrow revision surface. `task_type="ui_critique"` should be confirmed as a registered routing type.

## 4. Verdict — "will plain requirements produce the desired output?"

**Today, on this config: no.** Three things stand between the current state and desired output: W3 (Nova writes the pages), W2 (the pages likely don't compile without burning the repair loop), and W1 (the polish loop can't see). None are architecture problems — W1+W2 are ~30 lines total, W3 is a payment fix.

**After those three: the architecture is genuinely competitive.** The chain — prompt → 4-pass IR extraction → deterministic backend with ABAC + domain constraints → LLM-authored pages with design tokens → compile-fix loop → sighted critique loop → self-healing probes → honest gates and confidence — is the right shape, and it's a shape Lovable/v0/Bolt don't fully have (they lack the deterministic backend + healing + delivery pipeline). At that point output quality becomes an empirical question, and the benchmark harness exists to answer it. My honest expectation: first benchmark runs will land *below* the giants on visual polish (their design systems have had years of tuning) but *above* on "app actually works end-to-end" — and the gap closes through rubric iteration, which the loops now make possible.

## 5. Layer grades (post-fix)

| Layer | Grade | Note |
|---|---|---|
| Orchestrator / pipeline | A− | DAG waves, checkpoints, hooks alive, honest gates |
| Backend codegen | A− | Deterministic + ABAC + domain packs + council coverage |
| Frontend generation | B− | Correctly LLM-first, but W1/W2/W4/W5/W6 cap it |
| Verification loops | B | Compile loop real; visual loop blind (W1) |
| Model layer | D | Config-crippled (W3); fine code, wrong engine |
| Tests | B | 647 green incl. E2E smoke; pipeline-path coverage still thin |
| Docs / hygiene / history | A− | Truthful, scrubbed, disciplined commits |

## 6. Recommended next session (small, surgical)

1. W2 — add `@` alias to vite.config + tsconfig templates (one commit)
2. W1 — send the screenshot bytes to a vision-capable call (one commit)
3. W4 — move build_loop before Gate-2 preview (one commit)
4. W5 — bounded-concurrency page generation (one commit)
5. C8 + W7 nits (one commit)
Then: human items (payment, rotation, force-push, VPS), then one real benchmark run — that run, not any audit, is the moment you know what you have.
