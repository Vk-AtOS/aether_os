# Secret rotation and history rewrite runbook (KAN-173, KAN-175, KAN-203)

Status: PREPARED, NOT EXECUTED. Every step below needs the owner. This file contains no secret values,
only locations. Order matters: rotate first, rewrite history second. Rotation is what protects you;
anything that was ever in git (or on GitHub, even private) must be treated as known.

## 0. Why the `gitleaks` job was red on main, and the baseline (KAN-203)

`bash scripts/ci/secret_scan.sh` reported 24 raw findings in git history (one pair of kinds: credentials quoted in
old notes and audit documents, and fake keys in tests). Owner decision, 22 Nov 2026: the credentials found in
history are test-only, will NOT be rotated and history will NOT be rewritten before the sale.

To keep CI blocking on anything new, the 23 distinct reviewed fingerprints are listed in `.gitleaksignore`
(repo root, picked up automatically by gitleaks), grouped by reason: test fixtures, and historic-only content in
files since removed from HEAD. A working-tree scan confirms no live secret remains in tracked files; the
notes file that held credentials is untracked and gitignored. Fingerprints are commit-bound, so a secret added
in any new commit is still reported and fails the job (checked locally with a fresh fake cloud key in a temp commit).

Rules: never add a finding that exists at HEAD to `.gitleaksignore`, remove the secret instead. The rotation and
rewrite steps below stay available if the owner reverses the decision; they are not required for a green job.

## 1. Rotate (owner, in this order)

| # | Secret | Where it lives now | How to rotate |
|---|--------|--------------------|---------------|
| 1 | VPS root password | `plans2.md:15` (HEAD, pushed) | change on the server via the DigitalOcean console; prefer SSH keys, disable password login |
| 2 | AWS access key (id in `plans2.md:13`) | HEAD + history | IAM: create new key, update `AWS_*` in the server `.env`, deactivate then delete the old key; review CloudTrail for use of the old key |
| 3 | `AETHER_SECRET_KEY` (JWT signing) | history: `FULL_AUDIT_REPORT_2026_05_09.md:175`, `MASTER_SECURITY_AND_HARDENING_REPORT.md:207,1505,2802` | `openssl rand -hex 32`; all sessions/JWTs become invalid (intended) |
| 4 | Admin password | history: same two reports (`:176`/`:208`), `AUDIT_REPORT_20260507.md:126`, `plans2.md` row E-8 (local, unpushed) | change in the app; set new `AETHER_ADMIN_PASS` on the server |
| 5 | `AETHER_ONE_ZT_SECRET` | history: `FULL_AUDIT_REPORT_2026_05_09.md:177`, `MASTER_SECURITY_AND_HARDENING_REPORT.md:209,1522` | `openssl rand -hex 32` |
| 6 | Google API key | history: `DEPLOYMENT_READINESS_REPORT.md:25,129` | Google Cloud console: delete key, create restricted replacement |
| 7 | DCSP license signing key | history: `products/dcsp/license_check.py:13`, `products/dcsp/scripts/generate_license.py:7`, `CONSOLIDATION_AUDIT.md:342` | generate a new key; re-issue licences signed with the old one |
| 8 | JWTs in `auth_res.json`, `token.txt` | history: commit `cf06c57` (on `origin/master`) | invalidated by rotation 3; also delete branch `master` after the rewrite |
| 9 | SCIM bearer token, field-encryption key (`AETHER_FIELD_KEY`) if ever shared | server `.env` | regenerate; field key rotation needs a re-encrypt migration, do not just replace it |
| 10 | Demo login | was in `launch/*.md`, `deploy/setup-bedrock.sh` (removed in this branch, still in history) | change the demo account password |

Server-side `.env`: update, `systemctl restart aetheros`, run `scripts/post-deploy.sh`.

## 2. Rewrite history (owner decision, needs a force-push; every clone must be re-cloned)

1. Announce a freeze. Merge or close open PRs (PR #1 first).
2. `bash scripts/security/history_rewrite_dryrun.sh` prints the exact command list (it executes nothing).
3. Make the `replacements.txt` it describes OUTSIDE the repo (it holds the old secret values; shred it afterwards).
4. Run the printed commands in a fresh `--mirror` clone, never in your working checkout.
5. Verify with the printed checks (`gitleaks git` clean, `git log --all -- auth_res.json token.txt` empty).
6. Force-push all refs, delete `master` and the stale `worktree-agent-*` branches, ask GitHub support to
   garbage-collect cached views and PR refs (`refs/pull/*` keep old objects until GC).
7. Everyone re-clones. Old forks/clones still contain the secrets: another reason rotation comes first.

## 3. Secret locations (file:line, no values)

Tracked tree (HEAD):
- `plans2.md:13` AWS access key id; `plans2.md:15` VPS root password and IP (owner's file, untouched here)

History only (removed from HEAD, still in `git log --all`):
- `FULL_AUDIT_REPORT_2026_05_09.md:175-177`, `MASTER_SECURITY_AND_HARDENING_REPORT.md:207-209,1505,1522,2802` (commit `6501a8a`)
- `AUDIT_REPORT_20260507.md:126` (commits `03b807c`, `cf06c57`)
- `DEPLOYMENT_READINESS_REPORT.md:25` (`e405cea`), `:129` (`9e6ad1d`)
- `CONSOLIDATION_AUDIT.md:342` (`d1dc09e`)
- `products/dcsp/license_check.py:13`, `products/dcsp/scripts/generate_license.py:7` (`2665893`)
- `auth_res.json:1`, `token.txt:1` (`cf06c57`)

VPS IP (identifier, not a credential, but also to be scrubbed): in history of `README.md`, `CLAUDE.md`,
`gateway/api.py`, `tests/load/locustfile.py`, `scripts/smoke_test.sh`, `deploy/setup-bedrock.sh`,
`docs/STRATEGIC_UPGRADE_PLAN.md`, `launch/*.md`, `AETHEROS_ACQUISITION_DUE_DILIGENCE.md`, `products/dcsp/**`,
`vkatos_deploy/products/aetheros/index.html`, `tests/monitor_live_build.py`, `tests/playwright_full_audit.py`.
Current tree: only `plans2.md`.

Refresh this list any time with `gitleaks git --redact=100 -r report.json .` (values stay redacted).

## 4. Prevent recurrence

- CI runs `scripts/ci/secret_scan.sh` (tree + history, pinned gitleaks, no licence needed).
- Local hook: `gitleaks protect --staged --redact` (add to `.git/hooks/pre-commit`).
- Tests use env vars; code and scripts have no password literal (`tests/test_no_default_credentials.py`).
- After the rewrite remove the `[[allowlists]]` entries that only exist for old history if you want a stricter config.
- Fix the audit docs that claim history was purged (`AETHEROS_ACQUISITION_DUE_DILIGENCE.md` "Security Posture",
  `DUE_DILIGENCE_AUDIT.md` section 7) until section 2 is done.
