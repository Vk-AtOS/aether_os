# Blueprint: what goes where, and what happens when

Last updated 2026-11-11. This is the working reference for the build. The full
reasoning is in the architecture dossier; this file is the short, enforceable version.

## 1. Vision

One company-running system made of three products on one foundation.

| Product | Job | Lives in |
|---|---|---|
| **AetherOS** | Software factory: turns a request into a tested, secured, deployable application | this repo |
| **Velaris** | Operations platform: people, finance, projects, knowledge, access | `Knackforge/velaris_knackforge` |
| **Prime** | Central brain: acts for absent people inside written, time-limited delegations | `prime/` in this repo |

Rules that hold everywhere:

1. **Nothing bypasses the foundation.** Every action is authenticated, authorised, and written to the ledger.
2. **Models propose; code decides.** A model's output never authorises anything. Money, law and access are computed by deterministic code.
3. **Fail closed.** Unknown action, missing permission, expired delegation or failed check means stop.
4. **No fabricated results.** Unimplemented means "not implemented", never a made-up score or a check that returns true.
5. **Proof before claims.** A capability exists when a recorded run shows it, not when the code for it exists.

## 2. What goes where (this repo)

| Folder | Holds | Must not hold |
|---|---|---|
| `gateway/` | HTTP only: routers (≤400 lines), auth dependencies, request/response models | Business logic, model calls |
| `gateway/dependencies.py` | The single place identity is established for a request | — |
| `orchestrator/` | Run control: stage order, waves, checkpoints, hooks, events | Code generation |
| `stages/` | The 12 stage supervisors (`s01`…`s12`): run sub-phases, apply the gate | Prompts, generators |
| `phases/` | One folder per sub-phase: `task_agent.py`, `prompts.py`, `helpers.py` | Cross-phase imports except through `phases/base.py` |
| `core/llm/`, `core/model_router.py` | The only path to any model | — |
| `core/audit/` | The hash-linked ledger | Update or delete paths |
| `core/policy/`, `core/identity/` | Permission decisions, service tickets | — |
| `core/sandbox/`, `core/run_app/` | Running generated code | Anything trusted |
| `prime/` | Delegations, autonomy levels, the never-list, `authorize()` | Model calls, direct execution |
| `dashboard/` | React user interface | Secrets |
| `scripts/local.sh` | Local setup: `check`, `up`, `e2e`, `down` | — |
| `benchmarks/results/` | Recorded end-to-end build reports: the evidence | — |
| `tests/` | Tests that exercise real code paths | Tests that mock the function under test |

Generated applications are written to `~/.aether_os/projects/<run_id>/`, one folder per
sub-phase at the project root (for example `p04_backend/backend_codegen/src`). Every
reader looks there; no stage may nest its output under its own stage folder.

## 3. What happens when: a build

```
POST /factory/start
  → gateway: authenticate, check org and plan, rate-limit, create Run
  → orchestrator.FactoryPipeline.run: build context, order 12 stages into 9 waves
```

| Wave | Stage | Does | Gate (blocks the run if it fails) |
|---|---|---|---|
| 1 | `s01_intake` | Research, requirements, clarifying questions | Requirements complete; spec review unless autonomous |
| 2 | `s02_architecture` | Architecture, domain model, scaffold | Domain model validates |
| 3 | `s03_backend` | Backend code, business logic, integrations | Code parses; app boots; backend audit |
| 4 | `s04_frontend` | Frontend code | Builds; routes match the backend |
| 5 | `s05_quality` ‖ `s12_specialist` | Security and quality review; specialist targets | Findings recorded for healing |
| 6 | `s06_testing` | Unit tests against the generated app | Test summary written |
| 7 | `s07_healing` | Repair loop, up to 5 attempts; never edits tests | Quality score ≥ threshold, or run marked failed |
| 8 | `s08_observability` ‖ `s09_devops` ‖ `s10_enterprise` | Monitoring, containers and deploy, enterprise features | App healthy at its live URL |
| 9 | `s11_handoff` | Documentation, quality report, delivery | Report complete |

After each stage: outputs and metadata merge into the shared context, a checkpoint is
saved, and post-stage hooks run. A parallel wave is checkpointed once, on its earliest
stage, so a resumed run never skips stages. Every stage start, finish and failure is an
event on Redis (for the live view) and a row in `phase_completions`.

A run is **done** only when the generated app answers its health check, accepts a
login, and passes create/read/update/delete on one entity. `./scripts/local.sh e2e`
checks exactly this and writes the report to `benchmarks/results/`.

## 4. What happens when: a request to Prime

```
action (who, what, amount, on whose behalf)
  → prime.authorize(action, now)        pure function, no model
       never-list, unknown action, or above the payment ceiling → REFUSE
       no delegation, or it is expired / revoked / not yet valid → REFUSE
       outside scope, over limit, or wrong currency             → ROUTE_TO_DEPUTY
       else by autonomy level (lowest level wins if several delegations match):
         0 observe                → REFUSE
         1 recommend              → RECOMMEND_ONLY
         2 act with approval      → NEEDS_APPROVAL
         3 act then notify        → EXECUTE_AND_NOTIFY
         4 act within delegation  → EXECUTE
  → ledger: the request and the decision are both appended, including refusals;
            granting and revoking a delegation are ledger entries too
  → executor (AetherOS or Velaris adapter) runs it only on EXECUTE / EXECUTE_AND_NOTIFY
```

Prime never does, under any delegation: hire or terminate a person, change pay, sign a
legal contract, pay above the ceiling (₹5,00,000), change its own delegations or autonomy, alter the
ledger, or disable a security control.

## 5. Security, from sign-in to output

| Step | Control |
|---|---|
| Sign-in | Passwords hashed with a vetted library; access and refresh tokens are distinct types and checked as such; MFA |
| Every request | Identity from `gateway/dependencies.py`; every resource is loaded "for this org or 404" |
| Model calls | Only through the router; per-run budget; keys never in process-wide environment per tenant |
| Generated code | Runs in a sandbox, never in the platform process; preview needs sign-in and forwards no caller headers |
| Checks on output | Static analysis, dependency and secret scanning, tests, boot check; all blocking |
| Record | Hash-linked ledger (`core/audit/chain.py`); `verify()` detects any edited entry; the database blocks update and delete |
| Delegations | At most 30 days, always with a named deputy, revocable at any time |

## 6. Build order and status

| Phase | Scope | Status |
|---|---|---|
| 0 Repair | Make the existing pipeline and gateway correct | In progress; see `CURRENT_STATE` |
| 1 Foundation | Ledger, identity, permissions, tenant isolation, sandbox | Ledger and Prime core started |
| 2 AetherOS v2 | One living specification, per-phase edit and re-run, verifier on a second model | Not started |
| 3 Velaris v1 | People, finance (India: PF, ESI, TN professional tax, TDS, GST), projects, Jira and Confluence connectors | Loader repair started |
| 4 Prime | Executors for AetherOS and Velaris, deputy routing, delegation screens | Core only |

Local first: everything runs on one machine. No cloud deployment is part of the plan
until a customer needs it.

## 7. Before any demo

1. Put a working model key in `.env` (`ANTHROPIC_API_KEY`, or a valid Bedrock token).
2. `./scripts/local.sh check` — all lines must say `ok`.
3. `./scripts/local.sh e2e` — must exit 0 and leave a report in `benchmarks/results/`.
