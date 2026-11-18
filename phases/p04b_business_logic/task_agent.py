"""P04b Business Logic Layer — Workflows, notifications, payments."""
from __future__ import annotations
import html
import json
import logging
import re
import ast
from pathlib import Path
from typing import Any, Dict, List

from aether_os.phases.base import TaskResult
from aether_os.phases.p04b_business_logic.logic_generators import (
    generate_workflow_sm,
    generate_email_service,
    generate_stripe_service,
    generate_s3_service,
)
from aether_os.phases.p04b_business_logic.safe_names import check_logic_names, write_inside
from aether_os.phases.p04b_business_logic.helpers import (
    _FALLBACK_WORKFLOW_ENGINE,
    _FALLBACK_BUSINESS_RULES,
    get_responsive_email_template,
    recover_domain_ir,
)

logger = logging.getLogger(__name__)


def _validate_python_output(code: str, filename: str) -> list[str]:
    errors = []
    try:
        ast.parse(code)
    except SyntaxError as e:
        errors.append(f"{filename}: SyntaxError at line {e.lineno}: {e.msg}")
        return errors
    # Check for relative imports
    if "from ." in code:
        errors.append(f"{filename}: contains relative imports — must use absolute imports")
    return errors


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Generate business logic: StateMachines, EmailTriggers, PaymentScaffold.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Read IR and context — with inline recovery if DomainIR is missing (Problem 27 fix)
    ir_path = phase_input.input_data.get("domain_ir_path")
    ir_data: dict = {}

    if ir_path:
        ir_file = Path(ir_path)
        if ir_file.exists():
            try:
                ir_data = json.loads(ir_file.read_text())
            except Exception as exc:
                logger.warning("p04b: failed to parse domain_ir at %s: %s", ir_path, exc)
                ir_data = {}

    if not ir_data:
        # DomainIR is None, missing, or unreadable — attempt inline recovery
        try:
            ir_data = await recover_domain_ir(phase_input, output_dir)
        except Exception as exc:
            logger.error("p04b: inline DomainIR recovery failed fatally: %s", exc)
            return TaskResult(
                output_path=str(output_dir),
                confidence=0.0,
                success=False,
                issues=[f"DomainIR unavailable and inline recovery failed: {exc}"],
            )

    bad_names = check_logic_names(ir_data)
    if bad_names:     # fail closed before anything is written (KAN-69 G6)
        logger.error("p04b: refusing the IR: %s", bad_names)
        return TaskResult(output_path=str(output_dir), confidence=0.0, success=False, issues=bad_names)

    flags = phase_input.input_data.get("integration_flags", {})
    project_name = phase_input.input_data.get('project_name', 'App')
    domain = phase_input.input_data.get('domain', 'general')

    # Enrich IR workflows with domain knowledge pack transitions when IR is sparse
    _dk = phase_input.input_data.get("domain_knowledge") or {}
    if _dk.get("domain") and _dk["domain"] != "general":
        try:
            from aether_os.core.domain_knowledge.loader import load_pack as _load_pack
            _dk_pack = _load_pack(_dk["domain"])
            if _dk_pack and _dk_pack.workflows and not ir_data.get("workflows"):
                ir_data["workflows"] = [
                    {
                        "name": w.name,
                        "entity": w.entity,
                        "field": w.field,
                        "states": w.states,
                        "transitions": w.transitions,
                        "terminal_states": w.terminal_states,
                    }
                    for w in _dk_pack.workflows
                ]
                logger.info("p04b: injected %d domain workflows from pack=%s",
                            len(_dk_pack.workflows), _dk["domain"])
        except Exception as _dk_exc:
            logger.warning("p04b: domain knowledge workflow injection failed: %s", _dk_exc)

    # Business logic belongs in the running app's src dir (backend_src_dir), not in the phase
    # output dir: state machines written there were never part of the delivered backend.
    _canonical = phase_input.input_data.get("backend_src_dir", "")
    src_dir = Path(_canonical) if _canonical and Path(_canonical).is_dir() else output_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    logger.info("p04b: writing business logic files to %s", src_dir)

    # 2. Logic generation - Workflows
    workflow_dir = src_dir / "workflows"
    workflow_dir.mkdir(exist_ok=True)
    (workflow_dir / "__init__.py").touch()

    for wf in ir_data.get("workflows", []):
        entity = wf.get("entity", "Entity")
        sm_code = generate_workflow_sm(entity, wf)
        write_inside(workflow_dir, f"{entity.lower()}_sm.py", sm_code)

    # 3. Logic generation - Integrations (src_dir was resolved above)

    if flags.get("needs_email"):
        (src_dir / "email_service.py").write_text(generate_email_service())

    if flags.get("needs_payments"):
        (src_dir / "stripe_service.py").write_text(generate_stripe_service())

    if flags.get("needs_file_upload"):
        (src_dir / "s3_service.py").write_text(generate_s3_service())

    # Ensure email_triggers.py is always generated to avoid ImportError in StateMachines
    notif_dir = src_dir / "notifications"
    notif_dir.mkdir(exist_ok=True)

    email_triggers_code = """\"\"\"Auto-generated email triggers.\"\"\"
async def trigger_notification(obj, new_status: str):
    # Email not configured for this app
    pass
"""
    if flags.get("needs_email"):
        email_triggers_code = f"""\"\"\"Auto-generated email triggers for {project_name}.\"\"\"
import logging
try:
    from src.email_service import EmailService
    email_service = EmailService()
except ImportError:
    email_service = None

logger = logging.getLogger(__name__)

async def trigger_notification(obj, new_status: str):
    if not email_service:
        return
    entity_name = obj.__class__.__name__
    logger.info("Triggering notification for %s status: %s", entity_name, new_status)
    try:
        # Map status to template and recipient
        await email_service.send(
            to="admin@example.com",
            subject=f"Status Update: {{entity_name}} is now {{new_status}}",
            template_name=f"{{new_status}}.html",
            context={{"obj": obj, "new_status": new_status}}
        )
    except Exception as e:
        logger.error("Failed to trigger email notification: %s", e)
"""
    (notif_dir / "email_triggers.py").write_text(email_triggers_code)

    # 4. Email Templates — co-located with the app (src_dir.parent/templates/emails)
    if flags.get("needs_email"):
        email_tmpl_dir = src_dir.parent / "templates" / "emails"
        email_tmpl_dir.mkdir(parents=True, exist_ok=True)

        welcome_body = """
                    <h2 style="color: #4f46e5; margin-top: 0;">Welcome!</h2>
                    <p>We're excited to have you on board. Your account is ready to go.</p>
                    <a href="#" class="button">Get Started</a>
        """
        (email_tmpl_dir / "welcome.html").write_text(
            get_responsive_email_template(project_name, welcome_body)
        )

        pwd_reset_body = """
                <h2>Password Reset</h2>
                <p>Click the link below to reset your password:</p>
                <a href="#" class="button" style="background: #ef4444;">Reset Password</a>
        """
        (email_tmpl_dir / "password_reset.html").write_text(
            get_responsive_email_template(project_name, pwd_reset_body)
        )

        verification_body = """
                <h2>Verify Your Email</h2>
                <p>Please confirm your email address by clicking the link below:</p>
                <a href="#" class="button" style="background: #10b981;">Verify Email</a>
        """
        (email_tmpl_dir / "email_verification.html").write_text(
            get_responsive_email_template(project_name, verification_body)
        )

        for notif in ir_data.get("notifications", []):
            event = notif.get("event", "notification")
            tmpl_body = f"""
                    <h2>Notification: {event.replace('_', ' ').capitalize()}</h2>
                    <p>{html.escape(str(notif.get('template', 'No details provided.')))}</p>
            """
            write_inside(email_tmpl_dir, f"{event}.html", get_responsive_email_template(project_name, tmpl_body))

    # ── LLM Call A — Approval Workflow Engine ────────────────────────────────
    domain = phase_input.input_data.get("domain", "general")
    raw_input = phase_input.input_data.get("raw_input", "")[:2000]
    entities_summary = ", ".join(
        e.get("name", "") for e in ir_data.get("entities", [])[:10] if e.get("name")
    ) or "User, Item"
    workflows_summary = json.dumps(ir_data.get("workflows", [])[:5], indent=2) if ir_data.get("workflows") else "[]"

    workflow_engine_code = _FALLBACK_WORKFLOW_ENGINE.format(
        domain=domain, project_name=project_name
    )
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()

        prompt_a = f"""\
You are a senior Python backend engineer. Design approval workflow state machines for a \
{domain} application called "{project_name}".

Project description: {raw_input}
Entities: {entities_summary}
Existing workflows from domain model: {workflows_summary}

For each entity that requires approval flows (expense reports need manager approval, \
contracts need legal sign-off, invoices need finance approval, leave requests need HR, etc.):
- Define states (e.g. DRAFT, PENDING_APPROVAL, APPROVED, REJECTED, CANCELLED)
- Define transitions between states with actor and conditions
- Define who can trigger each transition

Generate a complete Python module `services/workflow_engine.py` with:
1. A `WorkflowState` enum with all states
2. A `WorkflowTransition` dataclass with: from_state, to_state, actor, condition, action
3. A `WorkflowEngine` class with:
   - `WORKFLOWS: dict` — maps entity name to list of WorkflowTransition
   - `async def transition(self, db, entity_type, entity_id, new_state, actor_role, actor_id)` — validates and applies transition
   - `def get_available_transitions(self, entity_type, current_state, actor_role)` — returns allowed next states

Return ONLY valid Python code. No markdown fences, no explanation."""

        result_a = await llm.call(prompt_a, task_type="code_generation", max_tokens=12000)
        if result_a and len(result_a.strip()) > 200:
            result_a = re.sub(r"^```(?:python)?\s*\n?", "", result_a.strip())
            result_a = re.sub(r"\n?```\s*$", "", result_a.strip())
            try:
                ast.parse(result_a)
                workflow_engine_code = result_a
                logger.info("p04b: LLM workflow engine generated (%d chars)", len(workflow_engine_code))
            except SyntaxError as _syn:
                logger.warning("p04b: LLM workflow engine SyntaxError: %s — using fallback", _syn)
    except Exception as exc:
        logger.warning("p04b: LLM Call A (workflow engine) failed: %s — using fallback", exc)

    _wf_errs = _validate_python_output(workflow_engine_code, "workflow_engine.py")
    if _wf_errs:
        for _e in _wf_errs:
            logger.warning("p04b: workflow_engine.py validation error: %s", _e)
        logger.warning("p04b: skipping workflow_engine.py write due to validation errors")
    else:
        (src_dir / "workflow_engine.py").write_text(workflow_engine_code)

    # ── LLM Call B — Business Rules + Calculations ────────────────────────────
    business_rules_code = _FALLBACK_BUSINESS_RULES.format(
        domain=domain, project_name=project_name
    )
    try:
        from aether_os.core.llm.client import get_llm_client
        llm = get_llm_client()

        prompt_b = f"""\
You are a senior Python backend engineer. Define the core business rules and calculation \
logic for a {domain} application called "{project_name}".

Project description: {raw_input}
Entities: {entities_summary}

Include in the Python module `services/business_rules.py`:
1. Validation rules beyond basic type checking (e.g. invoice amount must be positive and \
   within budget, appointment cannot be in the past)
2. Calculation formulas appropriate for {domain} (pricing, scoring, eligibility, totals, taxes, \
   discounts, commissions)
3. Conditional logic (e.g. if order total > X apply discount Y)
4. Business constraints (e.g. max concurrent bookings, minimum order amount)

Structure as a `BusinessRules` class with:
- Class methods for each business rule / calculation
- Each method has a docstring explaining the rule
- Methods raise `ValueError` with descriptive messages when rules are violated
- Calculation methods return the computed value

Return ONLY valid Python code. No markdown fences, no explanation."""

        result_b = await llm.call(prompt_b, task_type="code_generation", max_tokens=12000)
        if result_b and len(result_b.strip()) > 200:
            result_b = re.sub(r"^```(?:python)?\s*\n?", "", result_b.strip())
            result_b = re.sub(r"\n?```\s*$", "", result_b.strip())
            try:
                ast.parse(result_b)
                business_rules_code = result_b
                logger.info("p04b: LLM business rules generated (%d chars)", len(business_rules_code))
            except SyntaxError as _syn2:
                logger.warning("p04b: LLM business rules SyntaxError: %s — using fallback", _syn2)
    except Exception as exc:
        logger.warning("p04b: LLM Call B (business rules) failed: %s — using fallback", exc)

    _br_errs = _validate_python_output(business_rules_code, "business_rules.py")
    if _br_errs:
        for _e in _br_errs:
            logger.warning("p04b: business_rules.py validation error: %s", _e)
        logger.warning("p04b: skipping business_rules.py write due to validation errors")
    else:
        (src_dir / "business_rules.py").write_text(business_rules_code)

    # 5. Patch main.py to import business logic services (only if main.py exists).
    #    Current generators export classes (EmailService, StripeService, S3Service),
    #    not FastAPI routers — so we add import-only lines for each generated module.
    #    No include_router calls are injected because no routers are defined.
    main_py = src_dir / "main.py"
    if main_py.exists():
        try:
            content = main_py.read_text()
            new_imports: list[str] = []

            if (src_dir / "email_service.py").exists() and "email_service" not in content:
                new_imports.append("from email_service import EmailService  # p04b: transactional email")

            if (src_dir / "stripe_service.py").exists() and "stripe_service" not in content:
                new_imports.append("from stripe_service import StripeService  # p04b: payments")

            if (src_dir / "s3_service.py").exists() and "s3_service" not in content:
                new_imports.append("from s3_service import S3Service  # p04b: file storage")

            if (src_dir / "workflow_engine.py").exists() and "workflow_engine" not in content:
                new_imports.append("from workflow_engine import WorkflowEngine  # p04b: approval workflows")

            if (src_dir / "business_rules.py").exists() and "business_rules" not in content:
                new_imports.append("from business_rules import BusinessRules  # p04b: business rules")

            if new_imports:
                import_block = "\n".join(new_imports)
                lines = content.splitlines(keepends=True)
                last_import_idx = -1
                for idx, line in enumerate(lines):
                    if re.match(r"^(?:from|import)\s", line):
                        last_import_idx = idx
                if last_import_idx >= 0:
                    lines.insert(last_import_idx + 1, import_block + "\n")
                    patched = "".join(lines)
                else:
                    patched = import_block + "\n" + content

                try:
                    ast.parse(patched)
                    main_py.write_text(patched)
                    logger.info(
                        "p04b: patched main.py with %d business logic imports", len(new_imports)
                    )
                except SyntaxError as _syn3:
                    logger.warning(
                        "p04b: main.py patch produced SyntaxError (%s) — skipping injection", _syn3
                    )
        except Exception as exc:
            logger.warning("p04b: main.py patching failed: %s — skipping", exc)

    # 6. Save artifacts
    email_tmpl_count = 0
    _tmpl_dir = src_dir.parent / "templates" / "emails"
    if _tmpl_dir.exists():
        email_tmpl_count = len(list(_tmpl_dir.glob("*.html")))

    summary = {
        "workflows": len(ir_data.get("workflows", [])),
        "integrations": [k for k, v in flags.items() if v],
        "email_templates": email_tmpl_count,
        "llm_workflow_engine": workflow_engine_code != _FALLBACK_WORKFLOW_ENGINE.format(
            domain=domain, project_name=project_name
        ),
        "llm_business_rules": business_rules_code != _FALLBACK_BUSINESS_RULES.format(
            domain=domain, project_name=project_name
        ),
        "status": "generated",
        "src_dir": str(src_dir),
    }
    out_json = output_dir / "business_logic.json"
    out_json.write_text(json.dumps(summary, indent=2))

    return TaskResult(
        output_path=str(out_json),
        confidence=0.9,
        metadata=summary,
        success=True,
    )
