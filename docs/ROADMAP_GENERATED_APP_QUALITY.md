# Roadmap: quality of generated apps (KAN-176, KAN-188, KAN-178)

Status of what the pipeline produces today, and what is left. Written for a buyer taking over the work. Items marked
"needs a model key" cannot be proven offline: they need a staging stack with a real model (KAN-78) and a paid run.

## What exists today

| Area | State | Where |
|---|---|---|
| Entity pages, dashboard, portal home | Model-written, template fallback | `phases/p05_frontend/llm_page_writer.py`, `domain_assembler.py`, `task_agent.py` |
| Design brief (palette, fonts, radius, density, widget text) | Model-written once per run, validated (`#RRGGBB` only), falls back to the token system on no model or bad answer | `phases/p05_frontend/design_brief.py`, fixtures `tests/fixtures/design_briefs/`, test `tests/test_r3_design_brief.py` |
| Domain lookup tables (`DOMAIN_STAT_LABELS`, `DOMAIN_COLOR_HINTS`, `DOMAIN_COMPONENT_DESC`) | Removed; stat labels come from the entity itself | `phases/p05_frontend/prompts.py` |
| Design tokens | 21 fixed token sets (colour, font, radius, shadow, gradient); no type scale | `phases/p05_frontend/design_system.py` |
| Missing UI primitives | Imports of `components/ui/*` or other local modules that the model did not write are generated (PR #34) | `phases/p05_frontend/missing_modules.py`, `ui_primitives.py`, `tests/test_p05_missing_modules.py` |
| Login, layouts, router shell, landing, 404 | Fixed templates (a wrong shell breaks the whole app, so they are not model-written) | `phases/p05_frontend/code_writer_parts/part07.py` (login), `part03.py`/`part04.py`/`part12.py` (layouts) |
| `template_debt_pct` | Counts pages and also the shell surfaces; the surfaces are listed in `frontend_meta.json` as `template_surfaces` | `domain_assembler.py` (`template_surfaces`), `task_agent.py` |
| Placeholder images | `picsum.photos` removed from the generators; no domain images are generated | `phases/` (no match) |
| Seed records | Model-written (`get_seed_py`) | `phases/p04a_backend_codegen/crud_generator_seed.py` |
| Frontend scoring | pattern checks plus real tsc/eslint/axe findings when a tool report is passed | `core/quality/dimension_scorer_frontend.py`, `frontend_tools.py`, `dimension_critic.py` |
| Real build of generated frontend | CI job `generated-npm-build` | `.github/workflows/ci.yml`, KAN-180 |
| Quality regression gate | Golden fixtures scored with the critic, compared with a stored baseline; blocks CI on a drop over 0.02 | `scripts/ci/quality_gate.py`, `tests/fixtures/quality_golden/`, `benchmarks/quality_baseline.json`, `tests/test_quality_gate.py` |
| Benchmark harness | 10 golden prompts through a live API; weekly workflow runs it when `AETHEROS_BENCH_URL` and `AETHEROS_BENCH_TOKEN` are set, and always runs the offline gate | `scripts/benchmark_harness.py`, `benchmarks/prompts/`, `.github/workflows/weekly-benchmark.yml` |

## What remains

1. **Model-written login, layout and router shell.** Needs writers and prompts for `App.tsx`, `LoginPage` and the layouts, plus
   validation fitted to them (the shell must keep every route and the auth guard; login must keep the auth calls), and a real npm
   build of the result. Needs a model key.
2. **Real design system.** Replace the 21 token sets with one token system (type scale included) and a component library
   (shadcn/radix). Today only the primitives that generated code imports are stubbed in.
3. **Domain-relevant images.** Generated or sourced assets keyed to the product; currently none.
4. **Two-prompts acceptance.** Two different prompts must give visibly different layout and palette with a real model. Proven only with a fake
   model and fixtures. Needs a model key.
5. **Benchmark results.** `benchmarks/results/` is empty until the owner sets the two secrets on a staging stack with a model key. The acceptance
   (results for all 10 prompts, two consecutive weeks) follows from the weekly workflow. Not yet built, because they need paid models: the VLM
   rubric (screenshots scored by a vision model) and the competitor baseline (same prompts through other generators).
6. **Backend scorer is weak.** `core/quality/dimension_scorer.py` gives the fixture `tests/fixtures/quality_golden/weak_router.py` 0.93
   although it has `eval`, `os.system` and a hard-coded password: the scorers do not detect `eval` and shell calls (nor bare `except`).
   The gate pins today's scores, so improving the scorer means raising the baseline with `python scripts/ci/quality_gate.py --write-baseline`.
7. **Hollow frontend checks outside the critic.** `phases/p06_review_security/critique_integration.py` calls the critic without a tool report,
   so p06 scores frontend files by patterns only. Running tsc/eslint a second time there is a cost decision.
8. **s06 gate.** Failing unit tests deliberately do not block (s07 healing repairs them); this is disclosed in the stage result `gate` field and
   `stage_summary`. The dashboard does not show those fields yet.
9. **Mocked tests.** Parts of the suite mock the model and the sandbox; an end-to-end run with a real model is the missing proof (see 5).
