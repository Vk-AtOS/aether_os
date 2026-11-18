# formal_verification_report.json (phase p06b)

Written by `phases/p06b_formal_verification/task_agent.py` to the phase output directory and to the
generated project root; stage s05 reads it as `verification_report` and a `FAIL` verdict blocks delivery
(`stages/s05_quality/supervisor.py`, `validate_gate`).

## What it is, and what it is not
A **static check of the generated source**, not a proof of runtime behaviour. Two kinds of invariant:

| Ids | Kind | What Z3 is asked |
|---|---|---|
| INV-001..007 (auth gate, input safety, state-machine guard, SQL safety, tenant filter, ownership check, one commit) | **Consistency check.** A boolean fact is extracted from the AST (is there a `Depends`? a `.where(org_id)`?) and Z3 confirms the fact holds. | Not a proof of the rule: if the extraction is wrong the check is wrong. Confidence is below 1 for the regex based ones. |
| INV-008 (unknown roles are denied everything), INV-009 (read-only roles cannot create/update/delete) | **Proof of the rule.** `services/permissions.py` is read; its `_has_permission` must be the exact function AetherOS generates (compared as an AST, otherwise `UNVERIFIABLE`); the rule is encoded symbolically over every role, resource and action, including an "other" member that stands for every unseen name, and the property is checked for a counter-example. | Z3 when installed. Without Z3 the same finite domain is enumerated exhaustively (also complete); `proof_method` names the engine. |

## Fields
| Field | Meaning |
|---|---|
| `schema_version` | `"1.0"` |
| `verified_at`, `z3_version`, `z3_available`, `z3_solver_time_ms` | When, with what, how long. `z3_available: false` means INV-001..007 did not run. |
| `project_name`, `domain`, `files_scanned` | Context. `files_scanned` is the number of `.py` files read (capped), not routes. |
| `overall_verdict` | `FAIL`: at least one invariant was violated (always, even if the run was otherwise partial). `PARTIAL`: Z3 missing, a partial reason, or nothing found to check; never read as a pass. `PASS`: no violation and something verified. |
| `confidence_score` | Verified / (verified + failed + unverifiable). `N/A` counts as verified. |
| `scope` | The text above in one paragraph, so the file explains itself. |
| `invariants_verified`, `invariants_failed`, `invariants_unverifiable` | One entry per (invariant, route): `invariant_id`, `invariant_name`, `route` (for INV-008/009 the permissions file path), `status` (`VERIFIED`, `N/A`, `VIOLATED`, `UNVERIFIABLE`), `proof_method`, `solver_time_ms`, `confidence`, and for a violation `violation_detail` (for INV-008/009 the counter-example as role, resource, action). |
| `partial_reason` | Present when `PARTIAL` because of a missing tool. |

## Gate
`gate.py`: `FAIL` blocks (`passed=False`); `PASS` and `PARTIAL` continue, `PARTIAL` capping the confidence at 0.6.
`UNVERIFIABLE` (try/except, generators, dynamic dispatch, an unmodelled decision function) is reported, never counted as verified.
