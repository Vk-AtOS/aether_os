# AetherOS — Claude Code Rules

These rules apply in every session, automatically, without the user needing to repeat them.

---

## Session Structure

Every session must follow this order:
1. **One clear goal** — if the user hasn't stated one, ask before writing any code
2. **Verify first** — read the relevant files before changing anything
3. **Fix → commit → verify** — one commit per logical fix, not one commit per session
4. **Smoke test before closing** — if anything was deployed, run `./scripts/smoke_test.sh` and report results

Never end a session with "pending verification." Either verify or explicitly state what is unverified and why.

---

## File Size Limits (hard rules)

- **No Python file may exceed 600 lines**
- If a change would push a file over 600 lines, split the file first, then make the change
- If a file already exists over 600 lines, flag it in the session summary
- **Exception:** `phases/p05_frontend/code_writer.py` — template generators, splitting adds no value

Allowed large files (pre-approved, do not split further unless user asks):
- `phases/p05_frontend/code_writer.py` — 35 pure code generators, all in one concern
- `gateway/routers/factory_runs_router.py` — already reduced from 3317 lines

---

## Code Quality Rules

**Never write:**
- `except: pass` — always log: `except Exception as e: logger.warning("...", e)`
- `except Exception: pass` — same rule
- Bare `except:` of any kind without at least a log line

**Always write:**
- Root cause in commit messages, not just what changed
- One sentence explaining WHY in any non-obvious code block
- Imports at the top of the file, never inside functions (unless circular import forces it, and only then with a comment)

**Never do:**
- Fix 10 things in one commit — one logical change per commit
- Add a feature while fixing a bug in the same commit
- Deploy to VPS without running smoke_test.sh first

---

## Architecture Rules

**Module structure — enforce always:**
- Routers: one file per domain, no router file over 400 lines
- Phase agents: `task_agent.py` (orchestration only) + separate files for prompts, helpers, generators
- Business logic never lives in a router — routers call services, services do the work
- No circular imports — if two modules need each other, extract the shared piece to a third module

**When adding a new phase agent:**
- `task_agent.py` — only the `run()` method and gate logic (target: under 300 lines)
- `prompts.py` — all prompt strings and templates
- `helpers.py` — utility functions specific to this phase

**When adding a new router:**
- Max 400 lines
- Auth check on every endpoint — no public endpoints without explicit comment saying why
- All endpoints return typed dicts or Pydantic models, never raw strings

---

## Deploy Rules

Before every VPS deploy:
1. All staged files pass `ast.parse`
2. No file over 600 lines was added
3. Commit message explains the why

After every VPS deploy:
1. Run: `./scripts/smoke_test.sh http://<VPS_IP>`
2. If any test fails: rollback with `git revert`, do not patch forward on a broken deploy
3. Report smoke test results to the user before closing the session

---

## Bug Fix Protocol

When a bug is reported:
1. **Find the root cause first** — do not patch the symptom
2. **Check if the same bug exists elsewhere** — search for the pattern, not just the instance
3. **Write the fix** — minimal change that solves the root cause
4. **Add a regression note** in the commit message so it's findable in git log

When the same bug appears twice:
- It means the first fix was wrong or incomplete
- Stop, trace back to where the real root is, fix that instead

---

## What to Avoid

- **Do not defer refactoring** — if a file hits 600 lines mid-session, split it before continuing
- **Do not fix bugs during feature work** — note them, finish the feature, then fix in a separate commit
- **Do not open new work** when the previous task isn't verified — finish and verify first
- **Do not use AI-generated code without reading it** — every function written must be checked for bare excepts, infinite loops, missing error handling at boundaries
- **Do not push to VPS** without user confirmation — always ask first

---

## Quick Reference

```bash
# Run smoke tests
./scripts/smoke_test.sh http://<VPS_IP>

# Run smoke tests locally
./scripts/smoke_test.sh http://localhost:8000

# Check file sizes
find . -name "*.py" -not -path "*/__pycache__/*" | xargs wc -l | sort -rn | head -20

# Validate all Python syntax
find . -name "*.py" -not -path "*/__pycache__/*" | xargs -I{} python3 -c "import ast; ast.parse(open('{}').read())" 2>&1 | grep -v "^$"
```
