# AetherOS — Demo Ready

## Critical Fixes Applied

### Fix 1 — DCSP wired into orchestrator pipeline
**File:** `orchestrator/pipeline.py` — `_phase_cicd()`  
Previously returned `{"status": "skipped"}`. Now calls `run_repair()` from
`phases/p08_cicd/pipeline.py` with these behaviours:
- If no CI failure in context → skips gracefully (status: skipped)
- If test failures exist → writes generated code to a temp dir, calls `run_repair()`
- If `escalated=True` → triggers `decide_for_risk("HIGH")` approval gate, sets
  `ctx.approval_ticket_id` and `ctx.human_approved = False`
- If `success=True` → writes patch diff to `<output_dir>/<project>/<run_id>/cicd_patch.diff`

**File:** `phases/p08_cicd/gate.py` — updated `validate()` to check:
- `status == "repaired"` → verifies `cicd_patch.diff` exists on disk
- `status == "escalated"` → returns `passed=False` with approval reason
- `status == "skipped"` → passes through cleanly

### Fix 2 — DCSP import paths
All files in `phases/p08_cicd/` already use `aether_os.phases.p08_cicd.*` — no
`src.*` imports remained. Verified with import check.

### Fix 3 — Bootstrap logger names
Updated `logging.getLogger("aetherone.*")` references to `logging.getLogger("aether_os.*")`:
- `core/bootstrap/runtime_manager.py` → `aether_os.runtime`
- `core/bootstrap/offline_guard.py`   → `aether_os.offline_guard`
- `core/bootstrap/safe_mode.py`       → `aether_os.safe_mode`

---

## Validation Results

| Step | Command | Result |
|------|---------|--------|
| 1 | `python -c "from aether_os.phases.p08_cicd.pipeline import run_repair"` | **PASS** |
| 2 | `python -c "from aether_os.core.bootstrap.runtime_manager import RuntimeManager"` | **PASS** |
| 3 | `python3 -m pytest aether_os/tests/ -v --asyncio-mode=auto` | **153/153 PASS** |
| 4 | `python3 aether_os/main.py status` | **All components healthy** |
| 5 | `python3 aether_os/main.py demo` | **Runs without errors** |
| 6 | Gemini provider smoke test | **PASS — key valid, quota exhausted (free tier), fallback → Ollama** |

---

## LLM Provider Status

**Active provider priority (as of this build):**

| Tier | Provider | Key | Status |
|------|----------|-----|--------|
| 1 | Anthropic Claude | `ANTHROPIC_API_KEY` | Ready (set key to activate) |
| 2 | Google Gemini | `GOOGLE_API_KEY` | **Wired** — key `AIzaSyBBC8...` authenticated, free-tier quota exhausted. Enable billing at console.cloud.google.com or wait for daily reset. |
| 3 | Ollama | localhost:11434 | Active fallback (deepseek-coder running) |

**Model routing:**
- Heavy tasks (`code_generation`, `security_scan`, `architecture`, `review`, `testing`):
  Anthropic → `claude-sonnet-4-6` · Gemini → `gemini-2.5-pro`
- Light tasks (`requirements`, `documentation`, `intake`, `portal`):
  Anthropic → `claude-haiku-4-5-20251001` · Gemini → `gemini-2.0-flash`

**Provider selected per call is logged:** `LLM call: provider=gemini model=gemini-2.0-flash task=documentation`

**`client.last_provider`** attribute set after each call: `"anthropic"` | `"gemini"` | `"ollama"`

---

## How to trigger a real CI repair demo

Set an Anthropic API key, then run:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cd /Users/apple/Desktop

# Full pipeline demo (NL → code → CI repair)
python3 aether_os/main.py demo --req "Build a FastAPI user auth service with JWT"

# Direct DCSP repair (inject a real CI log)
python3 - <<'EOF'
from aether_os.phases.p08_cicd.pipeline import run_repair

log = """
FAILED tests/test_auth.py::test_login - AssertionError
Traceback (most recent call last):
  File "tests/test_auth.py", line 42, in test_login
    assert response.status_code == 200
AssertionError: assert 401 == 200
"""

result = run_repair(
    log_content=log,
    root_dir=".",
    historical_records=[],
    ast_index=None,
)
print(f"Success: {result.success}")
print(f"Confidence: {result.confidence:.0%}")
print(f"Explanation: {result.explanation}")
print(f"Escalated: {result.escalated}")
if result.patch_diff:
    print(f"Patch:\n{result.patch_diff}")
EOF
```

---

## What a buyer sees when they run the demo

```
python3 aether_os/main.py demo
```

1. **Banner** — AetherOS v1.0.0, Anthropic claude-sonnet-4-6, 10-phase pipeline
2. **Live phase table** ticking through all 10 phases:
   - Requirements → Architecture → Scaffolding → Codegen → Review
   - Security → Testing → CI/CD → Docs → Packaging
3. **CI/CD phase** now live — if tests failed, DCSP runs repair automatically:
   - Green: patch found, written to disk, pipeline continues
   - Yellow: escalated, human approval ticket created, pipeline halts for review
4. **Final result panel** — status COMPLETE, run ID, duration, output directory
5. **Phase summary table** — each phase with pass/fail, confidence %, duration
6. **Output directory** — fully packaged: `main.py`, `README.md`, `tests/`, `cicd_patch.diff`

The buyer can then inspect the output at `~/.aether_os/outputs/<project>/<run_id>/`.
