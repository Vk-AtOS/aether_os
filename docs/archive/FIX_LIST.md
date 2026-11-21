> **HISTORICAL RECORD. Audit dated 2026-07-20. Superseded.** All numbers and findings below are as of that date, not today. Current state lives in Jira project KAN (owner register KAN-204) and in `SALE_READINESS.md` (measured numbers at commit `e5c23fd`, 15 Nov 2026). The checkboxes below were not updated after this date and do not show current status. Item 1 (history purge) is NOT done: pending owner approval (KAN-175).

# AetherOS — Master Fix List
**Compiled:** 2026-07-20 · Sources: AUDIT_OUTPUT_QUALITY.md + DUE_DILIGENCE_AUDIT.md
Ordered by priority. One commit per item (per CLAUDE.md). Effort: S = hours, M = 1–3 days, L = 1+ week.

---

## P0 — Security & Trust (do before anything else; deal-killers if a buyer finds them first)

- [ ] **1. Purge `token.txt` (JWT) from git history** — retrievable at commit `cf06c57`. Run `git filter-repo`, force-push, invalidate the token. Flagged in June, still present. *(S)*
- [ ] **2. Rotate every secret in `.env`** — AWS access key/secret/bearer token, admin password, `AETHER_SECRET_KEY` (JWT signing), `AETHER_ONE_ZT_SECRET` (HMAC). Treat all as exposed. *(S)*
- [ ] **3. Scrub `AETHEROS_ACQUISITION_DUE_DILIGENCE.md`** — remove live demo credentials and VPS IP from header; regenerate all stale numbers (claims 392 files/65k lines/258 tests/240 commits; reality 748 files/~143.8k lines/584 test fns/852 commits). *(S)*
- [ ] **4. Remove VPS IP from CLAUDE.md and launch/ docs** — replace with env var or placeholder. *(S)*

## P1 — The Model Problem (cheapest quality jump in the project)

- [ ] **5. Fix the Bedrock payment instrument / add a working frontier-model key** — `.env` shows Anthropic blocked by `INVALID_PAYMENT_INSTRUMENT`; production runs on Amazon Nova Pro/Lite + Llama-3.3. Wire Anthropic API (or fixed Bedrock Claude) as primary. *(S — admin, not engineering)*
- [ ] **6. Kill silent model degradation** — `core/llm/client.py:87`: `PRIMARY_LLM` defaults to `"ollama"`. Make model tier an explicit per-run requirement; fail loudly or queue instead of silently dropping to local models; flag any codegen call that lands on a fallback tier in run metadata. *(M)*
- [ ] **7. Raise token/time budgets** — `p04b_business_logic/task_agent.py:244` (`max_tokens=3000`), router timeouts (now in `core/model_router_providers.py`; the 30s figure was wrong), `PHASE_TIMEOUT_SECONDS=180` ("one LLM call per phase"). *(S)*
- [ ] **8. Fix the 3 failing model-router tests** — `tests/test_model_router.py`: provider-selection/fallback logic (`test_router_uses_anthropic_when_key_present`, `test_router_skips_anthropic_falls_back_to_gemini`, `test_fallback_count_increments_on_chain_advance`). The subsystem that picks the codegen model must have green tests. *(M)*

## P2 — Honest Gates (stop shipping failures as successes)

- [ ] **9. Fail s04 gate on npm build failure** — `phases/p05_frontend/task_agent.py:453-457`: build errors currently only logged, phase returns `success=True`. *(S)*
- [ ] **10. Stop hardcoding `confidence=1.0`** — same file, line 457. Derive from build result, tsc errors, test pass rate, template-fallback count. *(S)*
- [ ] **11. Strengthen the s04 gate** — `stages/s04_frontend/supervisor.py`: currently passes if `index.html` or `App.tsx` exists. Require a clean production build. *(S)*
- [ ] **12. Surface template-fallback usage ("template debt")** — every `except → logger.warning → canned fallback` (p04b, p05 helpers, p07b) must also record to run metadata; report % LLM-authored vs template-stamped per run. *(M)*
- [ ] **13. Decide council strictness** — `COUNCIL_ENABLED=true` but `COUNCIL_STRICT_MODE=false` means DeliveryCouncil/PreFlightCouncil never block anything. Either enforce or stop presenting them as gates. *(S)*

## P3 — Output Quality Core (the 5–7 week program; the actual product fix)

- [ ] **14. Compile-error feedback loop** — run `tsc --noEmit` + `vite build`, feed errors back to the LLM, bounded at 3 rounds. This is the correct fix for the "30% import failure rate" that caused LLM removal from p04a. *(M)*
- [ ] **15. LLM-first UI authorship** — `phases/p05_frontend/`: templates keep writing configs/auth/api-client/router shell; a frontier model writes all pages, dashboard, components, and copy from Domain IR + API contract + user prompt. Retire the 62 fixed generators in `code_writer.py` (5,822 lines) as the primary path. *(L)*
- [ ] **16. Autonomous screenshot → critique → revise loop** — wire existing `preview.py` (Playwright screenshots) + `apply_gate2_revisions` (LLM revision) into a loop that fires without human Gate-2 feedback; VLM scores against a design rubric (hierarchy, spacing, contrast, emptiness, genericness); 2 rounds. *(M–L)*
- [ ] **17. Seed data visible in the UI** — guarantee L3/L4 seed data renders on every generated page; LLM-generated, domain-plausible content instead of empty tables and placeholder stats. *(M)*
- [ ] **18. One opinionated design system** — real tokens, shadcn/radix-quality components, typography scale, dark mode; replace the 20 hand-mapped Tailwind palette hints (`DOMAIN_COLOR_HINTS`); LLM themes it per brand. *(L)*
- [ ] **19. Score the frontend for real** — extend the dimension critic (`core/quality/dimension_scorer.py`, currently Python-only regex) to TS/TSX using eslint, tsc, and axe-core. *(M)*
- [ ] **20. Re-enable LLM business logic properly** — p04b workflow/rules generation with adequate budgets + the compile loop, instead of 3k-token one-shots with silent canned fallbacks. *(M)*

## P4 — Architecture & Repo Cleanup (value protection for diligence)

- [ ] **21. Delete the ~50 dead phase directories** — everything in `INACTIVE_PHASE_DIRS` (`orchestrator/phase_sequence.py`) that is absorbed/dead but still on disk. *(M)*
- [ ] **22. Merge duplicate/parallel modules** — `pipeline.py` vs `factory_pipeline.py`; 4 `knowledge_graph*` files; `billing/` (21 lines) vs `billing_impl.py`; `model_router` vs `model_router_providers`. *(M)*
- [ ] **23. Make enterprise output opt-in** — s10 currently pushes IAM, billing metering, feature flags, SRE agents into every generated app; default off, flag on. Less generated surface = fewer breakages = better perceived quality. *(M)*
- [ ] **24. Clean repo root** — ~100 screenshots/PNGs, console captures, Gmail captures, `graphify-out/`, `vkatos_deploy/` → move to `docs/assets/` or delete. *(S)*
- [ ] **25. Split or pre-approve over-limit test files** — `tests/test_integration_pipeline.py` (661) and `tests/test_factory.py` (653) exceed the 600-line rule and aren't on the CLAUDE.md approved list. *(S)*
- [ ] **26. Align docs with measured reality** — README/ARCHITECTURE/launch docs must match actual counts and actual generation architecture ("LLM-powered" claims vs template engine). Buyers diff claims against code. *(M)*

## P5 — Proof & Sale Assets (what actually moves the price)

- [ ] **27. Benchmark harness** — 10–20 golden prompts run weekly; scored on build pass, test pass, Lighthouse, axe, VLM design rubric; competitor outputs (Lovable/v0/Bolt) as baseline. Reproducible by a buyer. *(L)*
- [ ] **28. The gallery** — 20 live generated apps across wildly different domains, each with the prompt that produced it. This is the pitch deck, demo, and tech proof in one artifact. *(L — mostly compute + curation, after P3)*
- [ ] **29. Fresh due-diligence doc** — regenerate from the audits + benchmark results once P0–P3 are done; every claim traceable to a measurement. *(M)*

---

## Suggested sequence

| Window | Items | Outcome |
|---|---|---|
| Days 1–3 | 1–4 (security), 5 (payment), 7, 9–11, 25 | Trust debt cleared, honest gates, frontier model live |
| Week 1–2 | 6, 8, 12–14 | No silent degradation; compile loop working |
| Weeks 2–5 | 15–20 | LLM-first output, visual critique loop, real frontend scoring |
| Weeks 5–7 | 21–24, 26, 27 | Clean architecture, benchmark harness running |
| Weeks 7–9 | 28, 29 | Gallery + regenerated DD doc = sale-ready package |

**Rules of engagement (per CLAUDE.md):** one commit per item, root cause in every commit message, no VPS deploy without smoke_test.sh, no deploy without user confirmation.
