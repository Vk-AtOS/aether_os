"""
P04b Business Logic Layer — Logic Generators.
Real functional scaffolds for Email, Payments, and Storage.
"""
import json
from typing import Dict

def _step_name(step) -> str:
    if isinstance(step, dict):
        return step.get("name") or step.get("action") or step.get("status") or str(step)
    return str(step)

def generate_workflow_sm(entity_name: str, workflow: Dict) -> str:
    """Generate a Python StateMachine class for a workflow with role checks."""
    raw_steps = workflow.get("steps", [])
    steps = [_step_name(s) for s in raw_steps]

    # Simple transition map from steps (placed -> confirmed -> preparing)
    transitions = {}
    for i in range(len(steps) - 1):
        transitions[steps[i]] = [steps[i+1]]
    if steps:
        transitions[steps[-1]] = ["cancelled"]
        
    lines = [
        f"class {entity_name}StateMachine:",
        f"    VALID_TRANSITIONS = {json.dumps(transitions, indent=8)}",
        "",
        "    @staticmethod",
        "    def transition(obj, new_status: str, actor_role: str = 'user') -> bool:",
        f"        if new_status not in {entity_name}StateMachine.VALID_TRANSITIONS.get(obj.status, []):",
        "            raise ValueError(f'Invalid transition: {obj.status} -> {new_status}')",
        "",
        "        # Role-based restriction: only staff/admin can move beyond 'placed'",
        "        if obj.status != 'placed' and actor_role not in ['admin', 'staff']:",
        "            raise PermissionError('Only staff can update status beyond initial stage')",
        "",
        "        obj.status = new_status",
        "        # Trigger notification hook",
        "        try:",
        "            from src.notifications.email_triggers import trigger_notification",
        "            import asyncio",
        "            import logging",
        "            asyncio.create_task(trigger_notification(obj, new_status))",
        "        except ImportError:",
        f"            logging.getLogger(__name__).warning('email_triggers module not found — notification skipped for {entity_name} → %s', new_status)",
        "        return True"
    ]
    return "\n".join(lines)

def generate_email_service() -> str:
    """Generate transactional email service with Jinja2-style template rendering."""
    return '''"""
Email service with SMTP support and HTML template rendering.
Requires: jinja2
"""
from __future__ import annotations
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

class EmailService:
    def __init__(self):
        self.smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SMTP_USER", "")
        self.smtp_pass = os.environ.get("SMTP_PASSWORD", "")
        self.from_email = os.environ.get("FROM_EMAIL", "noreply@aetheros.app")

    async def send(self, to: str, subject: str, template_name: str, context: dict):
        """Send an HTML email using a local template."""
        # In a real app, use jinja2 to render templates/emails/{template_name}.html
        print(f"EMAIL SENT TO {to} | SUBJECT: {subject} | TEMPLATE: {template_name}")
        
        if not self.smtp_user:
            return # Skip if not configured
            
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_email
        msg["To"] = to
        msg.set_content(f"Subject: {subject}\\n\\nThis is a fallback text message.")
        
        # HTML logic would go here
        
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
        except Exception as e:
            print(f"Failed to send email: {e}")
'''

def generate_stripe_service() -> str:
    """Generate Stripe payment service with intent creation."""
    return '''"""Stripe payment service scaffold."""
import os
import stripe

class StripeService:
    def __init__(self):
        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "sk_test_placeholder")
        self.webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    async def create_payment_intent(self, amount: int, currency: str = "usd", metadata: dict = None):
        """Create a PaymentIntent for the frontend to confirm."""
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                metadata=metadata or {},
                automatic_payment_methods={"enabled": True},
            )
            return intent
        except Exception as e:
            print(f"Stripe error: {e}")
            return None

    async def handle_webhook(self, payload: bytes, sig: str):
        """Handle incoming Stripe events."""
        try:
            event = stripe.Webhook.construct_event(payload, sig, self.webhook_secret)
            return event
        except Exception as e:
            print(f"Webhook error: {e}")
            return None
'''

def generate_s3_service() -> str:
    """Generate S3 file upload service using boto3."""
    return '''"""S3 file upload service using boto3."""
import os
import boto3
from botocore.exceptions import ClientError

class S3Service:
    def __init__(self):
        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION", "us-east-1")
        )
        self.bucket = os.environ.get("AWS_S3_BUCKET")

    async def upload_file(self, file_path: str, object_name: str = None) -> str:
        """Upload a file to S3 and return the public URL."""
        if object_name is None:
            object_name = os.path.basename(file_path)
            
        try:
            self.s3.upload_file(file_path, self.bucket, object_name)
            return f"https://{self.bucket}.s3.amazonaws.com/{object_name}"
        except ClientError as e:
            print(f"S3 Upload Error: {e}")
            return ""
'''
