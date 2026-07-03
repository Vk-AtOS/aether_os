"""
Stage-by-stage questionnaire definitions for the interactive guided pipeline.

Each stage maps to a list of question dicts.  The renderer and the pipeline
pause logic both consume this mapping — keep question IDs stable across
deployments because they become keys in questionnaire_answers in the DB.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Question schema (TypedDict-style comment only — no runtime overhead):
# {
#   "id":         str  — unique within stage (stable across versions)
#   "label":      str  — human-readable prompt
#   "type":       str  — select|multiselect|text|textarea|boolean|number
#   "options":    list — for select / multiselect only
#   "default":    any  — pre-filled default value
#   "help":       str  — grey explanatory text shown below the field
#   "required":   bool — validation on submit
#   "depends_on": None | {"question_id": str, "value": any}
# }
# ---------------------------------------------------------------------------

STAGE_QUESTIONS: dict[str, list[dict]] = {

    # ── Stage 01: Intake / Project Setup ─────────────────────────────────────
    "s01_intake": [
        {
            "id": "app_name",
            "label": "Application name",
            "type": "text",
            "options": [],
            "default": "",
            "help": "The display name for your application (e.g. InvoicePro, ClinicApp).",
            "required": True,
            "depends_on": None,
        },
        {
            "id": "app_description",
            "label": "Application description",
            "type": "textarea",
            "options": [],
            "default": "",
            "help": "What does this app do? Who uses it? What problem does it solve?",
            "required": True,
            "depends_on": None,
        },
        {
            "id": "target_users",
            "label": "Target users",
            "type": "text",
            "options": [],
            "default": "",
            "help": "e.g. 'Small business owners', 'Hospital staff', 'Freelance developers'.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "domain",
            "label": "Industry / domain",
            "type": "select",
            "options": [
                "E-commerce", "Healthcare", "Fintech", "SaaS", "Marketplace",
                "ERP", "Government", "AI-integrated", "Other",
            ],
            "default": "SaaS",
            "help": "Helps the AI choose appropriate patterns and seed data.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "key_entities",
            "label": "Key data entities",
            "type": "textarea",
            "options": [],
            "default": "",
            "help": "List the main objects your app manages — e.g. Products, Orders, Customers.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "build_type",
            "label": "Build type(s)",
            "type": "multiselect",
            "options": [
                "Web app", "Mobile app", "CLI tool", "Multi-tenant SaaS",
                "Agentic AI", "Real-time", "File management", "Marketplace",
            ],
            "default": ["Web app"],
            "help": "Select all that apply.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 02: Architecture Review ────────────────────────────────────────
    "s02_architecture": [
        {
            "id": "database_type",
            "label": "Database",
            "type": "select",
            "options": ["PostgreSQL", "MySQL", "SQLite"],
            "default": "PostgreSQL",
            "help": "PostgreSQL is recommended for production workloads.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "scale",
            "label": "Deployment scale",
            "type": "select",
            "options": ["Single-server", "Multi-server", "Microservices"],
            "default": "Single-server",
            "help": "Single-server is fastest to build and deploy.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "auth_method",
            "label": "Authentication method",
            "type": "select",
            "options": ["JWT", "OAuth2", "Magic Link", "SAML"],
            "default": "JWT",
            "help": "JWT is fastest to set up. OAuth2 adds social login.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "needs_realtime",
            "label": "Real-time updates needed?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "e.g. live dashboards, notifications, collaborative editing.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "needs_file_uploads",
            "label": "File uploads needed?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Images, documents, CSVs, etc.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "needs_multi_tenancy",
            "label": "Multi-tenant (multiple orgs/companies)?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Each tenant gets isolated data — adds org_id to every table.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 03: Backend Configuration ──────────────────────────────────────
    "s03_backend": [
        {
            "id": "api_style",
            "label": "API style",
            "type": "select",
            "options": ["REST", "GraphQL", "gRPC"],
            "default": "REST",
            "help": "REST is the most widely supported. GraphQL suits complex UIs.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "rate_limiting",
            "label": "Enable rate limiting?",
            "type": "boolean",
            "options": [],
            "default": True,
            "help": "Protect endpoints from abuse with per-IP request limits.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "rate_limit_per_minute",
            "label": "Requests per minute (per IP)",
            "type": "number",
            "options": [],
            "default": 60,
            "help": "Applied when rate limiting is enabled.",
            "required": False,
            "depends_on": {"question_id": "rate_limiting", "value": True},
        },
        {
            "id": "integrations",
            "label": "Third-party integrations",
            "type": "multiselect",
            "options": ["Stripe", "SendGrid", "Twilio", "AWS S3", "Slack", "None"],
            "default": ["None"],
            "help": "Select all integrations to wire in.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "admin_panel",
            "label": "Include admin panel?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "A separate /admin UI for managing users and data.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 04: Frontend & Design ───────────────────────────────────────────
    "s04_frontend": [
        {
            "id": "ui_theme",
            "label": "UI theme",
            "type": "select",
            "options": ["Dark", "Light", "System"],
            "default": "Light",
            "help": "Base color scheme for the generated UI.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "primary_color",
            "label": "Primary accent colour",
            "type": "select",
            "options": ["Violet", "Blue", "Green", "Orange", "Red", "Gray"],
            "default": "Violet",
            "help": "Used for buttons, links, and highlights throughout the app.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "dashboard_layout",
            "label": "Dashboard layout",
            "type": "select",
            "options": ["Sidebar", "Top nav", "Minimal"],
            "default": "Sidebar",
            "help": "Sidebar is best for feature-rich apps; Minimal for simple tools.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "mobile_priority",
            "label": "Prioritise mobile experience?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Adds responsive breakpoints and touch-friendly UI components.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "charts_needed",
            "label": "Include charts / analytics?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Adds a Recharts-powered analytics section.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "chart_types",
            "label": "Chart types",
            "type": "multiselect",
            "options": ["Line", "Area", "Bar", "Pie", "Table"],
            "default": ["Line", "Bar"],
            "help": "Select which chart types to include.",
            "required": False,
            "depends_on": {"question_id": "charts_needed", "value": True},
        },
    ],

    # ── Stage 05: Security Review ─────────────────────────────────────────────
    "s05_quality": [
        {
            "id": "accept_security_fixes",
            "label": "Approve automated security fixes?",
            "type": "boolean",
            "options": [],
            "default": True,
            "help": "Allows the AI to apply security patches without manual approval.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "additional_constraints",
            "label": "Additional compliance requirements",
            "type": "textarea",
            "options": [],
            "default": "",
            "help": "e.g. HIPAA, PCI-DSS, SOC 2. Leave blank if none apply.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 06: Testing Configuration ──────────────────────────────────────
    "s06_testing": [
        {
            "id": "coverage_target",
            "label": "Minimum test coverage %",
            "type": "number",
            "options": [],
            "default": 70,
            "help": "Pipeline will retry self-healing if coverage falls below this.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "include_e2e",
            "label": "Include Playwright E2E tests?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Adds browser-based end-to-end tests for critical user flows.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "include_performance",
            "label": "Include performance / load testing?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Runs a Locust load test and reports p95 latency.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 07: Auto-Repair Review ──────────────────────────────────────────
    "s07_healing": [
        {
            "id": "approve_healing",
            "label": "Approve all auto-applied code fixes?",
            "type": "boolean",
            "options": [],
            "default": True,
            "help": "Self-healing patches are applied automatically and logged.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "notes",
            "label": "Any specific issues to prioritise?",
            "type": "textarea",
            "options": [],
            "default": "",
            "help": "Describe any known bugs or tech-debt to address first.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 08: Monitoring Setup ────────────────────────────────────────────
    "s08_observability": [
        {
            "id": "monitoring_stack",
            "label": "Monitoring stack",
            "type": "select",
            "options": ["Prometheus+Grafana", "Datadog", "New Relic", "Logging only"],
            "default": "Prometheus+Grafana",
            "help": "Prometheus+Grafana is free and self-hosted.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "alert_email",
            "label": "Alert email address",
            "type": "text",
            "options": [],
            "default": "",
            "help": "Where to send critical error alerts. Leave blank to skip.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "error_tracking",
            "label": "Enable Sentry error tracking?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Sentry captures exceptions with full stack traces.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 09: Deployment Configuration ───────────────────────────────────
    "s09_devops": [
        {
            "id": "deploy_target",
            "label": "Deployment target",
            "type": "select",
            "options": [
                "Docker Compose", "Kubernetes", "AWS ECS", "Cloud Run", "Heroku", "Local only",
            ],
            "default": "Docker Compose",
            "help": "Docker Compose works on any Linux server.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "ci_platform",
            "label": "CI/CD platform",
            "type": "select",
            "options": ["GitHub Actions", "GitLab CI", "CircleCI", "None"],
            "default": "GitHub Actions",
            "help": "Generates pipeline config for the selected platform.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "domain_name",
            "label": "Custom domain",
            "type": "text",
            "options": [],
            "default": "",
            "help": "e.g. myapp.com — used in CORS config and nginx vhost.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 10: Enterprise Features ─────────────────────────────────────────
    "s10_enterprise": [
        {
            "id": "feature_flags",
            "label": "Include feature flags?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "GrowthBook-compatible feature flag support.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "billing_stripe",
            "label": "Include Stripe billing?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Adds subscription plans, invoices, and Stripe webhook handling.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "sso_saml",
            "label": "Enable SAML SSO?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Allows enterprise customers to log in via Okta, Azure AD, etc.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "audit_logs",
            "label": "Include audit logs?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Tamper-evident log of every data change.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "multi_tenancy",
            "label": "Multi-tenancy (isolated orgs)?",
            "type": "boolean",
            "options": [],
            "default": False,
            "help": "Each customer organisation gets its own isolated data.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 11: Delivery Options ────────────────────────────────────────────
    "s11_handoff": [
        {
            "id": "delivery_format",
            "label": "Delivery format",
            "type": "multiselect",
            "options": ["ZIP archive", "GitHub repo", "Hosted demo"],
            "default": ["ZIP archive"],
            "help": "How you want to receive the finished application.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "include_postman",
            "label": "Include Postman collection?",
            "type": "boolean",
            "options": [],
            "default": True,
            "help": "An importable Postman collection for every API endpoint.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "include_docs",
            "label": "Include documentation?",
            "type": "boolean",
            "options": [],
            "default": True,
            "help": "README, API reference, and deployment guide.",
            "required": False,
            "depends_on": None,
        },
        {
            "id": "client_name",
            "label": "Client / recipient name",
            "type": "text",
            "options": [],
            "default": "",
            "help": "Used on the cover page of generated docs.",
            "required": False,
            "depends_on": None,
        },
    ],

    # ── Stage 12: Specialist Outputs ──────────────────────────────────────────
    "s12_specialist": [
        {
            "id": "specialist_outputs",
            "label": "Additional specialist outputs",
            "type": "multiselect",
            "options": ["Mobile app", "Desktop app", "CLI tool", "Helm chart"],
            "default": [],
            "help": "Optional extra artefacts beyond the default web app.",
            "required": False,
            "depends_on": None,
        },
    ],
}


def get_stage_questions(stage_id: str) -> list[dict]:
    """Return question list for the given stage, empty list if unknown."""
    return STAGE_QUESTIONS.get(stage_id, [])


def extract_stage_answers(stage_id: str, intake_answers: dict) -> dict:
    """Filter intake_answers to only the keys relevant to stage_id's questions.

    Used in autonomous mode so pre-filled intake_answers are mapped correctly
    per stage without exposing keys from other stages.
    """
    questions = STAGE_QUESTIONS.get(stage_id, [])
    relevant_ids = {q["id"] for q in questions}
    return {k: v for k, v in intake_answers.items() if k in relevant_ids}
