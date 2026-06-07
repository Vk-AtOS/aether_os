"""P04b Business Logic Layer — Workflows, notifications, payments."""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List
import json

from aether_os.phases.base import TaskResult
from phases.p04b_business_logic.logic_generators import (
    generate_workflow_sm,
    generate_email_service,
    generate_stripe_service,
    generate_s3_service,
)

logger = logging.getLogger(__name__)

def _get_responsive_email_template(project_name: str, body_content: str, primary_color: str = "#4f46e5") -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; background: #f4f4f4; }}
    .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; }}
    .header {{ background: {primary_color}; padding: 24px; text-align: center; }}
    .body {{ padding: 32px; line-height: 1.6; color: #333333; }}
    .button {{ display: inline-block; padding: 12px 24px; background: {primary_color}; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; margin-top: 20px; }}
    .footer {{ padding: 16px; text-align: center; font-size: 12px; color: #888; }}
    @media (max-width: 600px) {{ .container {{ width: 100% !important; }} }}
  </style>
</head>
<body>
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center">
      <table class="container" cellpadding="0" cellspacing="0">
        <tr><td class="header"><h1 style="color:#fff;margin:0;">{project_name}</h1></td></tr>
        <tr><td class="body">{body_content}</td></tr>
        <tr><td class="footer">
          <p>{project_name} · <a href="#" style="color:#888;">Unsubscribe</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


async def run(phase_input: Any, memory_ctx: List[Dict], output_dir: Path) -> TaskResult:
    """
    Generate business logic: StateMachines, EmailTriggers, PaymentScaffold.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Read IR and context
    ir_path = phase_input.input_data.get("domain_ir_path")
    if not ir_path:
        return TaskResult(output_path=str(output_dir), confidence=0.0, success=False, issues=["Missing DomainIR"])
    ir_data = json.loads(Path(ir_path).read_text())
    flags = phase_input.input_data.get("integration_flags", {})
    project_name = phase_input.input_data.get('project_name', 'App')
    
    # 2. Logic generation - Workflows
    workflow_dir = output_dir / "workflows"
    workflow_dir.mkdir(exist_ok=True)
    
    for wf in ir_data.get("workflows", []):
        entity = wf.get("entity", "Entity")
        sm_code = generate_workflow_sm(entity, wf)
        (workflow_dir / f"{entity.lower()}_sm.py").write_text(sm_code)
        
    # 3. Logic generation - Integrations
    src_dir = output_dir / "src"
    src_dir.mkdir(exist_ok=True)
    
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
            subject=f"Status Update: {entity_name} is now {new_status}",
            template_name=f"{new_status}.html",
            context={{"obj": obj, "new_status": new_status}}
        )
    except Exception as e:
        logger.error("Failed to trigger email notification: %s", e)
"""
    (notif_dir / "email_triggers.py").write_text(email_triggers_code)
    
    # 4. Email Templates
    if flags.get("needs_email"):
        email_tmpl_dir = output_dir / "templates" / "emails"
        email_tmpl_dir.mkdir(parents=True, exist_ok=True)
        
        welcome_body = f"""
                    <h2 style="color: #4f46e5; margin-top: 0;">Welcome!</h2>
                    <p>We're excited to have you on board. Your account is ready to go.</p>
                    <a href="#" class="button">Get Started</a>
        """
        (email_tmpl_dir / "welcome.html").write_text(_get_responsive_email_template(project_name, welcome_body))
        
        # Mandatory templates
        pwd_reset_body = """
                <h2>Password Reset</h2>
                <p>Click the link below to reset your password:</p>
                <a href="#" class="button" style="background: #ef4444;">Reset Password</a>
        """
        (email_tmpl_dir / "password_reset.html").write_text(_get_responsive_email_template(project_name, pwd_reset_body))
        
        verification_body = """
                <h2>Verify Your Email</h2>
                <p>Please confirm your email address by clicking the link below:</p>
                <a href="#" class="button" style="background: #10b981;">Verify Email</a>
        """
        (email_tmpl_dir / "email_verification.html").write_text(_get_responsive_email_template(project_name, verification_body))
        
        # Domain specific templates from IR
        for notif in ir_data.get("notifications", []):
            event = notif.get("event", "notification")
            tmpl_body = f"""
                    <h2>Notification: {event.replace('_', ' ').capitalize()}</h2>
                    <p>{notif.get('template', 'No details provided.')}</p>
            """
            (email_tmpl_dir / f"{event}.html").write_text(_get_responsive_email_template(project_name, tmpl_body))

    # 5. Save artifacts
    summary = {
        "workflows": len(ir_data.get("workflows", [])),
        "integrations": [k for k, v in flags.items() if v],
        "email_templates": len(list((output_dir / "templates" / "emails").glob("*.html"))) if (output_dir / "templates" / "emails").exists() else 0,
        "status": "generated"
    }
    out_json = output_dir / "business_logic.json"
    out_json.write_text(json.dumps(summary, indent=2))
    
    return TaskResult(
        output_path=str(out_json),
        confidence=0.9,
        metadata=summary,
        success=True,
    )
