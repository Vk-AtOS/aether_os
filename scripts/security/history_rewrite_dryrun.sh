#!/usr/bin/env bash
# DRY RUN ONLY. Prints the git filter-repo command list for the history rewrite (KAN-175).
# It never runs filter-repo, never pushes, never touches this repo. Read docs/security/ROTATION_RUNBOOK.md first.
# Usage: bash scripts/security/history_rewrite_dryrun.sh [git@github.com:ORG/REPO.git]
set -euo pipefail
REMOTE="${1:-<remote-url>}"
cat <<EOF
# 0. prerequisites: pip install git-filter-repo ; all secrets rotated (runbook section 1)
# 1. fresh mirror clone, outside any working checkout
git clone --mirror $REMOTE aether_os-rewrite.git && cd aether_os-rewrite.git

# 2. replacements file kept OUTSIDE the repo; one rule per line, e.g.
#      <old-secret-value>==>REDACTED
#      regex:SECRET_KEY = "vkat[^"]*"==>SECRET_KEY = "REDACTED"
#    (fill in old values yourself; never commit this file; shred it afterwards)
#    REPL=/secure/path/replacements.txt

# 3. drop files that exist only to hold secrets / old reports
git filter-repo --force \\
  --invert-paths \\
  --path auth_res.json --path token.txt \\
  --path FULL_AUDIT_REPORT_2026_05_09.md \\
  --path MASTER_SECURITY_AND_HARDENING_REPORT.md \\
  --path AUDIT_REPORT_20260507.md \\
  --path DEPLOYMENT_READINESS_REPORT.md \\
  --path CONSOLIDATION_AUDIT.md

# 4. scrub remaining values (plans2.md, products/dcsp, VPS IP) in every commit
git filter-repo --force --replace-text "\$REPL"

# 5. verify, nothing may be reported
git log --all --oneline -- auth_res.json token.txt | wc -l        # expect 0
gitleaks git --redact=100 --no-banner .                            # expect "no leaks found"
git for-each-ref | grep -E 'master|worktree-agent' || true         # stale branches to delete

# 6. publish (OWNER ONLY, after announcing the freeze)
git remote add origin $REMOTE
git push --force --mirror origin
# then: delete branch master, ask GitHub support to purge cached refs/pull/*, everyone re-clones
EOF
