# Confluence corrections (KAN-172 and KAN-56)

Date: 15 Nov 2026. Nobody edited Confluence. This file lists what the lead should change, page by page.

## Code used

| Repo | Path | Branch | Commit |
| --- | --- | --- | --- |
| AetherOS | /Users/apple/Desktop/wt3/a_docs/aether_os | r3/a_docs (off r2/int) | e5c23fd |
| Velaris | /Users/apple/Desktop/wt2/int/velaris_knackforge | r2/int | b8ebe7f |

## Method

- Pages were read with the Atlassian read tools (markdown, full). Nothing was created, edited or commented on in Confluence or Jira.
- Part 1 (KAN-172): three pages never fully verified, and six pages that may lack the line "Verified against source 14 Nov 2026". Each statement was compared with the code as it is today.
- Part 2 (KAN-56): independent review of a sample of "Agent: X" pages. See "Part 2" below for the sample rule and the totals.
- Where I could not check a statement I say "not verified" and why.
- "Claims checked" counts separate factual statements (a table row counts as one claim). A claim is "wrong" when the code contradicts it, "partly wrong" when part of it is true and part is not or is no longer true.
- The rule for the new verification line: add "Verified against source 15 Nov 2026 (branch r2/int)" only to a page where every statement was checked. Page by page below, I say whether that is the case. For pages that were fixed in code, the page text must be corrected first, then the line added.
- Many problems below are statements that were true on 14 Nov and became stale when rounds 1 and 2 fixed the code (for example the AI core "open gaps"). They are still wrong on the page today.
- Tests I ran (read-only, with a temporary data folder, no files left in either repo): `velaris/tests/test_dept_legal_compliance_stubs.py`, `test_governance_kernel.py`, `test_layer32_eacpe.py`, `test_layer5_neuralgov.py` (27 passed), plus `test_aicore_a_crk.py` and `test_aicore_a_csg.py` (50 passed with the four above).

## Part 1 summary

| Page | Verified line present | Claims checked | Wrong | Partly wrong | Add 15 Nov line after fixes |
| --- | --- | --- | --- | --- | --- |
| Phase: patterns | no | 14 | 1 | 1 | not yet: I did not read the code strings line by line (see page section) |
| Phase: gateway | no | 9 | 7 | 0 | no, the page should become a "removed" note |
| Dept: AI Core (_ai_core) | no | 155 (133 table rows, 22 statements) | 10 | 5 | not yet: the rows were checked against each agent's docstring and manifest, not against every code body |
| Agent: CRK_INTENT | no | 16 | 1 | 2 | yes, after the 3 fixes |
| Agent: COHERENCE_SYNC_CORE | no | 16 | 1 | 0 | yes, after the 1 fix |
| Dept: Legal and Compliance | no (has "re-checked against the source on 14 Nov 2026" in a paragraph, not as a last line) | 17 | 5 | 1 | yes, after the fixes |
| Phase: p05c_desktop | no | 16 | 3 | 1 | yes, after the fixes, except the one "not verified" item |
| Roadmap and Work Plan | has a different line, see section | 10 | 0 | 1 | no: KAN-8 code claims and "no real model key" not verified |
| AetherOS Pipeline Phases | no | 1 | 0 | 0 | only as an index page, see section |

---

## Phase: patterns (id 133020)

Verdict: verified line present: no. Last line of the page: "- `orchestrator/phase_hooks.py:315` reads `accumulated_context["domain_ir"]`, which is never set; it works only because it falls back to reading the IR file." Claims checked 14, wrong 1, partly wrong 1.

Limit of this check: `phases/patterns/` is 5,886 lines (20 files). I read `__init__.py` fully (240 lines) and every place that calls into the library (`pattern_injector.py`, `phase_hooks.py`, `domain_pages.py`, `task_agent.py`). The other files are mostly large code strings for generated apps. I read their headers, imports and which names they export, not every line of the embedded code. What the page says the code strings contain (WebSocket rooms, Stripe, upload, RBAC, multi-tenant, marketplace, ERP approval, agentic AI, IoT, social graph) matches the module names and docstrings but I did not audit the embedded code itself. "Verified only by unit tests and fakes" was not verified (I did not look for tests of the library).

Checked and correct (no change): about 5,900 lines (5,886); no `task_agent.py`; docstring says the model selects patterns, selection is keyword code (`__init__.py:5`, `:210`); `Pattern` record and six factories (`__init__.py:42-166`); substring matching on lower-cased IR text (`:200`, `:210`); trigger words "ws", "live", "role", "admin", "post", "like", "file", "device" (`:86`, `:97`, `:119`, `:132`, `:146`); inject target folders (`:55-60`); p04a calls `detect_active_patterns` and `inject_patterns` (`task_agent.py:64`, `:284-285`); the hook runs after `s03_backend` (`phase_hooks.py:281`, `:314`); `domain_ir` never set and read at `phase_hooks.py:315`; p04a writes `billing_router.py` (`pattern_injector.py:132`) and patches `main.py` (`task_agent.py:297`), the selector writes `src/routers/billing.py` (`__init__.py:109`); every injection path logs a warning and goes on (`__init__.py:213`, `:226`, `:238`, `pattern_injector.py:170`, `phase_hooks.py:336`); `domain_pages.py` imports `frontend_patterns_c`, `_d`, `_e` (`:175`, `:192`, `:208`, `:217`).

| # | Statement on the page | What the code shows | Replace with |
| --- | --- | --- | --- |
| 1 | "and five `frontend_patterns_*.py` files" | `phases/patterns/` has six content files, `frontend_patterns_a.py`, `_b.py`, `_b2.py`, `_c.py`, `_d.py`, `_e.py`, plus `frontend_patterns.py`, which re-exports them (`frontend_patterns.py:4-9`, `:13-31`) | "and six `frontend_patterns_*.py` files (a, b, b2, c, d, e), re-exported by `frontend_patterns.py`" |
| 2 | "Output: Python or TSX files written to the backend (`src/routers/ws.py`, `billing.py`, `middleware/rbac.py` and similar)" (partly wrong) | The Python files go to the backend folder (`__init__.py:62-67`). The TSX pages are not written by the backend injectors. `phases/p05_frontend/domain_pages.py:179-180` writes `FeedPage.tsx`, `FollowersPage.tsx` and the other pages into the frontend pages folder | "Output: Python files written to the backend (`src/routers/ws.py`, `billing.py`, `middleware/rbac.py` and similar). TSX pages are written separately by p05_frontend (`domain_pages.py`) into the frontend pages folder." |

Additional note (not wrong, missing): `Pattern.inject` falls back to the project folder itself when none of the three backend folders exist (`__init__.py:60`). The page says "the first existing folder of" the three. Suggested addition: "or the project folder if none exists".

Also not on the page but useful: `patch_main_py` only adds routes for websocket, stripe, marketplace and erp_approval (`task_agent.py:297-304`). The multi_tenant, agentic_ai, social_graph and iot_timeseries files that p04a writes are not wired into `main.py` by that call. Not verified whether another step wires them.

---

## Phase: gateway (id 231613)

Verdict: verified line present: no. Last line of the page: "- Error responses return `str(e)` (`routes.py:50, 68, 84, 99`)." Claims checked 9, wrong 7, partly wrong 0.

The folder `phases/gateway/` no longer exists. It was deleted in commit d2094f7 (15 Nov 2026, message starts "fix(p02c): permission-model validator ...", KAN-98); `git show d2094f7 --stat` lists `phases/gateway/client_portal/__init__.py`, `index.html` and `routes.py` as deleted. Nothing in the repo imports it: a search for `phases.gateway` and `phases/gateway` finds only documentation under `docs/codebase_map/sections/` (`01_orchestration.md:2,64,275,373` and `10_core_platform_governance.md:218`), which describe the old state. The whole page is therefore stale. The live portal is `gateway/client_portal/routes.py` (373 lines, checked) with `provenance.py` (75 lines).

Recommendation for the lead: replace the whole page body with the text in row 1, or archive the page. Either way the page should not describe the deleted router as present.

What the old description said about the live router is now also wrong for this page's purpose: the live router does have access control (`gateway/client_portal/routes.py:14` imports `portal_access`; every route uses `Depends(_portal_auth)` at `:128`, `:219`, `:243`, `:269`, `:288`, `:354`) and `approve` records the approval (`:253`, `portal_access.record_approval`).

| # | Statement on the page | What the code shows | Replace with |
| --- | --- | --- | --- |
| 1 | "`phases/gateway` is not a pipeline phase. It holds one folder, `client_portal`, with a 99-line FastAPI router and an `index.html`. It is an older, smaller copy of the client portal that now lives in `/gateway/client_portal/routes.py` (373 lines). The platform mounts the top-level copy, so this folder is dead code." | The folder was deleted in d2094f7. `gateway/client_portal/routes.py` is 373 lines (correct). | "`phases/gateway` no longer exists. It held an older copy of the client portal router (99 lines, an `index.html`, no access check, an approve route that recorded nothing). It was removed on 15 Nov 2026 (commit d2094f7) because nothing imported it. The live client portal is `gateway/client_portal/routes.py` (373 lines), mounted in `gateway/api.py:307`." |
| 2 | "The live router is registered in `gateway/api.py:295` as `aether_os.gateway.client_portal.routes`" | Now `gateway/api.py:307` | "`gateway/api.py:307`" |
| 3 | "None. No stage supervisor imports it and there is no `task_agent.py`. The only mention is a docstring in `gateway/routers/portal_admin_router.py`." | Folder is gone. The docstring of `portal_admin_router.py` now says the client routes are in `gateway/client_portal/routes.py`. Only old docs mention `phases/gateway`. | Delete the "Position in the pipeline" section. |
| 4 | "Routes under the prefix `/portal`: `GET /{project_id}/status` ..." (the whole Inputs and outputs section) | Describes deleted code | Delete the section. |
| 5 | "The current top-level router adds portal access control through `core/identity.portal_access`, provenance, a ZIP download and request models with limits; none of that exists in this copy." | True of the live router (`routes.py:14`, `:288`, `:354`). The copy is gone. | Move this fact to the client portal page if one exists. |
| 6 | "Handlers wrap work in a broad `except Exception` and return HTTP 500 with the exception text, which can expose internal paths and messages to the caller." and "Error responses return `str(e)` (`routes.py:50, 68, 84, 99`)." | Deleted code. In the live router the ZIP error returns a fixed text (`routes.py:339`). Not verified for the other live handlers (`:214`, `:235`, `:254`, `:281` catch `Exception`; I did not read what they return). | Delete both statements from this page. |
| 7 | "If it were mounted it would be unauthenticated ... anyone who knows a project id could read phase outputs and write feedback." and "`approve_phase` only logs and returns 'Approval recorded...'" | Deleted code; the live router authenticates and records approvals. | Delete. |

---

## Dept: AI Core (_ai_core) (id 131091)

Verdict: verified line present: no. Last line of the page: "## Child pages" (a heading; the last text line is the row "| [Agent: VPSE\_SCENARIO](...) | Safe-formula what-if recomputation of outcomes. |"). Claims checked 155 (133 table rows plus 22 statements), wrong 10, partly wrong 5.

Code folder: `/Users/apple/Desktop/wt2/int/velaris_knackforge/departments/_ai_core/` (133 agent folders; each has `main.py` and `manifest.json`).

What I checked: every table row against the agent's module docstring and manifest description (read for all 133), the allow-list, tests, and the "open gaps" against the code of the named agents. I ran the inventory classifier (`velaris/agents/inventory.py`) over all 133 `main.py` files. I read the full code of ORCHESTRIX, SCHEDULON, STRATEGOS, SELF_HISTORY, VCAS_CORE, MCD, AGENT_EVOLUTION, CRK_INTENT and COHERENCE_SYNC_CORE. For the other agents I compared the page row with the docstring, which the 14 Nov doc round wrote from the code; a row can still differ from a code body I did not read.

Checked and correct: "It has 133 agents" (133 folders); four allow-listed agents with the names and methods given, at `velaris/api/allowlist.py:125-131` (also `:126`, `:129`) and no other `_ai_core` agent is in the allow-list (script check); CONVERGENCE_BRIDGE fronts ORCHESTRIX, COHERENCE_SYNC_CORE, REGISTRY (`departments/operations/CONVERGENCE_BRIDGE/main.py:4`); SAGE and NIRVANA files exist and mention STRATEGOS/CSM_CORE and SELF_CORRECTION_ENGINE (file-level check only); GCK fronts GLOBAL_STATE_MAP; PRIME runs health checks on VIGILIS, CUSTOS, PRAETOR (`PRIME/main.py:73`); alias agents AEIL, ASEL, CORE_CONVERGENCE, CRK, FSCL, GCK are 9-line wrappers (classifier says not_implemented); every other table row not listed below matches its docstring.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | "Agent: REGISTRY: five manifests (PERSONALITY\_MOD, SELF\_CONSISTENCY, SELF\_HISTORY, SELF\_IDENTITY, SOUL\_CORE\_EXT) have no entrypoint, so health\_all reports them as errors; 114 of the 133 agents have no manifest.json and are not discoverable by it." | All 133 agents have `manifest.json` and all 133 have an `entrypoint` (script check; for example `SELF_HISTORY/manifest.json` has `"entrypoint": "main.py:SELF_HISTORYAgent"`). Fixed by commit 90cfeb1 ("REGISTRY builds agents from every manifest"). | Delete the bullet. |
| 2 | "Agent: ORCHESTRIX: parallel\_groups can place a task in a batch before its dependency." | Batches are now computed by dependency depth: `ORCHESTRIX/main.py:58-66` (docstring `:3-6`). Fixed in 90cfeb1. | Delete the bullet. |
| 3 | "Agent: SCHEDULON: crashes with zero workers." | `distribute_load` returns `[]` for a worker count below 1 or not an int: `SCHEDULON/main.py:36-37`. | Delete the bullet. |
| 4 | "Agent: STRATEGOS: crashes or inverts ranking when risk is -1 or below." | `evaluate_strategy` raises `ValueError` for a negative or non-finite risk: `STRATEGOS/main.py:37-39`. | Delete the bullet. |
| 5 | "Agent: VCAS\_CORE: decide drops the pending task before the audit write, losing it if the trace write fails." | The decision is recorded first; if the trace cannot be written the task stays pending and the reply is `audit_failed`: `VCAS_CORE/main.py:81-87`. | Delete the bullet. |
| 6 | "Agent: SELF\_DIRECTED\_TASKER: does not detect cycles among non-root tasks." | `_has_cycle` at `SELF_DIRECTED_TASKER/main.py:35`, used at `:69`. | Delete the bullet. |
| 7 | "Agent: SELF\_HISTORY: placeholder, nothing persisted." | The agent persists up to 1000 events to `<VELARIS_DATA>/agents/SELF_HISTORY/events.json`: `SELF_HISTORY/main.py:1-9`, `:20`, `:31-33`. | Delete the bullet. |
| 8 | Table row: "[Agent: SELF\_HISTORY] ... In-memory event list (placeholder)." | Same as 7. | "Small persisted event log (newest 1000 events, owner-only file)." |
| 9 | Table row: "[Agent: ORCHESTRIX] ... Topological sort and parallel batches of tasks (batching has a bug)." | Same as 2. | "Topological sort of tasks and parallel batches by dependency depth." |
| 10 | "Placeholders that still need a real implementation: SELF\_HISTORY, AGENT\_EVOLUTION, MCD, MULTILINGUAL\_BRAIN." | SELF_HISTORY is no longer a placeholder (row 7). The other three are still thin: `AGENT_EVOLUTION/main.py:1-6`, `MCD/main.py:1-8`, `MULTILINGUAL_BRAIN` (word-for-word lookup, 43 lines). | "Thin placeholders that still need a real implementation: AGENT\_EVOLUTION, MCD, MULTILINGUAL\_BRAIN." |
| 11 | Table row: "[Agent: LOCAL\_BIOMETRICS\_INTERFACE] ... In-memory store of hashed biometric strings and match check." | State is on disk: "State: <VELARIS_DATA>/agents/LOCAL_BIOMETRICS_INTERFACE/templates.json (hashes only, owner-only, shared by workers)" (`LOCAL_BIOMETRICS_INTERFACE/main.py:12`); salted scrypt hashes. | "Store of salted hashes of biometric strings kept in an owner-only file, and an exact-match check." |
| 12 | Table row: "[Agent: AGENT\_EVOLUTION] ... In-memory metrics stub that returns a fixed suggestion." (partly wrong) | `propose` returns "tune-params" when more than 5 metrics were recorded for the agent and "none" otherwise; it never reads the metric values: `AGENT_EVOLUTION/main.py:1-6`. | "In-memory metrics stub: proposes \"tune-params\" after more than 5 records, otherwise \"none\"." |
| 13 | Table row: "[Agent: NEURAL\_MESH] ... Records a message note in shared memory; does not deliver it." (partly wrong) | `route` adds the message to the receiver's inbox in MEMORY_FABRIC and `receive(agent)` returns and empties it; only "pushing" to the receiver does not happen: `NEURAL_MESH/main.py:1-9`. | "Message queue between agents backed by MEMORY\_FABRIC: route adds to the receiver's inbox, receive reads and empties it. Nothing is pushed." |
| 14 | "Older v0.1.0 agents (ORCHESTRIX, SCHEDULON, STRATEGOS) are unvalidated." (partly wrong) | STRATEGOS rejects non-numeric, non-finite or negative values (`STRATEGOS/main.py:37-39`); SCHEDULON returns `[]` for a bad worker count (`SCHEDULON/main.py:36`). ORCHESTRIX still has no validation (its docstring `:7-8`). All three still report version 0.1.0. | "Older v0.1.0 agents (ORCHESTRIX, SCHEDULON, STRATEGOS) have only light validation: ORCHESTRIX none, SCHEDULON and STRATEGOS check their numbers." |
| 15 | "The model-driven pieces are few: RECURSIVE\_GOAL\_PLANNER.decompose, SELF\_CONSISTENCY.sample, META\_REASONING\_CORE, MRF\_REFLECT, MODEL\_COUNCIL, AUTONOMOUS\_RESEARCH\_ENGINE and LYRA\_VOICE\_ENGINE" (partly wrong) | These also call a model: CRK_INTENT (fallback when rules tie, `CRK_INTENT/main.py:71-92`), INTENT_SYNTHESIZER (`synthesize(idea, llm)`), MCFE_CLASSIFIER (`classify(text, llm)`), MCFE_CORE (`process(text, llm)`) and LOCAL_EMBEDDING_ENGINE (method "model", through velaris.intel.llm). LYRA_VOICE_ENGINE uses a speech-recognition model (whisper, `LYRA_VOICE_ENGINE/main.py:73`), not a language model. | "The model-driven pieces are RECURSIVE\_GOAL\_PLANNER.decompose, SELF\_CONSISTENCY.sample, META\_REASONING\_CORE, MRF\_REFLECT, MODEL\_COUNCIL, AUTONOMOUS\_RESEARCH\_ENGINE, CRK\_INTENT (fallback), INTENT\_SYNTHESIZER, MCFE\_CLASSIFIER, MCFE\_CORE and LOCAL\_EMBEDDING\_ENGINE. LYRA\_VOICE\_ENGINE uses a speech model, not a language model." |

Count for this page: wrong = rows 1-9 and 11 (10 statements: seven "open gaps" bullets and three table rows); partly wrong = rows 10, 12, 13, 14, 15 (5 statements). Rows 7 and 8 describe the same code change but are separate statements on the page.

---

## Agent: CRK_INTENT (id 98972)

Verdict: verified line present: no. Last line of the page: "- Defect: the accept check `choice not in self.intents` raises TypeError if the model returns an unhashable value for intent (for example a list), so that case escapes as an exception instead of returning `unresolved`. Reproduced the underlying dict-membership error." Claims checked 16, wrong 1, partly wrong 2. Code: `departments/_ai_core/CRK_INTENT/main.py` (93 lines).

Checked and correct: the seven intents; public methods `classify` and `health_check`; intents overridable in the constructor (`:34-37`); 4000 characters limit (`:30`, `:60-61`); guard scan returns `blocked` (`:62-65`); whole-word keyword counting and one clear leader wins with method "rules" (`:44-52`, `:66-70`); model used when passed in or `VELARIS_MODEL` is set (`:38-43`); redacted and wrapped text, JSON reply, `temperature 0`, 50 tokens, purpose `crk_intent` (`:77-85`); statuses `invalid_input`, `blocked`, `not_configured`, `model_error`, `unresolved` (`:56-92`); `intent: None` when not ok; no confidence value is returned.

| # | Statement on the page | What the code shows | Replace with |
| --- | --- | --- | --- |
| 1 | "- Defect: the accept check `choice not in self.intents` raises TypeError if the model returns an unhashable value for intent (for example a list), so that case escapes as an exception instead of returning `unresolved`. Reproduced the underlying dict-membership error." | Fixed. The check is now `if not isinstance(choice, str) or choice not in self.intents` (`CRK_INTENT/main.py:90`), and a test sends `{"intent": ["x"]}` (`velaris/tests/test_kan106_aicore.py:59-65`). | Delete the bullet. |
| 2 | "No agent calls it in the code; tests are `test_layer12_crk.py` and `test_aicore_a_crk.py`, using a fake model." (partly wrong) | The alias agent CRK lists it as a component (`departments/_ai_core/CRK/main.py:4`) and calls it through the delegator (`velaris/agentkit/alias.py:82-91`). A third test file covers it: `test_kan106_aicore.py:59`. It is not in `velaris/api/allowlist.py`. | "Called only through the alias agent CRK (`departments/_ai_core/CRK/main.py:4`), which fronts it, and by tests: `test_layer12_crk.py`, `test_aicore_a_crk.py` and `test_kan106_aicore.py` (fake model). It is not on the HTTP allow-list." |
| 3 | "Custom intents with non-string keyword lists are not validated." (partly wrong) | Keywords are turned into text with `str(w)` before matching (`:44`), so a non-string word is matched as its text. The constructor still only checks that `intents` is a non-empty dict (`:36`); a value that is not a list of words is not checked. | "Custom intents are only checked to be a non-empty dict; keyword lists are not validated (items are converted with str())." |

---

## Agent: COHERENCE_SYNC_CORE (id 131215)

Verdict: verified line present: no. Last line of the page: "- No access control or audit of who reported." Claims checked 16, wrong 1, partly wrong 0. Code: `departments/_ai_core/COHERENCE_SYNC_CORE/main.py` (74 lines).

Checked and correct: methods `report`, `forget`, `check`, `health_check`; SHA-256 digest of the state (`:25-26`); strict majority is the reference, otherwise status `split` with no patches (`:70-72`); patches come from CSG_STATEALIGN (`:73-74`); lagging replicas listed (`:68`); status `ok` or `drift` (`:75-76`); `report` validates name, object and number (`:40-42`); future check with CSG_TEMPORAL, 5 s default skew (`CSG_TEMPORAL/main.py:17`), refused as `clock_skew` (`:43-44`); `stale` (`:48-49`); state file path (`:10`); `no_data` with coherent false (`:62-63`); a non-numeric `max_lag` silently ignored (`:68`); two differing replicas always give a split (`:70`); a stale replica still counts in the vote (no exclusion in `check`); no caller check, no audit (no `check_caller` in the file).

| # | Statement on the page | What the code shows | Replace with |
| --- | --- | --- | --- |
| 1 | "The operations agents HYPERSYNC and CONVERGENCE\_BRIDGE list it as a delegate and import its module, but their `run(method)` looks the method up on the module, which holds only the class, so a delegated call such as `check` raises AttributeError. There is no working production caller." | Fixed in commit a3b0140. The delegator resolves the agent class and calls the method on an instance (`velaris/agentkit/alias.py:82-91`, `resolve_class` at `:28-42`). I ran `HYPERSYNCAgent().run("check")` and it returned `{'status': 'no_data', ..., 'coherent': False}`. HYPERSYNC (`departments/operations/HYPERSYNC/main.py:4`) and CONVERGENCE_BRIDGE (`:4`) are still the only callers besides tests, and neither is on the allow-list. | "The operations agents HYPERSYNC and CONVERGENCE\_BRIDGE list it as a delegate and call it through the alias delegator (`velaris/agentkit/alias.py`); `run("check")` works. No other agent calls it and it is not on the HTTP allow-list." |

---

## Dept: Legal and Compliance (id 131117)

Verdict: verified line present: no. The page has a sentence "Every agent page and this page were re-checked against the source on 14 Nov 2026." inside "How the department is called", but it is not the last line. Last line of the page: "- LEGAL\_INTELLIGENCE\_ENGINE holds no legal content, sources or persistence." Claims checked 17, wrong 5, partly wrong 1. Code: `departments/legal_compliance/` (7 agents, 787 lines in total).

Checked and correct: 7 agents with the names in the table; EACPE_ALIGNMENT calls a model for the principle review (`EACPE_ALIGNMENT/main.py:11-16`); LEGAL_INTELLIGENCE_ENGINE is an in-memory stub (`LEGAL_INTELLIGENCE_ENGINE/main.py:1-8`); none of the seven is in `velaris/api/allowlist.py`; governance writes need the governance_admin role (`POLICY_CONTROLLER/main.py:88`, `:95`, `EACPE_HUMAN_GUARD/main.py:79`, `EACPE_ALIGNMENT/main.py` docstring); Prime refuses `execute` for `set_approvers` and other management methods (`PRIME/main.py:39-44`); policy history is append-only (`POLICY_CONTROLLER/main.py:2-4`); no code outside the department calls them (only a docstring in VIGILIS and the routing table in MCFE_ROUTER mention the names), so "No enforcement points" still holds.

| # | Statement on the page | What the code shows | Replace with |
| --- | --- | --- | --- |
| 1 | "LEGAL\_INTELLIGENCE\_ENGINE has no test." | A test exists: `velaris/tests/test_agents_coverage_a.py:281-282` (`test_LEGAL_INTELLIGENCE_ENGINE_stores_updates_looks_up_and_searches_rules`). | "LEGAL\_INTELLIGENCE\_ENGINE is covered by `test_agents_coverage_a.py`." |
| 2 | "(25 tests, all passing on 14 Nov 2026)" | I ran the four named files today: 27 tests, all pass. | "(27 tests, all passing on 15 Nov 2026)" |
| 3 | "Six of the seven agents are covered by test\_dept\_legal\_compliance\_stubs.py, ..." | Seven of seven have a test once item 1 is counted. | "All seven agents are covered by test\_dept\_legal\_compliance\_stubs.py, test\_governance\_kernel.py, test\_layer32\_eacpe.py, test\_layer5\_neuralgov.py and test\_agents\_coverage\_a.py;" |
| 4 | "- EACPE\_PROTOCOL.define and GOVERNANCE\_ADAPTATION\_LOOP.record/adapt have no caller checks, so protocols can be redefined and override evidence injected by anyone." | `define` needs a governance admin and writes to the trace first (`EACPE_PROTOCOL/main.py:21-25`); `record` and `adapt` call `check_caller(..., roles=GOVERNANCE_ADMINS)` (`GOVERNANCE_ADAPTATION_LOOP/main.py:49`, `:63`). | Delete the bullet. |
| 5 | "- EACPE\_HUMAN\_GUARD.validate can be called by anyone and consumes the approval; exempt lets one admin remove a guarded class." (partly wrong) | `validate` for a guarded class now needs the caller to be the requester (`EACPE_HUMAN_GUARD/main.py:163-176`). The second half is still true: one governance admin can exempt a class (`:75-87`), and the change is audited and refused if the audit write fails (`:83-84`). | "- EACPE\_HUMAN\_GUARD.exempt lets one governance admin remove a guarded class (the change is audited)." |
| 6 | "- GOVERNANCE\_ADAPTATION\_LOOP re-proposes a rejected rule on the next call." | A rejected proposal is not created again until MIN_SAMPLES new outcomes arrive (`GOVERNANCE_ADAPTATION_LOOP/main.py:87-89`). | Delete the bullet. |
| 7 | "Each agent keeps a JSON file under its own agent directory (velaris.agentkit.state) with organisation-scoped data" | Nothing in `departments/legal_compliance/` scopes data by organisation or tenant (a search for organisation, org_id and tenant finds nothing). State files are per agent, not per organisation. | "Each agent keeps a JSON file under its own agent directory (velaris.agentkit.state); the data is not split by organisation;" |

Decision for the lead: the "Overview" sentence "nothing else in the platform calls them yet" is still true.

---

## Phase: p05c_desktop (id 100353)

Verdict: verified line present: no. Last line of the page: "The token is read from `localStorage` but the app has no login screen." (the end of the last bullet under "Gaps and open items"). Claims checked 16, wrong 3, partly wrong 1, not verified 1. Code: `phases/p05c_desktop/` (`task_agent.py` 63 lines, `electron_generator.py` 376 lines, `supervisor_agent.py` 23 lines).

Checked and correct: stage 4 sub-step 3 and the trigger (`stages/s04_frontend/supervisor.py:146-148`, `_should_run_desktop`); listed again in stage 12 (`stages/s12_specialist/supervisor.py:107-108`, key `desktop_output_path`); dependency on p05_frontend (`orchestrator/phase_dag.py:69`); API port fixed at 8000 (`task_agent.py:41`); metadata `desktop_dir` and `entity_count`, confidence 0.85 (`task_agent.py:54-59`); deterministic templates, no model; `main.js` window with `contextIsolation: true` and `nodeIntegration: false`, spawns `python3 -m uvicorn main:app --port`, dev server in development and `dist/index.html` packaged, `get-api-base` over IPC (`electron_generator.py:48-103`); backend run with the user's system Python (`:52-53`); the double `r.json()` read at `:293`, the `/<table>s` URL at `:288`, no `/api` prefix, token from `localStorage` at `:292`, `:304`, no login screen in the generator (no "login" text in the file); skip returns success True (`task_agent.py:27-33`).

Not verified: "Non-critical in the sense of the sub-step wrapper, but a real failure marks the stage as failed (see p05b\_mobile)". I did not trace `_run_sub_phase`.

| # | Statement on the page | What the code shows | Replace with |
| --- | --- | --- | --- |
| 1 | "`phases/p05c_desktop/task_agent.py:36` reads the never-populated `input_data["domain_ir"]` (the orchestrator only sets `domain_ir_path`), so every desktop app has the single placeholder entity `item`." | Fixed in round 2. `task_agent.py:37` calls `get_domain_ir(data)`, which reads `domain_ir` or else the file at `domain_ir_path` (`phases/utils.py:61-80`). The placeholder `item` is used only when the IR has no entities (`task_agent.py:38-40`). | "If the Domain IR has no entities, the app gets one placeholder entity `item` (`task_agent.py:38-40`). The IR is read with `get_domain_ir` (from `domain_ir` or `domain_ir_path`)." |
| 2 | "It knows the backend only by assumption: `main.js` runs `uvicorn main:app` in `resourcesPath/backend`, and `electron-builder.yml` packages `../backend` (relative to the desktop folder) with only `*.py` and `requirements.txt`." | The generator now copies the generated backend into `desktop/backend` (`electron_generator.py:367-375`, skipping caches, env files, databases, keys, venvs, tests), and the builder file says `from: backend` (`:150`), with the same filter `**/*.py` and `requirements.txt` (`:151-154`). The task fails with success False and the issue "no generated backend to bundle into the desktop app" when no backend folder is given (`task_agent.py:45-50`). | "The generator copies the generated backend (`backend_src_dir` or `backend_output_path`) into `desktop/backend`; `electron-builder.yml` packages that folder (`from: backend`) with only `*.py` and `requirements.txt`. `main.js` runs `uvicorn main:app` in `resourcesPath/backend`. Without a generated backend the phase fails." |
| 3 | "No test in `tests/` covers p05c or `electron_generator`; nothing was packaged or launched." | `tests/test_r2_p05_generators.py:11` (builder packages a backend that exists) and `:27` (without a backend the phase fails). Nothing is packaged or launched (still true). | "Two tests cover p05c (`tests/test_r2_p05_generators.py`): the builder file packages a backend that exists, and the phase fails without a backend. Nothing was packaged or launched." |
| 4 | "Generation errors return success False with empty metadata; skip returns success True." and "Writes `p05c_desktop/desktop/`: `main.js`, `preload.js`, ... and `src/components/<Entity>View.jsx` per entity." (partly wrong: incomplete) | A missing backend is a third failure case with an issue text (`task_agent.py:45-50`), and the output now also contains the `desktop/backend/` folder (`electron_generator.py:367-369`). | Add to Failure behaviour: "A missing generated backend returns success False with an issue." Add to outputs: "`desktop/backend/` (a copy of the generated backend)." |

---

## Roadmap and Work Plan (id 100114)

Verdict: verified line present: yes, in other words. Last line of the page: "Verified against the KAN-1 to KAN-10 descriptions and the code on 14 Nov 2026; no inconsistencies." Claims checked 10, wrong 0, partly wrong 1, not verified 3.

Checked and correct: ten epics KAN-1 to KAN-10 in Jira, all "In Progress" (Jira search today); epic titles match the one-line summaries (KAN-4 says "all 346 agents": I counted 346 `departments/*/*/main.py` files); the four dependency sentences are statements about plans, not code.

Not verified: (a) "tests use a fake model, there is no real model key in the repository" (I did not search the repo for keys); (b) KAN-8 code claims "p11 docker build, p08 test runner and p05 screenshot still run on the host; the Docker sandbox backend has never run; rate limits are in memory"; (c) KAN-1 provider list "OmniRoute".

| # | Statement on the page | What the code shows | Replace with |
| --- | --- | --- | --- |
| 1 | "Prime hard bounds (Rs 50,00,000 and 90 days; request lifetime 72 hours)" (partly wrong) | These figures are the proposal in the KAN-10 description. The code today has a ceiling of 500,000 for a single amount (`velaris/agentkit/aicore_b_authz.py:44`, `HARD_CEILING = 500_000.0`) and at most 30 days for a grant (`:45`, `MAX_GRANT_SECONDS = 30 * 86400.0`). The guard approval lifetime is 24 hours (`departments/legal_compliance/EACPE_HUMAN_GUARD/main.py:40`). I found no 72 hour request lifetime in the code. | "Prime hard bounds (the owner is to decide; KAN-10 proposes Rs 50,00,000, 90 days and a 72 hour request lifetime; the code today caps one amount at 500,000 and a grant at 30 days)" |
| 2 | Last line: "Verified against the KAN-1 to KAN-10 descriptions and the code on 14 Nov 2026; no inconsistencies." | "no inconsistencies" is not right while item 1 stands. | After fixing item 1 and checking items (a) to (c) above, replace with "Verified against source 15 Nov 2026 (branch r2/int)." Do not add it before (a) to (c) are checked. |

---

## AetherOS Pipeline Phases (id 98543)

Verdict: verified line present: no. The page is an index page. Its whole text, and last line: "The build pipeline phase by phase: what each phase takes in, what it produces, which modules it calls, and how it fails." Claims checked 1 (the sentence describes the child pages; the list of child pages is a macro the read tool did not return, so I could not see it), wrong 0, partly wrong 0.

No correction needed to the sentence. Recommendation: the page has no facts of its own, so the verified line is only meaningful if it says so. Suggested last line: "Index page. Each child page carries its own verification line." Do not add "Verified against source 15 Nov 2026" here: the 40 plus child phase pages were not checked in this task, only p05c_desktop, patterns and gateway.

---

# Part 2: independent review of the "Agent: X" pages (KAN-56)

## Sample and totals

- Pages found by CQL `space = SD AND type = page AND title ~ "Agent:"`, paged with the cursor (100 per page): 347 results. One result is "Velaris Agent Reference" (id 98526), which is not an agent page (its title contains the word Agent). **Agent page total: 346.** The 346 agents match the 346 `departments/*/*/main.py` folders.
- Sample rule (redo it like this): take the 346 titles starting with "Agent: ", sort them alphabetically ignoring case (Python `sorted(titles, key=str.lower)`), and take every 10th starting at the 5th (positions 5, 15, 25 ... 345). That gives 35 pages, about 10 percent.
- Doubt pages: every agent page whose text contains writer doubt. The CQL combined query (`text ~ "unverified" OR text ~ "not verified" OR text ~ "unclear" OR text ~ "TODO" OR text ~ "could not confirm"`) returned 346 of 346 pages, because Confluence matches "not" and "verified" as separate words and every page says "Verified against source". That set is useless, so I ran each term alone and kept the exact-word ones: `unverified` (10 pages), `TODO` (1), `could not confirm` (3), `unclear` (10). The union is 23 pages (OFFER_LETTERS appears twice). The phrase "not verified" could not be searched as a phrase with this tool.
- Sample plus doubt pages, without duplicates: 55 pages (35 sample + 23 doubt - 3 in both: OVERSIGHT_MONITOR, VMRK, ZOHO_PEOPLE).
- Completed: **39 of 55 pages** (443 claims checked). Not reviewed: 16 pages, listed at the end.
- Counting: a claim is one separate factual statement (a table row, a number, a named caller, a test, a path, a behaviour). On pages with no corrections I checked every statement I could tie to the code. "Wrong" means the code contradicts the statement. "Partly" means part is wrong or out of date. Pages where all claims hold have no table.
- Error rate = (wrong + partly wrong) / claims checked. The wrong-only rate is also shown. A department above 10 percent (on the first measure) needs a redo ticket; the lead opens it.
- Reason for most errors: the pages were verified on 14 Nov 2026 and rounds 1 and 2 fixed many things afterwards (KAN-87 to KAN-106: agents now check callers, persist state, redact notes, use atomic writes). The page text still describes the old defects.

### Error rate by department (reviewed pages only)

| Department (code folder) | Pages reviewed | Claims checked | Wrong | Partly wrong | Wrong only | Wrong plus partly | Redo ticket needed (above 10 percent) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| _ai_core | 15 | 181 | 30 | 12 | 16.6% | 23.2% | yes |
| legal_compliance | 1 | 14 | 0 | 0 | 0.0% | 0.0% | no (only 1 page: low confidence) |
| security | 6 | 63 | 9 | 8 | 14.3% | 27.0% | yes |
| hr | 1 | 15 | 1 | 0 | 6.7% | 6.7% | no (only 1 page: low confidence) |
| it_infrastructure | 2 | 30 | 15 | 2 | 50.0% | 56.7% | yes (only 2 pages: low confidence) |
| finance | 3 | 29 | 7 | 1 | 24.1% | 27.6% | yes |
| project_management | 2 | 22 | 2 | 1 | 9.1% | 13.6% | yes (only 2 pages: low confidence) |
| marketing | 2 | 19 | 4 | 1 | 21.1% | 26.3% | yes (only 2 pages: low confidence) |
| operations | 2 | 18 | 0 | 0 | 0.0% | 0.0% | no (only 2 pages: low confidence) |
| sales | 2 | 20 | 1 | 2 | 5.0% | 15.0% | yes (only 2 pages: low confidence) |
| executive | 1 | 14 | 0 | 0 | 0.0% | 0.0% | no (only 1 page: low confidence) |
| data_knowledge | 1 | 12 | 2 | 2 | 16.7% | 33.3% | yes (only 1 page: low confidence) |
| supply_chain | 1 | 6 | 1 | 1 | 16.7% | 33.3% | yes (only 1 page: low confidence) |
| **All reviewed** | 39 | 443 | 72 | 30 | 16.3% | 23.0% | |

Departments above 10 percent: _ai_core, security, it_infrastructure, finance, project_management, marketing, sales, data_knowledge, supply_chain.

Note on the numbers: pages with many rows (for example OFFLINE_REGISTRY, LOCAL_BIOMETRICS_INTERFACE) carry a lot of weight in small departments. The two pages reviewed in Part 1b (CRK_INTENT, COHERENCE_SYNC_CORE) are not part of these totals.

### Pages reviewed, one line each

| Page | Department | Why in the set | Claims | Wrong | Partly |
| --- | --- | --- | --- | --- | --- |
| Agent: STRATEGOS | _ai_core | sample | 13 | 2 | 0 |
| Agent: VCAS_CORE | _ai_core | sample | 13 | 2 | 1 |
| Agent: LOCAL_BIOMETRICS_INTERFACE | _ai_core | sample | 15 | 10 | 3 |
| Agent: CONTROL_LAYER | _ai_core | sample | 12 | 2 | 1 |
| Agent: ACF_FUSION | _ai_core | sample | 11 | 0 | 1 |
| Agent: ASEL | _ai_core | sample | 11 | 7 | 2 |
| Agent: AUTO_LEARN_CORE | _ai_core | sample | 11 | 0 | 0 |
| Agent: CCSF_RESOLVER | _ai_core | sample | 13 | 0 | 1 |
| Agent: COGNITIVE_LOAD_BALANCER | _ai_core | sample | 11 | 1 | 0 |
| Agent: CRK_CONTEXT | _ai_core | sample | 12 | 2 | 2 |
| Agent: DSS_REPLICATION | _ai_core | sample | 11 | 0 | 0 |
| Agent: MPC_CORE | _ai_core | sample | 10 | 0 | 0 |
| Agent: NEURAL_ALIGNMENT_ENGINE | _ai_core | sample | 13 | 2 | 1 |
| Agent: RCI_CORE | _ai_core | sample | 14 | 1 | 0 |
| Agent: EACPE_ALIGNMENT | legal_compliance | doubt (text 'unclear') | 14 | 0 | 0 |
| Agent: VCAS_ROUTER | _ai_core | doubt (text 'unclear') | 11 | 1 | 0 |
| Agent: HARD_LOCKDOWN_MODE | security | sample | 11 | 2 | 2 |
| Agent: DECISION_FIREWALL | security | doubt (text 'unclear') | 11 | 0 | 0 |
| Agent: SECURE_ACTION_TOKENS | security | sample | 11 | 2 | 2 |
| Agent: THREAT_DETECTION_MESH | security | sample | 10 | 2 | 2 |
| Agent: POLICY_ACKS | hr | sample | 15 | 1 | 0 |
| Agent: ITSM_ENGINE | it_infrastructure | sample | 16 | 4 | 0 |
| Agent: RISKON | finance | sample | 10 | 1 | 0 |
| Agent: INITIATIVE_ENGINE | project_management | sample | 12 | 0 | 1 |
| Agent: VMRK | marketing | sample and doubt (text 'unclear') | 10 | 3 | 1 |
| Agent: FABRICA | operations | sample and doubt (text 'unclear') | 9 | 0 | 0 |
| Agent: FLUXOR | operations | sample | 9 | 0 | 0 |
| Agent: ECONOMIC_INTELLIGENCE_MESH | finance | sample | 10 | 5 | 1 |
| Agent: OVERSIGHT_MONITOR | security | sample and doubt (text 'unclear') | 9 | 0 | 0 |
| Agent: COHORTUS | sales | doubt (text 'unclear') | 9 | 0 | 0 |
| Agent: CREATIVE_HOLODECK | marketing | doubt (text 'unclear') | 9 | 1 | 0 |
| Agent: BUSINESS_DNA | executive | sample | 14 | 0 | 0 |
| Agent: MEMORY_DRIFT_DETECTOR | data_knowledge | sample | 12 | 2 | 2 |
| Agent: OFFLINE_REGISTRY | it_infrastructure | sample | 14 | 11 | 2 |
| Agent: FORMULA | finance | doubt (text 'unclear') | 9 | 1 | 0 |
| Agent: SIMULON | project_management | sample | 10 | 2 | 0 |
| Agent: MACHINE_LIFECYCLE_ENGINE | supply_chain | sample | 6 | 1 | 1 |
| Agent: AGENT_CONTAINMENT_MODES | security | sample | 11 | 3 | 2 |
| Agent: DOMAIN_ADVISOR | sales | sample | 11 | 1 | 2 |

## Agent: STRATEGOS (id 131929)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 13, wrong 2, partly wrong 0. Code: `departments/_ai_core/STRATEGOS/main.py (62 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | No validation: non-numeric values raise ValueError, a non-dict raises AttributeError, and a risk of exactly -1 raises ZeroDivisionError. Negative risk other than -1 inflates scores. | Validated now: a field that is not a number, a non-dict, a non-finite value or a negative risk raises ValueError (STRATEGOS/main.py:34-39). No ZeroDivisionError path. | Failure behaviour: a non-dict, a value that is not a finite number, or a negative risk raises ValueError. Missing numbers default to 0. |
| 2 | **Defect:** evaluate\_strategy divides by `1 + risk` with no guard (main.py:26), so risk = -1 crashes and risk below -1 flips the sign of the score so riskier options rank higher. Risk is not constrained to be non-negative. NaN input would also scramble the sort. | Fixed: risk below 0 and NaN or infinite values are refused (STRATEGOS/main.py:37-39); the comment there names the old bug. | Delete the defect paragraph. Add: "A negative risk or a value that is not finite is refused with ValueError." |

Other statements: Other claims checked and correct: formula, defaults to 0, float() conversion, no state or environment, stable ordering of ties, SAGE names it (operations/SAGE/main.py:4), test file test_strategos.py exists, no other callers found, no authorisation.

## Agent: VCAS_CORE (id 230432)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026 (page earlier cited lines 370-373; the file has 85 lines).". Claims checked 13, wrong 2, partly wrong 1. Code: `departments/_ai_core/VCAS_CORE/main.py (92 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | decide: only the approver PRIME named can decide. It removes the task from pending, writes a `decision` trace entry holding the task digest, approver and note, then on approval executes with that entry's hash; on rejection it just closes. | The trace entry is written first; only then is the task removed from pending (VCAS_CORE/main.py:81-87). If the trace cannot be written the task stays pending and the reply is audit_failed (:85-86). | decide: only the approver PRIME named can decide. It writes a `decision` trace entry holding the task digest, approver and note; if that fails the task stays pending (status audit_failed). Then it removes the task from pending, and on approval executes with that entry's hash; on rejection it just closes. |
| 2 | **Defects:** (1) In decide, the task is popped from pending (main.py:77) before the `decision` trace entry is written (main.py:78-80); trace.append raises if the trace cannot be written, so on a write error the task is lost from pending, no decision is recorded, and the exception escapes (PRIME catches this case, this path does not). | Fixed: the record is written first and a write error is caught (VCAS_CORE/main.py:80-86). | Delete defect (1) and renumber: "**Defect:** the task is removed from pending before execute ..." |
| 3 | and submitting a task id that is already pending silently replaces the stored entry (main.py:53). | Still true, but the line is main.py:56. | (main.py:56) |
| 4 | Verified against source 14 Nov 2026 (page earlier cited lines 370-373; the file has 85 lines). | The file has 92 lines. | Verified against source 15 Nov 2026 (branch r2/int), after the two fixes above. |

Other statements: Defect (2) (task removed from pending before execute, so an approved task is lost if the handler is not registered after a restart) is still true (main.py:87 before the execute at :89-90). Other claims checked and correct: methods, outcomes, submit order router, caller, supervisor, autopilot, pending.json state, not_found/denied/invalid_input replies, no expiry on pending tasks.

## Agent: LOCAL_BIOMETRICS_INTERFACE (id 99052)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 15, wrong 10, partly wrong 3. Code: `departments/_ai_core/LOCAL_BIOMETRICS_INTERFACE/main.py (92 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | is a small in-memory store that enrols a user's biometric strings (finger, face, voice) as hashes | State is on disk: templates.json and throttle.json under <VELARIS_DATA>/agents/LOCAL_BIOMETRICS_INTERFACE/ (main.py:12, :36). | is a small store, kept in an owner-only file, that enrols a user's biometric strings (finger, face, voice) as salted hashes |
| 2 | `update(user, biometrics)` | Signature is update(user, current, biometrics); the current factors must verify first (main.py:73-76). | `update(user, current, biometrics)` (replaces or adds templates once `current` verifies) |
| 3 | `enroll` stores SHA-256 of each factor string under the user. | Each factor is hashed with hash_secret (salted scrypt, per the docstring) (main.py:5, :57). | `enroll` stores a salted scrypt hash of each factor string under the user. |
| 4 | 3. Everything is held in a dict; nothing is written to disk. | JsonState writes templates.json (main.py:36); Throttle writes throttle.json. | 3. Hashes are written to an owner-only file under VELARIS_DATA, shared by workers and kept across restarts. |
| 5 | No dependencies on other modules, no callers, and no tests mention it. | It imports velaris.agentkit.secure, velaris.agentkit.state and velaris.core.access (main.py:20-22). Tests mention it: velaris/tests/test_agents_coverage_c.py and test_kan89_aicore.py. No other agent calls it (not on the allow-list). | Depends on velaris.agentkit.secure (hashing, throttle), velaris.agentkit.state and velaris.core.access. Tests: test_agents_coverage_c.py and test_kan89_aicore.py. No other agent calls it and it is not on the HTTP allow-list. |
| 6 | Wrong types (non-string values, non-dict) raise exceptions instead of returning False. | `_valid` returns False for a non-dict, an empty dict, an unknown factor or a non-string or empty value (main.py:46-49); enroll and verify return False. | Wrong types return False. |
| 7 | No caller check at all: anyone with a reference can enrol a user, overwrite a user's templates with `update`, or list all users. | enroll and update call check_caller: only the user or a security admin may enrol or update (main.py:60, :79; docstring lines 4-5). list_users has no caller check (main.py:86). | Enrol and update need the person themselves or a security admin, and are traced. list_users has no caller check and lists all enrolled names. |
| 8 | It is a toy: it does no matching score (despite the class docstring promising "match scoring"), no sensor handling, and no persistence. | The docstring no longer promises scoring and says it is an exact-match stand-in (main.py:2-14). Persistence exists (see above). No scoring and no sensor handling are still true. | It does exact string matching only, no similarity score and no sensor handling. |
| 9 | `departments/_ai_core/LOCAL_BIOMETRICS_INTERFACE/main.py:42`: factors are compared as unsalted, unkeyed SHA-256 of the raw string and with a plain `!=`; real biometrics are never bit-identical between captures, so exact hashing would not work and a leaked store allows offline guessing. | Hashes are salted scrypt checked with verify_secret (main.py:70). The point that real captures are never identical is still true and is stated in the docstring (main.py:13-14). | Factors are compared as salted scrypt hashes with exact string match; real captures are never bit-identical, so this is a stand-in for a matcher. |
| 10 | `update` (line 46) has no check of the old factor, so enrolment can be silently replaced. | update requires the current factors to verify (main.py:75) and a caller check (main.py:79). | Delete the bullet. |
| 11 | Untested and uncalled; the docstring's "match scoring" is not implemented. | Tested (see above); the docstring no longer says match scoring. | Not called by other agents; tested in test_agents_coverage_c.py and test_kan89_aicore.py. |
| 12 | there is no minimum-factors rule and no attempt limit. | No minimum-factors rule is still true (any non-empty subset). An attempt limit exists: 5 failed verifications in a row lock the user for 15 minutes (docstring lines 7-9, main.py:67-69). | there is no minimum-factors rule. Five failed verifications in a row lock the user for 15 minutes. |
| 13 | `enroll` also accepts an empty dict, creating a user with no factors. | An empty dict is refused (main.py:46-49). | Delete the sentence. |

Other statements: Correct: it reads no sensor; verify is True only when the user exists, at least one factor is presented and all presented factors match; an un-enrolled factor fails; unknown user and empty input fail closed; no minimum-factors rule.

## Agent: CONTROL_LAYER (id 229596)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026". Claims checked 12, wrong 2, partly wrong 1. Code: `departments/_ai_core/CONTROL_LAYER/main.py (49 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Each forwards to a process-wide `ControlService`, created on first use. | service() returns the /control service of the running app when there is one (`shared_service()`), and creates its own only when there is none (main.py:16-23). Fixed by commit 90cfeb1. | Each forwards to the `ControlService` of the running app (`shared_service()`); outside the app it creates one on first use. |
| 2 | but this wrapper builds its process-wide service as `ControlService()` with no llm, gate or flow\_path, a different instance from the one mounted for /control. Which model and which approval gate a run uses through this agent therefore comes from the defaults, not from the app configuration; this was not tested with a live model. | Fixed: the mounted service, with its model and gate, is used (main.py:19-21). A separate ControlService() is created only when no app service exists (main.py:22-23). | Delete the sentence. Keep: "not tested with a live model". |
| 3 | Because the agent and /control use separate service instances, a run started through one is only rebuilt (not shared in memory) when read through the other. | Same fix: inside the app both use the same service (main.py:19-21). | Delete the sentence. |

Other statements: Correct: methods, health_check returns ok plus task count, caller taken only from current_caller and AccessDenied('unauthenticated'), allow-list rules (velaris/api/allowlist.py:131-132: list_tasks, run_state, run_report READ; start_run, undo ACT), test_control_api.py exists, health_check and list_tasks need no caller, kill and approvals not exposed. Not verified: 'Only tasks registered in velaris/control/tasks.py can run' (the service code was not read).

## Agent: ACF_FUSION (id 131391)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 0, partly wrong 1. Code: `departments/_ai_core/ACF_FUSION/main.py (31 lines) and velaris/agentkit/aicore_a_fusion.py`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Equality is by JSON text, so 1 and 1.0 count as a conflict (agentkit/aicore\_a\_fusion.py:55). | Behaviour is as stated (json.dumps of each value, aicore_a_fusion.py:67), but the line number is 67, not 55. | (agentkit/aicore\_a\_fusion.py:67) |

Other statements: Correct: methods; plain data named a and b; output fields; clean_sources rules (unique source name, dict data with string keys, numeric ts, nested objects flattened to dotted names); one distinct value goes to merged, several to conflicts; a field only one source reports is merged; called by ACF_CORE (ACF_CORE/main.py:4,11); tests exist; wrapper-form confusion at main.py:15; lists compared whole, empty objects kept; the reason text repeats the offending value.

## Agent: ASEL (id 132004)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 7, partly wrong 2. Code: `departments/_ai_core/ASEL/main.py (9 lines) and velaris/agentkit/alias.py`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | As written it cannot call any of them. | Fixed in commit a3b0140. ASELAgent is a Delegator (ASEL/main.py:7-9). It loads the class of each of the five agents and calls the method on an instance (alias.py:28-42, :82-91). I ran ASELAgent().run('plan', [...]) and got a real ASEL_PLANNER plan. | As written it passes calls through to the five ASEL agents: run("method") calls the first component that has the method, run("ASEL_PLANNER.plan") picks the component. |
| 2 | It imports the first loadable module from ASEL\_PLANNER, ASEL\_EXECUTOR, ASEL\_ROUTER, ASEL\_STRATEGIST, ASEL\_EVALUATOR and looks up the named attribute on that module. | The delegator builds an instance of every component class once (alias.py:60-75) and calls the named method on it (alias.py:82-91). | It builds one instance of each of the five agents on first use and calls the named method on the first one that has it. |
| 3 | 1. The loader returns on the first import that succeeds, which is always ASEL\_PLANNER, so the other four are never reached. | All five components are loaded (alias.py:66-72); health_check lists them: ['ASEL_EVALUATOR','ASEL_EXECUTOR','ASEL_PLANNER','ASEL_ROUTER','ASEL_STRATEGIST']. | 1. All five agents are loaded; a component that cannot load is named in health_check as failed. |
| 4 | 2. run does `getattr(module, method)`. The ASEL modules define classes ... so those calls raise AttributeError. It is not completely dead: any name the module imported resolves ... | run looks the method up on the instance, skips names starting with an underscore, and raises AttributeError only when no component has it (alias.py:82-91). Calling plan, execute, route, choose, evaluate works. | 2. run calls the method on the first component that has it (a name starting with an underscore is refused). run("COMPONENT.method") picks the component. If no component has the method it raises AttributeError. |
| 5 | 3. health\_check reports ok whenever the module imported, as the module has no health\_check of its own. | health_check is ok only when every component loads, builds and reports ok; otherwise failed or degraded, naming the component (alias.py:5-8 docstring). | 3. health_check is ok only when all five agents load and report ok. |
| 6 | Raises rather than returning a result dict, unlike the real ASEL agents. Reports healthy while unable to do anything. | Calls return the component's own result dict. Second sentence is wrong (see 3). | Delete the second sentence. First sentence: "An unknown method raises AttributeError; otherwise the result is the component's own." |
| 7 | Needs LLM harness: it is a non-working stub. | It works as a pass-through (see above). It adds no behaviour of its own. | Status: alias wrapper that works as a pass-through; it adds no behaviour. |
| 8 | - ASEL/main.py delegation targets modules, not agent instances, so run() is dead (same defect as AEIL). / - Delete it or rewrite it as a real pipeline object like AIIE\_KERNEL. | Fixed (see above). The same fix applies to AEIL and the other aliases. | Delete both bullets. |
| 9 | Nothing calls it. test\_alias\_layers.py only imports it and checks health. | test_aicore_a_asel.py also mentions ASEL (found by name search). Not verified what that test does with the alias. | Nothing in the platform calls it. Tests: test_alias_layers.py and a mention in test_aicore_a_asel.py. |
| 10 | No state; it adds a debug-level stream handler to its logger. | Not found: alias.py has no StreamHandler or addHandler (search). Logger comes from logging.getLogger(self.name). | No state. |

Other statements: Correct: ASEL fronts five agents; the five real agents are tested in test_aicore_a_asel.py and test_layer13_asel.py; a method allow-list would be needed before exposing ASEL_EXECUTOR.execute (a statement about risk, still true: any component method not starting with an underscore is callable through run).

## Agent: AUTO_LEARN_CORE (id 99633)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 0, partly wrong 0. Code: `departments/_ai_core/AUTO_LEARN_CORE/main.py (77 lines)`.

No corrections needed.

Other statements: Every checked claim holds: methods and signatures (main.py:37, :49, :56, wilson_lower :20); success must be a real boolean (:39); stats fields and 95 percent Wilson bound (z = 1.96); sort order lower bound, fewest trials, name (:70-71); no_data plus untried list (:74-76); state file state.json; used by ADAPTIVE_ACTION_ENGINE; tests exist; bad names refused; no authorisation; no decay; the whitespace issue at lines 38, 50, 68 is real (ident strips, stats and best look names up as given).

## Agent: CCSF_RESOLVER (id 99977)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026". Claims checked 13, wrong 0, partly wrong 1. Code: `departments/_ai_core/CCSF_RESOLVER/main.py (83 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Return `resolved` (value, source, reason) and `unresolved` (field, reason, all values). | The resolved entry has the keys value, source and why (main.py:82); unresolved has field, reason and values (:80). | Return `resolved` (value, source, why) and `unresolved` (field, reason, all values). |

Other statements: Correct: signature, conflict shape, the six strategies, validation, latest needs a timestamp on all values and a unique newest (:33-37), majority compares JSON text (:42), max/min refuse non-numbers (:48-49), priority fails when no listed source reported (:56), invalid_input for the whole call (:66-76), status ok or unresolved, called by CCSF_CORE, tests exist, no authorisation, no tracing.

## Agent: COGNITIVE_LOAD_BALANCER (id 98619)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026". Claims checked 11, wrong 1, partly wrong 0. Code: `departments/_ai_core/COGNITIVE_LOAD_BALANCER/main.py (34 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Logging uses a module-level stream handler at DEBUG level. | The module only creates a logger (main.py:15); there is no stream handler and no debug logging in the file. | Delete the sentence (or: "It creates a module logger and logs nothing."). |

Other statements: Correct: class is LoadBalancer; choose logic (main.py:26-32); health_check fixed dict with version; constructor builds LifecycleManager; unknown agents give {'state':'unknown'} (AGENT_LIFECYCLE_MANAGER/main.py:64-66, non-strings treated as unknown); only tests call it (test_aicore_a_ops.py:54); ENGINE creates it and never uses it (ENGINE/main.py:11,39); falls back to the first candidate; no authorisation; stray header comment lines; naming differs from the <NAME>Agent convention.

## Agent: CRK_CONTEXT (id 98876)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026". Claims checked 12, wrong 2, partly wrong 2. Code: `departments/_ai_core/CRK_CONTEXT/main.py (86 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Non-string values (objects, lists) are not scanned or masked, so nested text passes through unscreened. | Fixed: every string at any depth of a dict or list is scanned and masked, up to depth 8; deeper values are refused (main.py:20-46, MAX_DEPTH = 8 at :17). Test: test_kan87_aicore_guards.py. | Strings inside objects and lists are scanned and masked too, to a depth of 8; anything nested deeper is dropped as "too_deep". |
| 2 | - Nested structures are not scanned (see above); this is a real hole if facts come from outside. | Same fix as above. | Delete the bullet. |
| 3 | 2. String values are scanned by `velaris.intel.guard.scan`; if blocked the fact is dropped with the rule names. | Partly out of date: strings inside dicts and lists are scanned too (main.py:31-45). | 2. Every string value, including strings nested in objects and lists (depth up to 8), is scanned by `velaris.intel.guard.scan`; if blocked the fact is dropped with the rule names. |
| 4 | Not called by another agent in the code (CRK\_REASONER takes facts directly). Called by `test_layer12_crk.py` and `test_aicore_a_crk.py`. | The alias agent CRK lists it as a component (departments/_ai_core/CRK/main.py:4). A third test file covers it: test_kan87_aicore_guards.py. | Not called by another agent except through the alias agent CRK (CRK_REASONER takes facts directly). Tests: test_layer12_crk.py, test_aicore_a_crk.py, test_kan87_aicore_guards.py. |

Other statements: Correct: build(facts) and output fields (main.py:85-86); dropped facts without key or value (:63-66); conflict handling keeps the first (:75-78); budget 8000 JSON characters and truncated list (:79-82); no state or environment; non-list input gives invalid_input (:59-60); no authorisation; conflicts detected after redaction; first-come budget order.

## Agent: DSS_REPLICATION (id 230427)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 0, partly wrong 0. Code: `departments/_ai_core/DSS_REPLICATION/main.py (77 lines)`.

No corrections needed.

Other statements: Every checked claim holds: signatures (main.py:37, :57); rendezvous hashing by SHA-256 of key and node (:44-45); one copy per zone first, then fill (:46-51); under_replicated (:52-54); audit lost, repairs, still_short, degraded (:62-77); no state files; stand-alone; tests exist; invalid_input; the duplicate-name defect at line 67 is still present; dead-node zones not considered; no check of factor in audit.

## Agent: MPC_CORE (id 230526)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026 (ran a list-valued record and a missing record: ...)". Claims checked 10, wrong 0, partly wrong 0. Code: `departments/_ai_core/MPC_CORE/main.py (37 lines), MPC_PREPROC, MPC_FUSION`.

No corrections needed.

Other statements: Every checked claim holds: run(sources, redact=False) (main.py:24); source keys; output is the fusion result plus cleaning counts (:36-37; MPC_FUSION returns record, provenance, conflicts, agreement); invalid_input naming the source (:31-32); all-or-nothing; no agent calls it; a list-valued record uses only the first cleaned record (MPC_PREPROC/main.py:93); digit strings up to 9 digits become numbers (MPC_PREPROC/main.py:22-23); no state; no authorisation.

## Agent: NEURAL_ALIGNMENT_ENGINE (id 230881)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026. Confirmed: ...". Claims checked 13, wrong 2, partly wrong 1. Code: `departments/_ai_core/NEURAL_ALIGNMENT_ENGINE/main.py (83 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | None on either call: anyone who can reach `set_objectives` can replace the company's objectives, which changes every later alignment verdict. This should be a restricted, approved action. | set_objectives calls check_caller with roles=GOVERNANCE_ADMINS and refuses anyone else (main.py:60-62). align still has no caller check (it is a read). | `set_objectives` needs the governance admin role (traced). `align` has no caller check. |
| 2 | - `set_objectives` is unauthenticated. | Fixed (main.py:60-62). | Delete the bullet. |
| 3 | Confirmed: unlike Agent: NEURAL\_POLICY\_MESH, no role check (check\_caller / governance admin) guards set\_objectives. | Wrong now: set_objectives is guarded by check_caller with the governance admin role (main.py:19, :60). | Delete the sentence. Keep: "align() accepts caller-supplied objectives, which bypass the stored ones; only dict values are scanned, not keys." |

Other statements: Correct: methods; objective shape; whole-word and phrase matching (main.py:77-79); matches and conflicts; is_aligned rule (:82); state in objectives.json via JsonState; depends on agentkit.state and aicore_b_text.words (it also uses velaris.core.access now); tests exist; no agent calls it; no_objectives and invalid_input replies; keyword-only, synonyms missed, negation not handled; caller-supplied objectives bypass stored ones.

## Agent: RCI_CORE (id 229628)

Verdict: department _ai_core; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026. ...". Claims checked 14, wrong 1, partly wrong 0. Code: `departments/_ai_core/RCI_CORE/main.py (65 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Tests: test\_aicore\_b\_rci, test\_layer23\_rci. Not called by other agents in code. No manifest.json. | RCI_CORE has a manifest.json (departments/_ai_core/RCI_CORE/manifest.json). All 133 AI core agents have one. | Tests: test\_aicore\_b\_rci, test\_layer23\_rci. Not called by other agents in code. |

Other statements: Correct: methods; ingest rejects non-object or empty events (main.py:53-54); strings joined recursively and scanned, high or block refused (:55-58; guard levels 4 and 8 at velaris/intel/guard.py:51); masking and counts (:59-61); publishes through RCI_STREAM; context delegates to RCI_CONTEXT.snapshot (:63-65); no state of its own; no caller check; keys and numbers not masked; threshold hard-coded; the scan runs before the topic is validated (:55).

## Agent: EACPE_ALIGNMENT (id 132861)

Verdict: department legal_compliance; in the set as doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 14, wrong 0, partly wrong 0. Code: `departments/legal_compliance/EACPE_ALIGNMENT/main.py (128 lines)`.

No corrections needed.

Other statements: Every checked claim holds: method signatures (main.py:52, :66, :97); mandate check order (:108-115) and NFKC normalisation (:38-40); up to 20 principles (:67-69); needs_text (:117-118); guard screening and wrapping, 6000 characters, temperature 0, purpose alignment.review (:77-87); coverage validation, model_error, not_configured (:89-94); governance_admin on set_mandate and set_principles (:59, :70); align has no caller check; state file; sibling agents; no redaction before the model; exact match after normalisation.

## Agent: VCAS_ROUTER (id 132249)

Verdict: department _ai_core; in the set as doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 1, partly wrong 0. Code: `departments/_ai_core/VCAS_ROUTER/main.py (32 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Tests: test\_layer19\_vcas, test\_aicore\_b\_prime\_vcas. No manifest.json. | VCAS_ROUTER has a manifest.json (departments/_ai_core/VCAS_ROUTER/manifest.json). | Tests: test\_layer19\_vcas, test\_aicore\_b\_prime\_vcas. |

Other statements: Correct: signature route(task, handlers=None); returns autopilot_route ok with the handler or manual with a reason (main.py:22-32); task_error rules (VCAS_SUPERVISOR/main.py:25-37) give invalid_input; default handlers none so everything manual; no state, no model; called by VCAS_CORE; 32 lines; no authorisation; handler registry in memory; no check against PRIME grants.

## Agent: HARD_LOCKDOWN_MODE (id 131657)

Verdict: department security; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 2, partly wrong 2. Code: `departments/security/HARD_LOCKDOWN_MODE/main.py (77 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | A boolean, a fixed list and a counter-keyed log dict, all in memory. get\_logs returns a copy. | The enabled flag is stored in JsonState (state.json under <VELARIS_DATA>/agents/HARD_LOCKDOWN_MODE/), so a restart does not lift a lockdown. Only the whitelist, the blocked log and the counter are in memory (main.py:9-10, :30-33). | The enabled flag is stored in an owner-only file and survives a restart. The whitelist is a fixed list; the blocked log (a counter-keyed dict) is in memory only. get\_logs returns a copy. |
| 2 | No dependencies, no caller, no test. | It imports velaris.agentkit.state and velaris.core.access (main.py:15-16). A test covers it: velaris/tests/test_kan104_unauthenticated_writes.py. No other code calls it (still true). | Depends on velaris.agentkit.state and velaris.core.access. Tested in test_kan104_unauthenticated_writes.py. No enforcement point calls it. |
| 3 | None: any caller can disable the lockdown, which defeats its purpose. | disable() needs a security admin; enable() needs any authenticated caller; both are traced and a refusal returns False (main.py:39-47, docstring :4-6). | enable needs an authenticated caller; disable needs a security admin. Both are traced. Unauthorised calls return False. |
| 4 | - disable() has no authorisation (main.py:23) and the state is not persisted, so a restart lifts the lockdown. | Both parts are fixed: authorisation at main.py:42-45, persisted flag at main.py:30 and :46. | Delete the bullet. |

Other statements: Correct: methods; whitelist heartbeat and core_status; blocked actions logged as BLOCKED with a counter (main.py:70-72); the class docstring says it overrides soft lockdown but nothing links the two; default state is disabled; action strings not validated; log unbounded; no enforcement point calls attempt() (no caller found by search).

## Agent: DECISION_FIREWALL (id 229727)

Verdict: department security; in the set as doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 0, partly wrong 0. Code: `departments/security/DECISION_FIREWALL/main.py (42 lines)`.

No corrections needed.

Other statements: Every checked claim holds: block, allow and blocked (main.py:27-42); key up to 256 characters (:33); check_caller with governance or security admin roles (:35); blocked.json via JsonState, first blocker kept by setdefault (:22, :38); allow re-reads the file (:29); exercised by test_governance_kernel.py; no caller found in the code; no unblock method; no reason stored (line 38). Not verified: 'if the trace cannot record the attempt the change is refused' (needs the check_caller code).

## Agent: SECURE_ACTION_TOKENS (id 132073)

Verdict: department security; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 2, partly wrong 2. Code: `departments/security/SECURE_ACTION_TOKENS/main.py (85 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | `generate(action)` returns `base64(action:timestamp).signature` with an HMAC-SHA256 signature. | The payload is action:timestamp:nonce (random 8-byte hex), base64 encoded, then "." and the signature (main.py:49-54). | `generate(action)` returns `base64(action:timestamp:nonce).signature` with an HMAC-SHA256 signature. |
| 2 | where reason is SignatureMismatch, ActionMismatch, Expired or MalformedToken. | A fifth reason exists: Replayed (main.py:80). | where reason is SignatureMismatch, ActionMismatch, Expired, Replayed or MalformedToken. A token is accepted once; a repeat inside its lifetime is refused (single_use, True by default). |
| 3 | - The docstring says it prevents replay, but tokens are stateless and can be reused any number of times within the lifetime (main.py:17, 38-52). | Fixed. Used signatures are recorded in used.json (a shared JsonState) and a second use returns Replayed (main.py:44, :72-80). Subclasses that issue session tokens set single_use = False (ZERO_TRUST_PIPELINE/main.py:52). | Delete the bullet. Add: "ZERO_TRUST_PIPELINE sets single_use to False for its identity session tokens, so those can be reused until they expire." |
| 4 | - The payload is split on the first colon, so an action name that itself contains a colon never validates (main.py:46). | Fixed. The payload is split from the right with rsplit(':', 2) (main.py:64). | Delete the bullet. |

Other statements: Correct: HMAC-SHA256; 60 second default (main.py:37); 32-byte key sat.key, owner-only, created if missing (:43); signature checked in constant time first, then action, then age (:61-69); malformed input returns MalformedToken (:82-83); no caller check, so a token proves integrity and freshness, not who asked; tokens bound to an action string only; uses velaris.intel.paths. Not verified: the statement about the ZERO_TRUST_PIPELINE identity prefix and the forged-token test.

## Agent: THREAT_DETECTION_MESH (id 230629)

Verdict: department security; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 10, wrong 2, partly wrong 2. Code: `departments/security/THREAT_DETECTION_MESH/main.py (74 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | scores an event by how many of those key and value pairs it matches. | Only a signature whose fields ALL equal the event's values counts; a partial match adds nothing (main.py:50-52, docstring :7). | scores an event: a signature counts only when every field of its pattern equals the event's value, and then adds 10 per field. |
| 2 | Scoring: for every signature and every key and value pair in its pattern, an exact match on the event adds 10. | Same: the whole pattern must match, then 10 x the number of fields (main.py:51-52). | Scoring: for every signature whose fields all match the event exactly, add 10 per field of that signature. 20 or more is HIGH, 10 to 19 MEDIUM, else LOW. |
| 3 | - Score counts matching fields, not whole-signature matches, so one signature with two shared fields reaches HIGH even when the rest of the pattern does not match (main.py:36-41). | Fixed (main.py:50-52). A signature with two fields that fully matches still scores 20 (HIGH), by design. | Delete the bullet. |
| 4 | No dependencies, no caller, no test. | Two test files cover it: velaris/tests/test_agents_coverage_a.py and test_kan88_security_agents.py. No dependencies and no caller are still true. | No dependencies and no caller. Tests: test_agents_coverage_a.py and test_kan88_security_agents.py. |

Other statements: Correct: methods; thresholds 20 and 10 (main.py:58-62); in memory only; no built-in signatures so LOW; non-dict events raise; empty pattern adds nothing; exact equality only; events list unbounded (main.py:27); no authorisation; nothing feeds it events.

## Agent: POLICY_ACKS (id 99929)

Verdict: department hr; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026 (...51 pass). Also: ...". Claims checked 15, wrong 1, partly wrong 0. Code: `departments/hr/POLICY_ACKS/main.py (255 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Also: `retire_policy` (main.py:87-96) and `acknowledge` (main.py:131-158) write no trace entry, only `publish_policy` does, so the hash-chained ledger does not show retirements or acknowledgements; the evidence lives in the store only. | Both write a trace entry now: `policy.retired` (main.py:96) and `policy.acknowledged` (main.py:159-161, with a hashed employee id and the evidence hash). publish_policy writes `policy.published` (:84). | `retire_policy` (main.py:87-97) and `acknowledge` (main.py:132-162) each write a trace entry (policy.retired, policy.acknowledged), as does `publish_policy` (policy.published). The duplicate check in `acknowledge` is still a read then a write without a lock. |

Other statements: Correct: method list (main.py:52-245); publish_policy needs hr_admin (HR_ADMINS, :56-57); next version, exact text and SHA-256, supersedes previous (:72-83); audience all, departments or employee ids (:65-69); due_days 1 to 120 (:63); acknowledge uses the Caller's employee id, stale_text on a wrong hash, idempotent repeats (:132-157); reminders drafted only (docstring); audience resolved through onboarding_directory; publish writes state before the trace entry (:83-84); version computed before the write without a lock (:73-74); authorize_read identity on compliance_report and pending_for_employee (:184, :197). Not verified: the '51 pass' test run, the PolicyAcksReader link, dsr_erase detail.

## Agent: ITSM_ENGINE (id 98988)

Verdict: department it_infrastructure; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 16, wrong 4, partly wrong 0. Code: `departments/it_infrastructure/ITSM_ENGINE/main.py (222 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Any authenticated person or service may open and move tickets; no roles are required. No Prime approval. Free-text `note` and `config_item` may contain personal data, and are not redacted. | Opening needs any authenticated caller (main.py:128). Moving a ticket needs the infra_admin role (or security_admin); the person who opened a ticket may also cancel it or reopen it once resolved (main.py:157-158, docstring :17-18). `config_item` and `note` are passed through redact_json before they are stored (main.py:139, :162). | Any authenticated person or service may open a ticket. Moving a ticket needs the infra_admin or security_admin role; the person who opened it may also cancel it or reopen it once resolved. Secrets and personal identifiers in `note` and `config_item` are masked before storing. No Prime approval. |
| 2 | - No role separation: anyone authenticated can close another user's ticket. | Fixed: transition needs infra_admin or security_admin (main.py:157-158); the opener can only cancel or reopen their own ticket (:156). | Delete the bullet. |
| 3 | - Notes are not redacted before they go into history. | Fixed: `note = redact_json(note)` (main.py:162). | Delete the bullet. |
| 4 | The thinking (classification, linking, summaries) is not here. ... Tool `itsm_transition(ticket_id, to, note)` needs the acting caller; closing or cancelling should need a human. | Not wrong, but the roles above now apply to every transition, not only closing or cancelling. | Tool `itsm_transition(ticket_id, to, note)` needs the acting caller to be an infra or security admin (or the opener, for cancel and reopen). |

Other statements: Correct: method list; score weights, priority bands and SLA minutes (main.py:34-35, :73-75); state table (:36-44); the reporter's priority is validated and only echoed (:92-93, :119-120); open_ticket stores in tickets.json and audits ticket.open (:128-148); transition adjusts hold accounting, note cut at 500 characters, audits (:151-186); list_tickets sorting (:218-222); VELARIS_ORG stamping (:47-53); allow-list rules (velaris/api/allowlist.py: list_tickets, get_ticket, sla_status READ, transition ACT with actor by); open_ticket is not on the allow-list; the precision paragraph about unchecked audit calls after save (:148, :185) is correct.

## Agent: RISKON (id 99516)

Verdict: department finance; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026. Also noted: ...". Claims checked 10, wrong 1, partly wrong 0. Code: `departments/finance/RISKON/main.py (76 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Float arithmetic; no state; debug logging with its own handler. | The module only creates a logger (main.py:17) and logs at debug level; it has no handler of its own. | Float arithmetic; no state; debug logging through a module logger. |

Other statements: Correct: volatility is the population standard deviation (main.py:34-44); exposure sums absolute amounts (:46-52); risk_score weights 0.5, 0.3, 0.2, configurable (:22-26, :54-67); compare_risk returns A, B or Equal (:69-76); inputs default to empty or zero; no validation, non-numeric uncertainty raises; a custom weights dict missing a key raises KeyError (:62); test_riskon.py exists; no agent calls it.

## Agent: INITIATIVE_ENGINE (id 100056)

Verdict: department project_management; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 12, wrong 0, partly wrong 1. Code: `departments/project_management/INITIATIVE_ENGINE/main.py (69 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | (`departments/_ai_core/AIIE_KERNEL/main.py:19`, imported by name and `propose()` called at lines 28-29) | AIIE_KERNEL lists it in PIPELINE at line 19 and calls it by name at lines 26-27 (import_module and getattr in _default_stages). | (`departments/_ai_core/AIIE_KERNEL/main.py:19`, imported by name and `propose()` called at lines 26-27) |

Other statements: Correct: RICE formula and rounding to 4 places (main.py:56); ties by name, rank, idea (:59-63); needs_data and failed replies (:37-41); every error collected before refusing (:57-58); at most 1000 (:22); register.json under VELARIS_DATA (:13, :28, :62); no caller check; only the last ranking kept; result echoes the context (:63); depends on biz_common; tests exist (test_dept_project_management_stubs.py, test_AI_IE_layer.py). Not verified: 'a corrupted register file is set aside' (shared state code not read).

## Agent: VMRK (id 99839)

Verdict: department marketing; in the set as sample and doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 10, wrong 3, partly wrong 1. Code: `departments/marketing/VMRK/main.py (34 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | A non-string message raises AttributeError. `verify` raises TypeError if the signature is not an ASCII string, instead of returning False. | `verify` returns False for a non-string message or signature and compares as bytes, so a non-ASCII signature no longer raises (main.py:28-32). `sign` still raises AttributeError for a non-string message (docstring :7-8). | A non-string message raises AttributeError in `sign`. `verify` returns False for any input that is not a matching string pair. |
| 2 | - Line 22: `compare_digest` raises TypeError for a non-ASCII or non-string signature; verify should return False. | Fixed (main.py:29-32). | Delete the bullet. |
| 3 | Purpose and department are unclear; no tests of sign and verify themselves. | sign and verify are exercised in velaris/tests/test_kan94_sales_marketing.py:63 and test_kan106_business_agents.py:93. Purpose and department are still unexplained. | Purpose and department are unclear. sign and verify are tested in test_kan94_sales_marketing.py and test_kan106_business_agents.py. |
| 4 | Called by: only the file-permission tests `velaris/tests/test_private_files.py` and `test_agent_paths.py`; no agent uses it. | Also used by test_kan94_sales_marketing.py and test_kan106_business_agents.py. No agent uses it (still true). | Called by tests only: test_private_files.py, test_agent_paths.py, test_kan94_sales_marketing.py, test_kan106_business_agents.py; no agent uses it. |

Other statements: Correct: HMAC-SHA256 base64 signature and constant-time compare; 64-byte key in <VELARIS_DATA>/agents/VMRK/vmrk.key via load_or_create_key (main.py:20-22), owner-only; no rotation, key id or nonce; no caller check; construction fails if the key file cannot be made private (comes from load_or_create_key; not read).

## Agent: FABRICA (id 66426)

Verdict: department operations; in the set as sample and doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 9, wrong 0, partly wrong 0. Code: `departments/operations/FABRICA/main.py (50 lines)`.

No corrections needed.

Other statements: Every checked claim holds: class FabricaAgent(config), layer_weight default 1.0 (main.py:16); build_layers, composition_score (unique names x weight), combine (shallow merge, b wins) (:24-50); standard library only; unhashable items raise TypeError; a string input counts per character; test_fabrica.py exists; no agent depends on it. Not verified: 'Called by ... the router' (I found no router or API reference to it).

## Agent: FLUXOR (id 131673)

Verdict: department operations; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 9, wrong 0, partly wrong 0. Code: `departments/operations/FLUXOR/main.py (67 lines)`.

No corrections needed.

Other statements: Every checked claim holds: spike_threshold default 1.5 (main.py:20); compute_throughput is the mean, 0.0 for empty (:32-37); detect_spike needs 2 or more values and compares the last value with the mean of the earlier ones times the threshold (:43-48); balance_load moves each load 1 toward the target and does not keep the total (:59-65); no validation; no state; test_fluxor.py exists. Not verified: 'Called by ... the router'.

## Agent: ECONOMIC_INTELLIGENCE_MESH (id 131769)

Verdict: department finance; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 10, wrong 5, partly wrong 1. Code: `departments/finance/ECONOMIC_INTELLIGENCE_MESH/main.py (56 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | `trend_score()`: mean of consecutive differences across all records, regardless of indicator name. | The differences are taken within one indicator name only, then averaged (main.py:33-38). | `trend_score()`: mean of the changes between consecutive values of the same indicator; a change is never taken between two different indicators. 0.0 when no indicator has two values. |
| 2 | `classify_risk()`: above 5 gives OPPORTUNITY, above 0 STABLE, otherwise RISK. | Above 5 OPPORTUNITY, 0 to 5 inclusive STABLE, below 0 RISK (main.py:42-47). A flat trend is STABLE. | `classify_risk()`: above 5 gives OPPORTUNITY, from 0 to 5 STABLE, below 0 RISK. With too little data the score is 0.0, which reads as STABLE. |
| 3 | All indicators are mixed into one series, so differences between unrelated indicators (for example inflation then GDP) are averaged together. | Fixed (main.py:33-38). | Delete the sentence. |
| 4 | No dependencies. No callers and no tests found. | Tests exist: velaris/tests/test_agents_coverage_b.py and test_kan85_70_finance_supply.py. No callers (still true). | No dependencies and no callers. Tests: test_agents_coverage_b.py and test_kan85_70_finance_supply.py. |
| 5 | - A flat trend (0) is labelled RISK (`main.py` lines 35-36), which is wrong for a stable series. | Fixed (main.py:44-45, comment "flat (0) is stable, not a risk"). | Delete the bullet. |
| 6 | - Mixing indicators makes the trend meaningless; no tests; duplicates ECON\_INTEL\_CORE. | Indicators are no longer mixed, and tests exist. It still duplicates the idea of ECON_INTEL_CORE (not compared in detail). | - It overlaps with ECON\_INTEL\_CORE. |

Other statements: Correct: records are in memory only; add_indicator appends; summary returns count, trend and risk (main.py:49-54); no validation, a non-number fails later with a raw exception; no authorisation.

## Agent: OVERSIGHT_MONITOR (id 229943)

Verdict: department security; in the set as sample and doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 9, wrong 0, partly wrong 0. Code: `departments/security/OVERSIGHT_MONITOR/main.py (25 lines)`.

No corrections needed.

Other statements: Every checked claim holds: record appends any dict, last returns the newest or {} (main.py:20-25); in-memory list, nothing validated or persisted; debug line per record (:22); no caller check; test_governance_kernel.py loads it; no agent calls record; the list is unbounded.

## Agent: COHORTUS (id 131641)

Verdict: department sales; in the set as doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 9, wrong 0, partly wrong 0. Code: `departments/sales/COHORTUS/main.py (48 lines)`.

No corrections needed.

Other statements: Every checked claim holds: assign_roles cycles roles and gives None to everyone when roles is empty (main.py:29-36); collaboration_clusters slices into chunks, last may be smaller (:45-46); size 0 raises ValueError, a negative size gives an empty list (range with a negative step); duplicates collapse in the dict; no caller check; no state; test_cohortus.py exists; no callers.

## Agent: CREATIVE_HOLODECK (id 99676)

Verdict: department marketing; in the set as doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 9, wrong 1, partly wrong 0. Code: `departments/marketing/CREATIVE_HOLODECK/main.py (59 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Called by: nothing found, no test. | A test covers it: velaris/tests/test_agents_coverage_a.py. Nothing in the platform calls it (still true). | Called by: nothing in the platform. Tested in test_agents_coverage_a.py. |

Other statements: Correct: the four word lists and 256 combinations (main.py:24-27); compose returns the four values and the sentence, or an error dict naming the first bad value (:29-47); random_scene uses the global random module (:49-57); no state; no caller check; errors use an `error` key.

## Agent: BUSINESS_DNA (id 99897)

Verdict: department executive; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 14, wrong 0, partly wrong 0. Code: `departments/executive/BUSINESS_DNA/main.py (80 lines)`.

No corrections needed.

Other statements: Every checked claim holds: run with set and get, default action (main.py:64-72); allowed fields, list limit 50, integer ranges, unknown fields rejected (:22-47); six required fields (:26); errors collected and nothing stored on error (:73-75); merge, version counter, UTC time (:76-79); profile.json under VELARIS_DATA; uses biz_common; no caller check; tested in test_dept_executive_stubs.py; no callers; the unlocked load, merge, save at main.py:68-79 is still there; merge cannot remove a field; no history.

## Agent: MEMORY_DRIFT_DETECTOR (id 132265)

Verdict: department data_knowledge; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 12, wrong 2, partly wrong 2. Code: `departments/data_knowledge/MEMORY_DRIFT_DETECTOR/main.py (80 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | - main.py:39: baseline file is rewritten non-atomically; a crash mid-write corrupts it and the next load resets all baselines. | The file is written with write_private, which is atomic and owner-only (main.py:46; docstring :9-10). | Delete the bullet. |
| 2 | **Deterministic tool.** A small, correct comparison, but crude and untested. | It is tested: velaris/tests/test_kan93_agents.py (and test_agent_paths.py). | **Deterministic tool.** A small, correct comparison, but crude. Tested in test_kan93_agents.py. |
| 3 | No agent calls it. The only reference is `velaris/tests/test_agent_paths.py`, which checks where its files go, not its scoring. | A second test file references it: test_kan93_agents.py. No agent calls it (still true). I did not read what test_kan93_agents.py asserts. | No agent calls it. Tests: test_agent_paths.py (file locations) and test_kan93_agents.py. |
| 4 | 1. Baselines are kept in `baseline.json` in the agent's data folder (created as `{}` if missing). | The file does not exist until the first set_baseline; a missing file means an empty baseline in memory (main.py:40, docstring :9-10). | 1. Baselines are kept in `baseline.json` in the agent's data folder (owner-only, written atomically). The file is created by the first set_baseline. |
| 5 | Code: `departments/data_knowledge/MEMORY_DRIFT_DETECTOR/main.py` (74 lines). | The file has 80 lines. | (80 lines) |

Other statements: Correct: methods; score is the percentage of keys over the union of old and new keys whose values differ (main.py:60-70); 100 with no baseline, 0 for two empty dicts; thresholds 20 and 60 (:74); nested values compared as whole objects; unreadable baseline treated as empty (:41-43); non-dict new_data raises AttributeError; result omits which keys changed; not on the API allow-list.

## Agent: OFFLINE_REGISTRY (id 230203)

Verdict: department it_infrastructure; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026 (also listed in KAN-90).". Claims checked 14, wrong 11, partly wrong 2. Code: `departments/it_infrastructure/OFFLINE_REGISTRY/main.py (34 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | A tiny key-value store kept in a JSON file, intended as an offline registry. It is the thinnest agent in the department and does not follow the shared agentkit conventions. | It now uses JsonState from agentkit and velaris.intel.paths (main.py:11-12, :23). | A small key-value store kept in one owner-only JSON file, usable offline. |
| 2 | The constructor takes a file path, default `/tmp/velaris_offline_registry.json`. | Default is <VELARIS_DATA>/agents/OFFLINE_REGISTRY/registry.json (main.py:5, :22). | The constructor takes an optional file path; the default is `<VELARIS_DATA>/agents/OFFLINE_REGISTRY/registry.json`. |
| 3 | 1. On construction it loads the JSON file if present; an unreadable file is logged and replaced by an empty dict in memory. | JsonState sets an unparseable file aside as <name>.corrupt-<time> and starts empty (docstring :5-7). | 1. An unparseable file is set aside as <name>.corrupt-<time> and the registry starts empty. |
| 4 | 2. `set` updates the in-memory dict and rewrites the whole file with `open(path, "w")`. | `set` updates the state under a lock and writes atomically (main.py:31; docstring :5-6). A key must be a non-empty string or ValueError is raised (:29-30). | 2. `set` stores the value under a non-empty text key (ValueError otherwise), written atomically under a lock shared by workers. |
| 5 | 3. `get` reads only the in-memory copy. | `get` reads the state file each time (main.py:34). | 3. `get` reads the stored file. |
| 6 | Not used: JsonState, result shapes, input checks, per-agent data directory, locking. | JsonState, a per-agent data directory and locking are used; the key is checked. Result shapes are still not the agentkit ones (it returns the raw value). | Not used: the agentkit result shapes. |
| 7 | No dependencies on other agents or platform modules. Its only caller is `velaris/tests/test_memory_substrate.py`, which imports it as `live.agents.OFFLINE_REGISTRY.main` ... | It imports velaris.agentkit.state and velaris.intel.paths. Three test files reference it: test_kan90_infra.py, test_memory_substrate.py, test_no_state_in_source_tree.py. I did not check the alias remark. | Depends on velaris.agentkit.state and velaris.intel.paths. Tests: test_kan90_infra.py, test_memory_substrate.py, test_no_state_in_source_tree.py. No agent calls it. |
| 8 | Unreadable file: starts empty (and the next `set` overwrites the damaged file, evidence lost). Non-JSON values raise during `json.dump` after the in-memory change and after the file was opened for writing, leaving memory and disk different and a truncated file. No input validation. It does not fail closed. | The damaged file is kept under a new name (docstring :5-7); a value that cannot be written raises on set before the file is replaced (atomic write); the key is validated (main.py:29-30). | Unreadable file: set aside as <name>.corrupt-<time>, registry starts empty. A value that cannot be written as JSON raises on set and the stored file is unchanged. The key is validated; the value is not. |
| 9 | No caller check, no Prime approval. The default path is in the shared `/tmp` with default file permissions, so other local users can read or replace it. | No caller check is still true (docstring :7-8). The file is owner-only under VELARIS_DATA (docstring :5). | No caller check, no Prime approval. The file is owner-only under VELARIS_DATA. |
| 10 | - Default storage path in `/tmp` loses data on reboot and is shared. | Fixed (main.py:22). | Delete the bullet. |
| 11 | - Non-atomic write and no lock; two instances overwrite each other. | Fixed: atomic write, locked across workers (docstring :5-6). | Delete the bullet. |
| 12 | Deterministic tool, but thin and below the department standard. Not ready to be given to a model as-is. | Thin is still true; "below the department standard" no longer fits since the KAN-90 fix. | Deterministic tool, thin. |

Other statements: Still correct: methods set, get, health_check with version 0.1.0 (main.py:26-34); no caller check; purpose overlaps with LOCAL_REGISTRY_CACHE (not compared in detail).

## Agent: FORMULA (id 99404)

Verdict: department finance; in the set as doubt (text 'unclear'). Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 9, wrong 1, partly wrong 0. Code: `departments/finance/FORMULA/main.py (50 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | Pure in-process code, no state, no validation. Debug logging with its own stream handler attached at import. | The module only creates a logger (main.py:14). There is no handler. | Pure in-process code, no state, no validation. Debug logging through a module logger. |

Other statements: Correct: build_framework, pattern_score (unique items x weight, default 1.0), merge_templates (t2 wins) (main.py:27-50); no dependencies; test_formula.py is the only test; no other caller; unhashable elements raise TypeError; shallow merge discards nested keys of t1.

## Agent: SIMULON (id 231073)

Verdict: department project_management; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 10, wrong 2, partly wrong 0. Code: `departments/project_management/SIMULON/main.py (52 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | The module attaches a console log handler when it is imported. | The module only creates a logger (main.py:12); no handler is attached. | Delete the sentence. |
| 2 | - Importing the module adds a console handler, causing duplicate log lines if imported twice under different names. | Same: no handler is attached. | Delete the bullet. |

Other statements: Correct: run_linear, run_dynamic, scenario and health_check (main.py:20-52); steps from config, default 5 (:17); run_dynamic runs the supplied function as given; steps of 0 gives [] from run_linear and [initial] from run_dynamic (docstring :6-7); standard library only; test_simulon.py exists; no caller check.

## Agent: MACHINE_LIFECYCLE_ENGINE (id 66187)

Verdict: department supply_chain; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 6, wrong 1, partly wrong 1. Code: `departments/supply_chain/MACHINE_LIFECYCLE_ENGINE/main.py (120 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | - install\_year is only range checked, so a fractional year (for example 2020.5) passes validation and gives a fractional age. Event counts are checked as integers but install\_year is not. | install_year must be a whole year: validate refuses a fractional value (main.py:54-55). | Delete the bullet. |
| 2 | (118 lines) | The file has 120 lines. | (120 lines) |

Other statements: Limited check: I read the validation (main.py:46-57, MAX_HOURS 200000 at :37, years 1900 to the as-of year) and the test and caller facts, not the MTBF, derating or components formulas (lines 74 onward), so the description of those formulas is NOT VERIFIED. Correct: tests in test_dept_supply_chain_stubs.py and test_kan85_70_finance_supply.py; no caller; uses biz_common.

## Agent: AGENT_CONTAINMENT_MODES (id 66247)

Verdict: department security; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 3, partly wrong 2. Code: `departments/security/AGENT_CONTAINMENT_MODES/main.py (64 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | None. Any caller can set any agent to any mode, including lowering a lock to SANDBOX. No Prime approval, no personal data. | set_mode and set_metadata call check_caller with the security admin role and return False for anyone else; the attempt is traced (main.py:34-37, :45-48; docstring :5-7). | Only a security administrator can set a mode or metadata (the attempt is traced; others get False). Reads need no caller. No Prime approval, no personal data. |
| 2 | - No caller check on set\_mode (main.py:20), no persistence, no audit trail. | The caller check exists (main.py:34-37) and the attempt is traced. Persistence is still missing: modes are lost on exit (docstring :9-10). | - Modes and metadata are in memory only: they must be set again after a restart. |
| 3 | Depends on nothing. No caller and no test mentions it. | It imports velaris.core.access (main.py:14). A test covers it: velaris/tests/test_kan104_unauthenticated_writes.py. No caller (still true). | Depends on velaris.core.access. Tested in test_kan104_unauthenticated_writes.py. No platform code reads it. |
| 4 | 1. set\_mode rejects any value outside the three modes (returns False) and otherwise stores it in a dict keyed by agent name. | It also returns False for an empty or non-text agent name and for a caller who is not a security admin (main.py:32-37). | 1. set\_mode returns False for a mode outside the three, for an empty or non-text agent name, or for a caller who is not a security administrator; otherwise it stores the mode in a dict keyed by agent name. |
| 5 | Invalid mode: returns False, state unchanged. Unknown agent: UNSET with no allowed actions, so a query fails closed. The agent name is not validated. | set_mode checks the agent name is a non-empty string (main.py:32). | Invalid mode or empty agent name: returns False, state unchanged. Unknown agent: UNSET with no allowed actions, so a query fails closed. |

Other statements: Correct: modes, mapping to allowed action classes (main.py:55-63), UNSET gives an empty list, state in memory, metadata is a free dict, nothing enforces the mode (no code reads allowed_actions).

## Agent: DOMAIN_ADVISOR (id 229963)

Verdict: department sales; in the set as sample. Last line of the page: "Verified against source 14 Nov 2026.". Claims checked 11, wrong 1, partly wrong 2. Code: `departments/sales/DOMAIN_ADVISOR/main.py (82 lines)`.

| # | Statement on the page | What the code shows (path:line) | Replace with |
| --- | --- | --- | --- |
| 1 | - Line 72 tests `if overall_cycle`, so a company median of 0 days silently skips rule A5. | Fixed: the test is `overall_cycle is not None` and a comment explains the 0-day case (main.py:72-75). A vertical with a median of 0 days is never flagged slow. | Delete the bullet. |
| 2 | It returns advice rows (rule, vertical, text, evidence), the company win rate, median cycle days and thresholds. | Each row has the keys rule, vertical, advice and evidence (main.py:58); the result also lists the rules and a note (:77-82). | It returns advice rows (rule, vertical, advice, evidence), the company figures (win rate, median cycle days, closed deals), the rules and the thresholds. |
| 3 | Called by: `velaris/tests/test_dept_sales_stubs.py` (advise, lines 56-69) and, for health\_check only, the import loop in `velaris/tests/test_layer20_adme.py:6`. | test_kan94_sales_marketing.py also references it (found by name search). Line numbers in the tests were not re-checked. | Called by tests only: test_dept_sales_stubs.py, test_kan94_sales_marketing.py and (health_check only) test_layer20_adme.py. |

Other statements: Correct: rules A1 to A5 and their thresholds (main.py:22-31, :62-76); min_closed validation (:42-43); needs_data for no deals (:47-48); one bad deal refuses the whole call (:45-46); only min_closed is settable (:80-81); no caller check; no model. Not verified: 'money is exact Decimal' (biz_sales not read).

## Pages not reviewed

These pages are in the set (sample or doubt) but I did not get to them. Most have a doubt word on them or are in the sample.

| Page | Id | Department | Why in the set |
| --- | --- | --- | --- |
| Agent: ADAPTIVE_BRANDING | 66934 | marketing | doubt word |
| Agent: AIIE_KERNEL | 99324 | _ai_core | doubt word |
| Agent: AUTONOMOUS_RESEARCH_ENGINE | 230688 | _ai_core | doubt word |
| Agent: CUSTOMER_BEHAVIOR_ENGINE | 132393 | marketing | sample |
| Agent: EPISODIC_MEMORY | 230139 | data_knowledge | sample |
| Agent: GST_ENGINE | 98651 | finance | doubt word |
| Agent: INTERVIEW_RECORD | 99660 | hr | doubt word |
| Agent: LYRA_VOICE_ENGINE | 99292 | _ai_core | doubt word |
| Agent: MCFE_FIELDGEN | 230187 | _ai_core | doubt word |
| Agent: OFFER_LETTERS | 132409 | hr | doubt word |
| Agent: PAYROLL_ENGINE | 99993 | hr | doubt word |
| Agent: SELF_CORRECTION_ENGINE | 99084 | _ai_core | doubt word |
| Agent: SPRINT_PLANNER | 67523 | project_management | doubt word |
| Agent: TDS_ENGINE | 229579 | finance | doubt word |
| Agent: TIME_TRACKER | 67594 | project_management | doubt word |
| Agent: ZOHO_PEOPLE | 229743 | _connectors | sample and doubt word |

16 pages not reviewed. Part 1 pages (patterns, gateway, AI Core, and the six 1b pages) were all reviewed.

## Pages with a credential

No page I read contained a credential or secret.
