"""
AetherOS — Skill Library

Skills are LLM-powered code generators that inject best-practice patterns
into the pipeline. Unlike connectors (which call external APIs), skills
generate code using the AetherOS LLM client.

Each skill:
  - Has a set of templates (minimal starting points for LLM completion)
  - Has a generate() method that returns production-ready code
  - Injects its output into the pipeline's accumulated_context
  - Is designed to be composed: auth + crud + payment all work together

Skills are called by pipeline phases (p04_backend, p05_frontend, etc.)
when the accumulated context indicates a skill capability is needed.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseSkill:
    """Base class for all skills."""

    skill_id: str = ""
    name: str = ""

    def __init__(self, llm_client=None) -> None:
        self._llm = llm_client

    async def _llm_call(self, prompt: str, task_type: str = "code_generation",
                        system: Optional[str] = None) -> str:
        if self._llm:
            return await self._llm.call(prompt, task_type=task_type, system=system)
        # Fallback: lazy-import the singleton
        from aether_os.core.llm.client import LLMClient
        client = LLMClient()
        return await client.call(prompt, task_type=task_type, system=system)

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate code for the skill. Returns {files: {path: content}, metadata: {}}."""
        raise NotImplementedError


# ── Auth Skill ────────────────────────────────────────────────────────────────

class AuthSkill(BaseSkill):
    skill_id = "skill_auth"
    name = "Auth Skill"

    _SYSTEM = (
        "You are an expert authentication engineer. Generate production-ready, "
        "secure authentication code. Include proper error handling, rate limiting, "
        "and security best practices. Output only code files."
    )

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        framework = params.get("framework", "fastapi")
        auth_type = params.get("auth_type", "jwt")
        language = params.get("language", "python")

        prompt = f"""Generate a complete {auth_type} authentication system for {framework} ({language}).

Requirements:
- User registration with email/password (bcrypt hashing, min 10 chars)
- Login endpoint returning JWT (HS256, 24h expiry)
- Token refresh endpoint
- Password reset via email token
- Rate limiting on auth endpoints (5 attempts/15min)
- Input validation (pydantic models)
- Audit logging for all auth events
{"- Google OAuth2 integration" if auth_type == "oauth" else ""}
{"- TOTP-based MFA (pyotp)" if auth_type == "mfa" else ""}

Return a JSON object with this structure:
{{
  "files": {{
    "auth/models.py": "...",
    "auth/router.py": "...",
    "auth/utils.py": "...",
    "auth/schemas.py": "..."
  }},
  "dependencies": ["python-jose[cryptography]", "passlib[bcrypt]", "pyotp"],
  "env_vars": ["JWT_SECRET_KEY", "JWT_ALGORITHM"]
}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation", system=self._SYSTEM)
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"auth/generated.py": raw}, "dependencies": [], "env_vars": []}


# ── CRUD Skill ────────────────────────────────────────────────────────────────

class CRUDSkill(BaseSkill):
    skill_id = "skill_crud"
    name = "CRUD Skill"

    _SYSTEM = (
        "You are an expert backend engineer. Generate production-ready CRUD API "
        "code with full validation, pagination, filtering, and error handling."
    )

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        resource = params.get("resource", "item")
        framework = params.get("framework", "fastapi")
        db = params.get("database", "postgresql")
        fields = params.get("fields", [{"name": "name", "type": "str"},
                                        {"name": "description", "type": "str"}])

        fields_str = "\n".join([f"  - {f['name']}: {f['type']}" for f in fields])
        prompt = f"""Generate a complete CRUD API for a '{resource}' resource.

Framework: {framework}
Database: {db}
Fields:
{fields_str}

Include:
- Pydantic schemas (Create, Update, Response)
- SQLAlchemy model with timestamps (created_at, updated_at)
- Router with: GET /list (paginated, filterable), GET /:id, POST /, PUT /:id, DELETE /:id
- Soft delete (is_deleted flag, not physical delete)
- Input validation and 404/422 error handling
- Unit-test skeleton

Return JSON: {{"files": {{}}, "dependencies": [], "env_vars": []}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation", system=self._SYSTEM)
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"crud/generated.py": raw}, "dependencies": [], "env_vars": []}


# ── Payment Skill ─────────────────────────────────────────────────────────────

class PaymentSkill(BaseSkill):
    skill_id = "skill_payment"
    name = "Payment Skill"

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        payment_type = params.get("type", "one_time")  # one_time | subscription
        currency = params.get("currency", "usd")
        framework = params.get("framework", "fastapi")

        prompt = f"""Generate a complete Stripe payment integration ({payment_type}) for {framework}.

Include:
- Checkout session creation endpoint
- Webhook handler (payment_intent.succeeded, invoice.paid, customer.subscription.*)
- Idempotency keys on all Stripe API calls
- Webhook signature verification
- Price/product creation helpers
{"- Subscription management (create, cancel, update plan)" if payment_type == "subscription" else ""}
- Test mode support (check STRIPE_TEST_MODE env)
- Error handling for card declines, insufficient funds

Currency: {currency}
Return JSON: {{"files": {{}}, "dependencies": ["stripe"], "env_vars": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"]}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation")
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"payments/generated.py": raw},
                "dependencies": ["stripe"],
                "env_vars": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"]}


# ── Email Skill ───────────────────────────────────────────────────────────────

class EmailSkill(BaseSkill):
    skill_id = "skill_email"
    name = "Email Skill"

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        provider = params.get("provider", "resend")  # resend | sendgrid | ses
        templates = params.get("templates", ["welcome", "password_reset", "notification"])

        prompt = f"""Generate a complete email system using {provider}.

Templates needed: {', '.join(templates)}
Include:
- Email service class with send_email(), send_template() methods
- HTML templates for each: {', '.join(templates)}
- Queue/retry logic for failed sends
- Unsubscribe token generation
- Preview in development (log to console when EMAIL_PREVIEW=true)

Return JSON: {{"files": {{}}, "dependencies": [], "env_vars": []}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation")
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"email/generated.py": raw}, "dependencies": [], "env_vars": []}


# ── Search Skill ──────────────────────────────────────────────────────────────

class SearchSkill(BaseSkill):
    skill_id = "skill_search"
    name = "Search Skill"

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        search_type = params.get("type", "full_text")  # full_text | vector | hybrid
        model = params.get("model", params.get("resource", "document"))

        prompt = f"""Generate a {search_type} search system for '{model}' entities.

Include:
- {"PostgreSQL full-text search with tsvector + GIN index" if search_type == "full_text" else ""}
- {"pgvector integration with OpenAI text-embedding-3-small" if search_type == "vector" else ""}
- {"Combined full-text + vector reranking" if search_type == "hybrid" else ""}
- Search endpoint with pagination, highlighting, facets
- Indexing job (reindex all / incremental)
- Query builder with filters, sort, boost fields

Return JSON: {{"files": {{}}, "dependencies": [], "env_vars": []}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation")
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"search/generated.py": raw}, "dependencies": [], "env_vars": []}


# ── File Upload Skill ─────────────────────────────────────────────────────────

class FileUploadSkill(BaseSkill):
    skill_id = "skill_file_upload"
    name = "File Upload Skill"

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        storage = params.get("storage", "s3")  # s3 | r2 | gcs | local
        max_size_mb = params.get("max_size_mb", 10)
        allowed_types = params.get("allowed_types", ["image/*", "application/pdf"])

        prompt = f"""Generate a file upload system using {storage}.

Max file size: {max_size_mb}MB
Allowed types: {', '.join(allowed_types)}
Include:
- Multipart upload endpoint with validation
- Presigned URL generation for direct-to-storage upload
- Image resizing/thumbnail generation (Pillow)
- Virus scanning hook (ClamAV integration stub)
- File metadata storage in database
- CDN URL generation
- Cleanup job for orphaned files

Return JSON: {{"files": {{}}, "dependencies": [], "env_vars": []}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation")
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"uploads/generated.py": raw}, "dependencies": [], "env_vars": []}


# ── Notifications Skill ───────────────────────────────────────────────────────

class NotificationsSkill(BaseSkill):
    skill_id = "skill_notifications"
    name = "Notifications Skill"

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        channels = params.get("channels", ["in_app", "email"])

        prompt = f"""Generate a notification system supporting: {', '.join(channels)}.

Include:
- Notification model (type, recipient, read_at, payload JSON)
- NotificationService with send(), mark_read(), get_unread()
{"- FCM push notification integration" if "push" in channels else ""}
{"- Twilio SMS integration" if "sms" in channels else ""}
{"- In-app notification REST API with SSE real-time updates" if "in_app" in channels else ""}
{"- Email notification via queue" if "email" in channels else ""}
- User notification preferences (opt-in/opt-out per channel per type)
- Batch notification support

Return JSON: {{"files": {{}}, "dependencies": [], "env_vars": []}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation")
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"notifications/generated.py": raw}, "dependencies": [], "env_vars": []}


# ── Analytics Skill ───────────────────────────────────────────────────────────

class AnalyticsSkill(BaseSkill):
    skill_id = "skill_analytics"
    name = "Analytics Skill"

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        provider = params.get("provider", "posthog")
        events = params.get("events", ["page_view", "button_click", "signup", "conversion"])

        prompt = f"""Generate analytics event tracking using {provider}.

Events to track: {', '.join(events)}
Include:
- Analytics client initialization
- Event tracking helpers for each event
- User identification and trait setting
- Group analytics (for B2B)
- Feature flag integration
- Privacy-compliant (IP anonymization, cookie consent)
- Server-side event tracking for sensitive events

Return JSON: {{"files": {{}}, "dependencies": [], "env_vars": []}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation")
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"analytics/generated.py": raw}, "dependencies": [], "env_vars": []}


# ── Admin Skill ───────────────────────────────────────────────────────────────

class AdminSkill(BaseSkill):
    skill_id = "skill_admin"
    name = "Admin Panel Skill"

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        framework = params.get("framework", "react")
        resources = params.get("resources", ["users", "organisations", "runs"])

        prompt = f"""Generate an admin panel ({framework}) for resources: {', '.join(resources)}.

Include:
- Data table with sortable columns, pagination, search
- Create/edit forms with validation
- Bulk actions (delete, status change)
- CSV/JSON export
- Role-based access (only admin/owner roles)
- Activity log view

Return JSON: {{"files": {{}}, "dependencies": [], "env_vars": []}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation")
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"admin/generated.jsx": raw}, "dependencies": [], "env_vars": []}


# ── i18n Skill ────────────────────────────────────────────────────────────────

class I18nSkill(BaseSkill):
    skill_id = "skill_i18n"
    name = "i18n Skill"

    async def generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        framework = params.get("framework", "react")
        locales = params.get("locales", ["en", "es", "fr", "de"])
        default_locale = params.get("default", "en")

        prompt = f"""Generate a complete i18n setup for {framework}.

Locales: {', '.join(locales)}
Default: {default_locale}
Include:
- Translation file structure (JSON, one per locale)
- Translation hook (useTranslation)
- Locale switcher component
- Number/date/currency formatting per locale
- RTL support detection
- Missing translation fallback to default locale
- Pluralization rules

Return JSON: {{"files": {{}}, "dependencies": [], "env_vars": []}}"""

        try:
            raw = await self._llm_call(prompt, task_type="code_generation")
            return self._parse_output(raw)
        except Exception as exc:
            logger.warning("Skill %s LLM generation failed: %s", self.skill_id, exc)
            return {"files": {}, "metadata": {}, "error": str(exc), "skill_failed": True}

    def _parse_output(self, raw: str) -> Dict[str, Any]:
        import json, re
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {"files": {"i18n/generated.js": raw}, "dependencies": [], "env_vars": []}


# ── Skill factory ─────────────────────────────────────────────────────────────

_SKILL_MAP: Dict[str, type] = {
    "skill_auth":          AuthSkill,
    "skill_crud":          CRUDSkill,
    "skill_payment":       PaymentSkill,
    "skill_email":         EmailSkill,
    "skill_search":        SearchSkill,
    "skill_file_upload":   FileUploadSkill,
    "skill_notifications": NotificationsSkill,
    "skill_analytics":     AnalyticsSkill,
    "skill_admin":         AdminSkill,
    "skill_i18n":          I18nSkill,
}


def get_skill(skill_id: str, llm_client=None) -> BaseSkill:
    """Instantiate the skill for the given skill_id."""
    cls = _SKILL_MAP.get(skill_id)
    if not cls:
        raise ValueError(f"No skill implemented for '{skill_id}'")
    return cls(llm_client=llm_client)


def list_skills() -> List[str]:
    return list(_SKILL_MAP.keys())
