# Release checklist: r3/int to production

Status: PREPARED, NOT EXECUTED. Written 16 Nov 2026 from the code and scripts on r3/int (AetherOS `88659af`, Velaris `b85f76e`). Nothing here has been run against a server, a Docker daemon or a real model: where a step needs one it says UNVERIFIED. This file contains no secret values, only commands and locations. `scripts/ci/check_docs.py` checks that the paths, scripts and environment variables named here exist.

Everything marked OWNER is on the owner register, Jira KAN-204 (A to E in brackets). Do the steps in order. Do not skip a verification: each one ends with the exact output to expect.

Two repositories: AetherOS (`aether_os`) and Velaris (`velaris_knackforge`). Both are on branch `r3/int` and are not pushed. Velaris serves one organisation per deployment (`VELARIS_ORG` equals the AetherOS organisation id).

## 0. Inputs the owner must provide first (KAN-204)

| Needed | KAN-204 | Used in step |
|---|---|---|
| Approval to push `r3/int` of both repos and merge | A1 | 3 |
| Decision where to deploy (VPS with systemd, Compose host, or cloud) | A2, C1 | 7 |
| Approval of the history rewrite (force-push, everyone re-clones) | A3 | 3 |
| Someone to rotate the secrets listed in `docs/security/ROTATION_RUNBOOK.md` section 1 | B1, B2, B3 | 2 |
| A place to keep `VELARIS_VAULT_KEY` and its separate backup | B4 | 5 |
| Model access: a key or a local model (without it nothing runs on a real model) | C2 | 8 |
| Domain, DNS and certificates (app, preview wildcard, Velaris public host) | C3 | 7 |
| Backup destination: bucket or disk, recipient key, schedule | C4 | 6 |
| A Docker host (sandbox, fault injection, acceptance run) | C5 | 8 |
| Mail, Stripe, Atlassian and alert-webhook values where those features are wanted | B6 | 5 |
| Accountant and lawyer sign-off for payroll, tax and HR texts if those features are sold | D1 to D4 | before go-live |

Known blockers found while preparing this list (fix or accept before step 7):

1. `ruff check --select F,E9,B904 .` reports 2 F401 errors in `alembic/versions/merge_r3_heads_merge_r3_integration_heads.py` (KAN-59), so the blocking CI lint step fails. `python3.11 -m ruff check --select F,E9,B904 --fix alembic/versions/merge_r3_heads_merge_r3_integration_heads.py` removes both.
2. Only the `docker-proxy` service mounts the host Docker socket (read-only); the `api` reaches it through `DOCKER_HOST=tcp://docker-proxy:2375` (KAN-65/66/101). The proxy filters endpoints, not request bodies, so a compromised API can still ask for a privileged container: residual risk, to be removed by a remote or rootless runner (KAN-204). `scripts/production_readiness.py` checks the socket is mounted only by the proxy.
3. `core/models.py` is 621 lines, over the 600-line rule and not on the exception list (KAN-57).

## 1. Verify r3/int before anything leaves the machine

AetherOS, from the directory that contains the `aether_os` checkout (the package name must stay `aether_os`):

```bash
cd aether_os
PYTHONPATH=$(cd .. && pwd) python3.11 -m pytest -q tests          # about 9 minutes; expect 0 failed
git checkout -- core/error_registry.json core/knowledge_graph/stage_feedback.jsonl
python3.11 -m ruff check --select F,E9,B904 .                      # expect: All checks passed
PYTHONPATH=$(cd .. && pwd) python3.11 scripts/ci/check_docs.py     # expect: check_docs: 0 problem(s)
python3.11 -m alembic heads                                        # expect exactly one line: merge_r3_heads (head)
python3.11 scripts/production_readiness.py                         # expect no FAIL except the ones listed above; read the UNVERIFIED lines
```

Velaris, from the repository root:

```bash
python3.11 -m pytest -q                                            # about 3 minutes; expect 0 failed
python3.11 -m ruff check --select F,E9,B904 .
python3.11 tools/check_structure.py
python3.11 tools/gen_agent_docs.py --check
```

If any command fails, stop: nothing below is safe on a red build.

## 2. Rotate secrets (OWNER, before the history rewrite) [B1, B2, B3]

Rotation is what protects you; a history rewrite only hides copies. Follow `docs/security/ROTATION_RUNBOOK.md` section 1 in its order (VPS password, AWS key, `AETHER_SECRET_KEY`, admin password, `AETHER_ONE_ZT_SECRET`, Google key, DCSP licence key, JWTs, SCIM token and `AETHER_FIELD_KEY` handling, demo login). Generators for the new values:

```bash
openssl rand -hex 32                      # AETHER_SECRET_KEY, AETHER_ONE_ZT_SECRET, AETHER_PREVIEW_SECRET, VELARIS_API_SECRET
openssl rand -hex 24                      # POSTGRES_PASSWORD, REDIS_PASSWORD, METRICS_API_KEY
```

Special cases:

* `AETHER_FIELD_KEY` encrypts stored columns. Do NOT just replace it on a database that holds data: a new key makes existing values unreadable (the runbook says a re-encrypt migration is needed). Keep the current key unless it was exposed, and then plan the re-encrypt separately.
* `plans2.md` line 13 still names the start of an AWS key in the tracked tree [B2]: stop tracking or redact the file in the same change set.
* After editing the server `.env`: `systemctl restart aetheros` and `bash scripts/post-deploy.sh http://127.0.0.1:8000` (needs `AETHER_ADMIN_PASS`). Run `bash scripts/harden_env.sh` so `.env` stays mode 0600.

## 3. Push, merge, then rewrite history (OWNER) [A1, A3, A4]

1. Announce a freeze. Push `r3/int` of both repositories, open the pull requests, review, merge to the main branch.
2. Only after the merge, if the owner approved A3: `bash scripts/security/history_rewrite_dryrun.sh` prints the exact command list (it executes nothing). Follow `docs/security/ROTATION_RUNBOOK.md` section 2 (mirror clone, replacements file kept outside the repository and shredded afterwards, verify with `bash scripts/ci/secret_scan.sh`, force-push all refs, delete `master` and the stale `worktree-agent-*` branches, everyone re-clones).
3. Deploy only from the rewritten, merged main branch. Do not deploy from an old clone.

Expected: `bash scripts/ci/secret_scan.sh` finishes clean (the gitleaks CI job turns green only after steps 2 and 3).

## 4. Prepare production configuration

AetherOS `.env` (never committed; `.env.example` lists every variable). Compose refuses to start without these: `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `AETHER_FIELD_KEY`, `CORS_ORIGINS`, `FRONTEND_URL`, `AETHER_ADMIN_PASS`, `AETHER_PREVIEW_ORIGIN`, `AETHER_PREVIEW_SECRET`. Also set `ENVIRONMENT=production` (then the API refuses to start without Redis and without `AETHER_FIELD_KEY`, and rate-limit or revocation-store failures answer 503 instead of passing) and one LLM provider (`PRIMARY_LLM` plus its key, or a local model). RS256 token signing needs `AETHER_JWT_PRIVATE_KEY_B64` and `AETHER_JWT_PUBLIC_KEY_B64` (otherwise the HS256 fallback is only for CI).

Velaris link (both repositories), generated once and kept in the secret store:

```bash
mkdir -p secrets && openssl genpkey -algorithm ED25519 -out secrets/velaris_identity.pem
openssl pkey -in secrets/velaris_identity.pem -pubout -out secrets/velaris_identity.pub.pem
```

* AetherOS `.env`: `VELARIS_API_URL`, `VELARIS_API_SECRET`, `VELARIS_IDENTITY_PRIVATE_KEY_PEM` (the private key text) and `VELARIS_SMOKE_ORG` (the organisation id; `deploy/deploy.sh` requires it when `VELARIS_API_URL` is set).
* Velaris environment: `VELARIS_ORG` (same organisation id), `VELARIS_API_SECRET` (same value, at least 32 bytes), `VELARIS_IDENTITY_PUBLIC_KEY` (path of `velaris_identity.pub.pem`, mounted read-only), `VELARIS_DATA` (volume, mode 0700), `VELARIS_VAULT_KEY_FILE` (step 5). Both Velaris processes (`python -m velaris.api`, `python -m velaris.api.public`) run ONE worker each; do not add `--workers`.
* Optional: `VELARIS_TRACE_ANCHOR_FILE` on another disk or host, so a rollback of the whole data directory cannot shorten the audit trail unseen.

## 5. Velaris encryption key (OWNER) [B4]

The master key lives OUTSIDE `VELARIS_DATA`. A restore without it is unreadable by design, so the key backup is part of the release.

```bash
install -d -m 0700 -o velaris -g velaris /etc/velaris
python3.11 -c "from velaris.core import vault; print(vault.new_key())" > /etc/velaris/vault.key
chown velaris:velaris /etc/velaris/vault.key   # the units run as User=velaris; a root-owned 0600 key is unreadable
chmod 0600 /etc/velaris/vault.key        # the file must not be inside VELARIS_DATA
```

Copy `/etc/velaris/vault.key` to the owner's secret store NOW, separately from any data backup. Expected: with the key present both Velaris services start; with it missing the API answers 503 and the personal-data stores refuse (fail closed).

## 6. Back up before touching production data

```bash
# AetherOS (PostgreSQL); needs DATABASE_URL in the environment or .env
bash scripts/backup_db.sh
# Velaris (stop both services for the snapshot, or pass --lock-stores)
python3.11 deploy/backup/velaris_backup.py backup --data /var/lib/velaris --out /var/backups/velaris --lock-stores
```

The Velaris command is in the Velaris repository (`deploy/backup/velaris_backup.py`). Encrypt the archive before it leaves the host (`age` or `gpg`, see Velaris `deploy/README.md`) and keep the `.sha256` sidecar. Practise one restore before the release: `python3.11 scripts/restore_drill.py --dump <dump.sql.gz> --admin-url <postgres admin url>` for AetherOS and `deploy/backup/restore_drill.py` for Velaris. These backups are the ONLY way back after step 7: sealed Velaris data cannot be read by the previous release.

## 7. Deploy in one maintenance window

Order: Velaris first, then AetherOS. Reason: `deploy/deploy.sh` ends with a signed request from AetherOS to Velaris (`scripts/velaris_smoke.py`) and fails the deploy if Velaris does not accept it, and Velaris refuses callers that send no roles, so both sides must be the new release.

### 7a. Velaris upgrade and the plaintext migration window

Run on the Velaris host. `VELARIS_DATA` and `VELARIS_VAULT_KEY_FILE` as in step 4 and 5.

```bash
systemctl stop velaris-public velaris-api                      # or the compose / Kubernetes equivalent
# 1. audit trail: re-sign the head after verifying the whole chain (refuses if entries are missing)
VELARIS_DATA=/var/lib/velaris VELARIS_VAULT_KEY_FILE=/etc/velaris/vault.key python3.11 -m velaris.intel trace-rebaseline
# 2. rows without an organisation: report first, then apply (VELARIS_ORG must be set)
python3.11 -m velaris.core.backfill_org
python3.11 -m velaris.core.backfill_org --apply
# 3. open the plaintext migration window (default 24 hours, at most 168; needs the master key)
python3.11 -m velaris.core.vault start-migration 24
# 4. start both services ONCE with the switch; stores seal their old plaintext when first read
VELARIS_VAULT_ALLOW_PLAINTEXT=1 systemctl start velaris-api velaris-public
```

During the window the mail, chat, memory and docs databases seal their existing plaintext (and VACUUM), JSON state files and records are sealed on first load, and HR sqlite databases (recruitment, onboarding, leave, performance) are sealed whole-file by ONE process. Exercise each store once so it seals: open the dashboard Velaris pages for HR, mail, chat and memory as an administrator and read at least one record in each. Then close the window:

```bash
python3.11 -m velaris.core.vault end-migration                 # deletes <VELARIS_DATA>/.vault_plaintext_open
systemctl restart velaris-api velaris-public                   # WITHOUT VELARIS_VAULT_ALLOW_PLAINTEXT
python3.11 -m velaris.intel trace                              # expect: the chain verifies
```

Check that nothing plaintext is left: after the restart without the switch, every store must open. A store that still held plaintext now raises `PlaintextRefused` (visible as errors in the log and as failed reads in the dashboard). If that happens, run `start-migration` again, repeat the window for that store, and end it again. Do not leave a window open: the token expires by itself, but end it as soon as the check passes.

One-time items to finish in the same window [B5]:

* `SECRETS_VAULT` agent secrets written before encryption: with `VELARIS_VAULT_ALLOW_LEGACY=1` call `migrate_legacy()` once (it seals the old secrets and writes a marker), unset the variable, then delete `<VELARIS_DATA>/agents/SECRETS_VAULT/vault.key` after checking the secrets still read.
* Old sqlite files left in the source tree, working directory or `/tmp` are copied once into `VELARIS_DATA/agents/<AGENT>/` (set `VELARIS_ADOPT_LEGACY=0` to stop that). The originals stay in place: delete them after checking.
* Search in mail and chat is whole-word after sealing (the index holds HMAC tokens). Tell users.

### 7b. AetherOS database and application

Database migration is one command everywhere (`scripts/db_migrate.py`): `alembic upgrade head` on an existing database, create-and-stamp on an empty one, then the audit-ledger triggers are re-applied (this also heals databases bootstrapped by an older release). It needs `AETHER_FIELD_KEY` in the environment.

Path A, VPS with systemd (the existing production path):

```bash
cd /home/aether_os                    # the install directory; the path is in deploy/aetheros.service
bash deploy/deploy.sh --domain <app domain>
```

`deploy/deploy.sh` runs, in order: `git pull --ff-only`, dependency install, `scripts/db_migrate.py` (a failed migration stops the deploy), nginx domain setup, dashboard rebuild if `dashboard/` changed, service reload, `/health` check, the signed Velaris smoke test, and `scripts/post-deploy.sh` (refreshes the Guardian file-integrity baseline).

Path B, Docker Compose (the `migrate` service runs `db_migrate.py` first and `api` waits for it):

```bash
docker compose up -d --build
docker compose --profile velaris up -d        # only if Velaris runs in the same Compose project (needs VELARIS_IMAGE, VELARIS_ORG, VELARIS_API_SECRET)
```

Path C, cloud (Terraform in `deploy/terraform/aws`, Helm chart in `helm/aetheros`): needs the cloud decision [C1] and account access. `terraform plan` goes to the owner for review; never `apply` without approval; then `helm upgrade --install` with the secrets supplied from the secret manager. UNVERIFIED: neither `terraform plan` nor `helm template` has been run (no account, no helm here).

nginx and TLS: `deploy/nginx.conf` for the app, `deploy/nginx_velaris_public.conf` for the Velaris public host; `nginx -t` before reload (UNVERIFIED, never run here). Preview hosts need the wildcard certificate and DNS (`docs/ops/PREVIEW_ORIGINS.md`) [C3].

## 8. Smoke tests after the deploy

```bash
curl -sf http://127.0.0.1:8000/healthz                        # liveness, no dependencies
curl -sf http://127.0.0.1:8000/readyz                         # readiness: Postgres and Redis up; degraded components are named
./scripts/smoke_test.sh https://<app domain>                  # needs AETHER_ADMIN_PASS; expect exit 0, no FAIL lines
python3.11 scripts/velaris_smoke.py --org <organisation id>   # needs VELARIS_API_URL, VELARIS_API_SECRET, VELARIS_IDENTITY_PRIVATE_KEY_PEM; expect exit 0
python3.11 scripts/production_readiness.py --live https://<app domain>
```

Then check by hand: sign in, start one small build, open a Velaris page (HR or mail) as a member, approve and reject one Prime request as a second person, and look at `/readyz` while one dependency is stopped on STAGING (never on production): `python3.11 scripts/fault_injection.py --run` needs Docker and Compose [C5]. Before selling, run the recorded acceptance run on staging with a real model: `python3.11 scripts/acceptance_run.py --velaris` (needs a model key, Docker and a running stack [C2, C5]; without them it prints SKIP and exits 0, which is NOT a pass).

Expected `production_readiness.py` end state: no FAIL; every UNVERIFIED line (access reviews, incident contacts, restore on real data, data residency) has an owner and a date. Paste the output into the Confluence page for KAN-53.

## 9. Rollback

* Code: the procedure in `RUNBOOK.md` section 7 (`git checkout <previous commit>`, `systemctl restart aetheros`). A database migration is additive; `alembic downgrade -1` was not verified for every revision, so prefer restoring the backup from step 6 over downgrading.
* Velaris: stop both services, restore the archive from step 6 (`python3.11 deploy/backup/velaris_backup.py restore --archive <archive> --target /var/lib/velaris --force`), start the PREVIOUS release. A restore needs the same `vault.key` that sealed the data in the archive. Do not start the previous release on data that was already sealed by this release.
* Rotated secrets are not rolled back.

## 10. Close

1. `python3.11 -m velaris.core.vault end-migration` has been run (step 7a) and no `.vault_plaintext_open` file exists in `VELARIS_DATA`.
2. The key backups (step 5) and the encrypted backups (step 6) exist outside the host.
3. `docs/RELEASE_CHECKLIST.md` is updated with what actually happened (dates, commit hashes, UNVERIFIED items now verified).
4. Update the Jira tickets named above with the result; the owner decides status changes.

## What is NOT verified in this checklist

No step was run on a server. `docker build`, `docker compose up`, `helm template`, `terraform plan`, `nginx -t`, `systemd-analyze verify`, the fault-injection run, the acceptance run, the Velaris plaintext migration on a real data directory, and every `--live` probe are untested here. The migration window procedure is read from `velaris/core/vault.py`, `velaris/agentkit/state.py` and Velaris `deploy/README.md`; rehearse it on a copy of the production data directory before the real one.
