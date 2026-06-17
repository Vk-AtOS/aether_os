"""P02 Architecture — helper utilities and domain data.

Contains: domain data constants, resource extraction, fallback architecture
builder, and tech stack fixer.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List

# ── Schema and defaults ───────────────────────────────────────────────────────

ARCHITECTURE_SCHEMA = {
    "domain": "general",
    "tech_stack": {
        "backend": "FastAPI",
        "frontend": "React",
        "database": "PostgreSQL",
        "cache": "None",
        "queue": "None",
        "deployment": "Docker",
        "monitoring": "Prometheus",
    },
    "component_diagram": "graph TD\n  Client --> API\n  API --> DB",
    "database_schema": [
        {"table": "users", "columns": ["id", "email", "password_hash", "created_at"]}
    ],
    "api_endpoints": [
        {"method": "GET",    "path": "/health",  "description": "Health check",   "auth": False},
        {"method": "GET",    "path": "/items",   "description": "List items",      "auth": True},
        {"method": "POST",   "path": "/items",   "description": "Create item",     "auth": True},
        {"method": "GET",    "path": "/items/{id}", "description": "Get item",     "auth": True},
        {"method": "PUT",    "path": "/items/{id}", "description": "Update item",  "auth": True},
        {"method": "DELETE", "path": "/items/{id}", "description": "Delete item",  "auth": True},
    ],
    "data_flow": "sequenceDiagram\n  Client->>API: Request\n  API->>DB: Query\n  DB-->>API: Result\n  API-->>Client: Response",
    "security_considerations": ["JWT authentication", "Input validation", "Rate limiting"],
    "scalability_notes": "Horizontally scalable via Docker Compose",
}

TECH_STACK_DEFAULTS = {
    "backend": "FastAPI",
    "frontend": "React",
    "database": "PostgreSQL",
    "cache": "None",
    "queue": "None",
    "deployment": "Docker",
    "monitoring": "Prometheus",
}

# Common domain nouns → CRUD resource detection
_DOMAIN_KEYWORDS = {
    "todo":      ("todos",    ["id", "title", "description", "completed", "created_at", "user_id"]),
    "task":      ("tasks",    ["id", "title", "description", "status", "priority", "due_date", "user_id"]),
    "user":      ("users",    ["id", "email", "password_hash", "name", "created_at"]),
    "product":   ("products", ["id", "name", "description", "price", "stock", "category_id"]),
    "order":     ("orders",   ["id", "user_id", "status", "total", "created_at"]),
    "item":      ("items",    ["id", "name", "description", "quantity", "price"]),
    "post":      ("posts",    ["id", "title", "content", "author_id", "published_at"]),
    "comment":   ("comments", ["id", "post_id", "author_id", "content", "created_at"]),
    "blog":      ("posts",    ["id", "title", "content", "author_id", "tags", "published_at"]),
    "article":   ("articles", ["id", "title", "body", "author_id", "published_at"]),
    "category":  ("categories", ["id", "name", "description", "parent_id"]),
    "inventory": ("inventory", ["id", "product_id", "quantity", "location", "updated_at"]),
    "customer":  ("customers", ["id", "name", "email", "phone", "address"]),
    "employee":  ("employees", ["id", "name", "email", "role", "department", "hired_at"]),
    "event":     ("events",   ["id", "title", "description", "start_at", "end_at", "location"]),
    "message":   ("messages", ["id", "sender_id", "recipient_id", "content", "sent_at"]),
    "payment":   ("payments", ["id", "order_id", "amount", "status", "method", "created_at"]),
    "booking":   ("bookings", ["id", "user_id", "resource_id", "start_at", "end_at", "status"]),
    "review":    ("reviews",  ["id", "user_id", "product_id", "rating", "content", "created_at"]),
    "report":    ("reports",  ["id", "title", "data", "generated_by", "created_at"]),
    # CRM-specific
    "contact":   ("contacts", ["id", "name", "email", "phone", "company", "type", "tags", "created_at"]),
    "deal":      ("deals",    ["id", "contact_id", "title", "value", "stage", "probability", "close_date", "assigned_to"]),
    "lead":      ("leads",    ["id", "name", "email", "source", "status", "score", "created_at"]),
    "pipeline":  ("pipeline_stages", ["id", "name", "order", "win_probability"]),
    "activity":  ("activities", ["id", "contact_id", "type", "notes", "occurred_at", "user_id"]),
    "account":   ("accounts", ["id", "name", "industry", "website", "revenue", "created_at"]),
    "segment":   ("segments", ["id", "name", "criteria", "contact_count", "created_at"]),
    "crm":       ("contacts", ["id", "name", "email", "phone", "company", "type", "tags", "created_at"]),
}

# G15 fix: domain-aware fallback entity lists so we never get generic tasks/users/comments
DOMAIN_FALLBACK_ENTITIES = {
    "saas_multitenant": ["organizations", "memberships", "workspaces", "projects", "tasks"],
    "saas": ["organizations", "memberships", "workspaces", "projects", "tasks"],
    "healthcare": ["patients", "appointments", "providers", "records", "prescriptions"],
    "fintech": ["accounts", "transactions", "ledger_entries", "users", "audit_logs"],
    "ecommerce": ["products", "orders", "customers", "cart_items", "categories"],
    "general": ["tasks", "users", "comments", "tags", "categories"],
}

# Domain-specific table schemas used in fallback
_DOMAIN_FALLBACK_SCHEMAS: Dict[str, List[Dict]] = {
    "healthcare": [
        {"table": "patients",      "columns": ["id", "name", "dob", "email", "phone", "created_at"]},
        {"table": "appointments",  "columns": ["id", "patient_id", "provider_id", "scheduled_at", "status", "notes"]},
        {"table": "providers",     "columns": ["id", "name", "specialty", "email", "license_number"]},
        {"table": "records",       "columns": ["id", "patient_id", "provider_id", "type", "content", "created_at"]},
        {"table": "prescriptions", "columns": ["id", "patient_id", "provider_id", "medication", "dosage", "expires_at"]},
        {"table": "users",         "columns": ["id", "email", "password_hash", "role", "created_at"]},
    ],
    "fintech": [
        {"table": "users",          "columns": ["id", "email", "name", "password_hash", "kyc_status", "created_at"]},
        {"table": "accounts",       "columns": ["id", "user_id", "type", "currency", "balance", "status", "created_at"]},
        {"table": "transactions",   "columns": ["id", "account_id", "type", "amount", "currency", "status", "reference", "created_at"]},
        {"table": "ledger_entries", "columns": ["id", "transaction_id", "account_id", "debit", "credit", "balance_after", "created_at"]},
        {"table": "audit_logs",     "columns": ["id", "user_id", "action", "resource", "ip_address", "created_at"]},
    ],
    "ecommerce": [
        {"table": "users",       "columns": ["id", "email", "name", "password_hash", "created_at"]},
        {"table": "customers",   "columns": ["id", "user_id", "shipping_address", "billing_address", "created_at"]},
        {"table": "categories",  "columns": ["id", "name", "slug", "parent_id", "description"]},
        {"table": "products",    "columns": ["id", "name", "description", "price", "stock", "category_id", "sku", "created_at"]},
        {"table": "orders",      "columns": ["id", "customer_id", "status", "total", "shipping_address", "created_at"]},
        {"table": "cart_items",  "columns": ["id", "customer_id", "product_id", "quantity", "added_at"]},
    ],
}

_DOMAIN_FALLBACK_ENDPOINTS: Dict[str, List[Dict]] = {
    "healthcare": [
        {"method": "POST",   "path": "/auth/register",           "description": "Register user",              "auth": False},
        {"method": "POST",   "path": "/auth/login",              "description": "Login",                      "auth": False},
        {"method": "GET",    "path": "/patients",                "description": "List patients",              "auth": True},
        {"method": "POST",   "path": "/patients",                "description": "Create patient",             "auth": True},
        {"method": "GET",    "path": "/patients/{id}",           "description": "Get patient",                "auth": True},
        {"method": "GET",    "path": "/appointments",            "description": "List appointments",          "auth": True},
        {"method": "POST",   "path": "/appointments",            "description": "Schedule appointment",       "auth": True},
        {"method": "PUT",    "path": "/appointments/{id}",       "description": "Update appointment",         "auth": True},
        {"method": "GET",    "path": "/providers",               "description": "List providers",             "auth": True},
        {"method": "GET",    "path": "/records",                 "description": "List records",               "auth": True},
        {"method": "POST",   "path": "/records",                 "description": "Create record",              "auth": True},
        {"method": "GET",    "path": "/prescriptions",           "description": "List prescriptions",         "auth": True},
        {"method": "POST",   "path": "/prescriptions",           "description": "Create prescription",        "auth": True},
        {"method": "GET",    "path": "/health",                  "description": "Health check",               "auth": False},
    ],
    "fintech": [
        {"method": "POST",   "path": "/auth/register",           "description": "Register user",              "auth": False},
        {"method": "POST",   "path": "/auth/login",              "description": "Login",                      "auth": False},
        {"method": "GET",    "path": "/accounts",                "description": "List accounts",              "auth": True},
        {"method": "POST",   "path": "/accounts",                "description": "Create account",             "auth": True},
        {"method": "GET",    "path": "/accounts/{id}",           "description": "Get account",                "auth": True},
        {"method": "GET",    "path": "/transactions",            "description": "List transactions",          "auth": True},
        {"method": "POST",   "path": "/transactions",            "description": "Create transaction",         "auth": True},
        {"method": "GET",    "path": "/transactions/{id}",       "description": "Get transaction",            "auth": True},
        {"method": "GET",    "path": "/ledger-entries",          "description": "List ledger entries",        "auth": True},
        {"method": "GET",    "path": "/audit-logs",              "description": "List audit logs",            "auth": True},
        {"method": "GET",    "path": "/health",                  "description": "Health check",               "auth": False},
    ],
    "ecommerce": [
        {"method": "POST",   "path": "/auth/register",           "description": "Register user",              "auth": False},
        {"method": "POST",   "path": "/auth/login",              "description": "Login",                      "auth": False},
        {"method": "GET",    "path": "/products",                "description": "List products",              "auth": False},
        {"method": "POST",   "path": "/products",                "description": "Create product",             "auth": True},
        {"method": "GET",    "path": "/products/{id}",           "description": "Get product",                "auth": False},
        {"method": "GET",    "path": "/categories",              "description": "List categories",            "auth": False},
        {"method": "GET",    "path": "/orders",                  "description": "List orders",                "auth": True},
        {"method": "POST",   "path": "/orders",                  "description": "Place order",                "auth": True},
        {"method": "GET",    "path": "/orders/{id}",             "description": "Get order",                  "auth": True},
        {"method": "POST",   "path": "/cart",                    "description": "Add item to cart",           "auth": True},
        {"method": "GET",    "path": "/cart",                    "description": "View cart",                  "auth": True},
        {"method": "DELETE", "path": "/cart/{id}",               "description": "Remove cart item",           "auth": True},
        {"method": "GET",    "path": "/health",                  "description": "Health check",               "auth": False},
    ],
}


# ── Domain extraction ─────────────────────────────────────────────────────────

def extract_resources(raw_input: str, domain: str = "general") -> List[Dict]:
    """
    Parse raw_input to detect domain nouns and build a rich resource list.
    Returns a list of {"resource": str, "table": str, "columns": [...]} dicts.
    """
    lower = raw_input.lower()
    found = []
    seen_tables: set = set()

    for keyword, (table, columns) in _DOMAIN_KEYWORDS.items():
        if keyword in lower and table not in seen_tables:
            found.append({"resource": keyword, "table": table, "columns": columns})
            seen_tables.add(table)

    # Fallback: extract bare nouns from the sentence if nothing matched.
    if not found:
        words = re.findall(r'\b([a-z]{3,})\b', lower)
        stop_words = {"the", "and", "for", "are", "with", "that", "this",
                      "from", "have", "will", "can", "but", "not", "build",
                      "create", "make", "using", "api", "app", "rest", "web",
                      "system", "service", "python", "fastapi", "django"}
        candidates = [w for w in dict.fromkeys(words) if w not in stop_words][:3]
        for noun in candidates:
            table = noun + "s" if not noun.endswith("s") else noun
            found.append({
                "resource": noun,
                "table": table,
                "columns": ["id", "name", "description", "created_at"],
            })

    # If still no resources found at all, use domain-canonical entity list
    if not found:
        fallback_entities = DOMAIN_FALLBACK_ENTITIES.get(domain, DOMAIN_FALLBACK_ENTITIES["general"])
        for entity in fallback_entities[:3]:
            noun = entity.rstrip("s")  # rough singularisation
            found.append({
                "resource": noun,
                "table": entity,
                "columns": ["id", "name", "description", "created_at"],
            })

    return found


# ── Fallback architecture builder ─────────────────────────────────────────────

def build_fallback_architecture(raw_input: str, domain: str = "general") -> dict:
    """
    Build a domain-aware architecture dict when the LLM is unavailable.
    Never returns a generic hello-world — always reflects the requirement.
    """
    from aether_os.core.domain_engine import get_domain_profile
    profile = get_domain_profile(domain)

    # SaaS multi-tenant domain: always use the canonical org/membership schema
    if domain in ("saas_multitenant", "saas"):
        stack = {**TECH_STACK_DEFAULTS, **profile.suggested_tech_stack}
        db_type = stack.get("database", "PostgreSQL")
        saas_db_schema = [
            {"table": "organizations", "columns": ["id", "name", "slug", "plan", "created_at"]},
            {"table": "memberships", "columns": ["id", "org_id", "user_id", "role", "created_at"]},
            {"table": "users", "columns": ["id", "email", "name", "password_hash", "created_at"]},
            {"table": "projects", "columns": ["id", "org_id", "name", "status", "created_at"]},
            {"table": "tasks", "columns": ["id", "project_id", "title", "status", "priority", "assignee_id", "due_date", "created_at"]},
        ]
        saas_endpoints = [
            {"method": "POST",   "path": "/auth/register",          "description": "Register user",           "auth": False},
            {"method": "POST",   "path": "/auth/login",             "description": "Login and get JWT token", "auth": False},
            {"method": "GET",    "path": "/organizations",          "description": "List organizations",      "auth": True},
            {"method": "POST",   "path": "/organizations",          "description": "Create organization",     "auth": True},
            {"method": "GET",    "path": "/projects",               "description": "List projects",           "auth": True},
            {"method": "POST",   "path": "/projects",               "description": "Create project",          "auth": True},
            {"method": "GET",    "path": "/projects/{id}",          "description": "Get project by ID",       "auth": True},
            {"method": "GET",    "path": "/tasks",                  "description": "List tasks",              "auth": True},
            {"method": "POST",   "path": "/tasks",                  "description": "Create task",             "auth": True},
            {"method": "PUT",    "path": "/tasks/{id}",             "description": "Update task",             "auth": True},
            {"method": "DELETE", "path": "/tasks/{id}",             "description": "Delete task",             "auth": True},
        ]
        return {
            "tech_stack": stack,
            "component_diagram": (
                "graph TD\n"
                "  Client --> API[FastAPI]\n"
                f"  API --> DB[({db_type})]\n"
                "  API --> Auth[JWT Auth]\n"
                "  subgraph Resources\n"
                "    API --> Orgs[Organizations]\n"
                "    API --> Projects[Projects]\n"
                "    API --> Tasks[Tasks]\n"
                "  end"
            ),
            "database_schema": saas_db_schema,
            "api_endpoints": saas_endpoints,
            "data_flow": (
                "sequenceDiagram\n"
                "  Client->>API: HTTP Request\n"
                "  API->>Auth: Validate JWT\n"
                "  Auth-->>API: Payload (org_id, user_id, role)\n"
                "  API->>OrgService: Enforce tenant isolation\n"
                "  OrgService->>DB: SQL Query (WHERE org_id=?)\n"
                "  DB-->>OrgService: Rows\n"
                "  OrgService-->>API: Result\n"
                "  API-->>Client: JSON Response"
            ),
            "security_considerations": profile.security_requirements + [
                "Pydantic input validation on all endpoints",
                "SQL injection prevention via ORM",
                "Multi-tenant row-level isolation",
            ],
            "scalability_notes": (
                f"Stateless FastAPI app — scale horizontally behind nginx. "
                f"{db_type} with read replicas. Tenant isolation via org_id foreign keys."
            ),
            "_fallback": True,
            "_detected_resources": ["organizations", "memberships", "projects", "tasks"],
            "domain": domain,
        }

    # G15 fix: domain-specific fallbacks for healthcare, fintech, ecommerce
    if domain in _DOMAIN_FALLBACK_SCHEMAS:
        stack = {**TECH_STACK_DEFAULTS, **profile.suggested_tech_stack}
        db_type = stack.get("database", "PostgreSQL")
        db_schema = _DOMAIN_FALLBACK_SCHEMAS[domain]
        endpoints = _DOMAIN_FALLBACK_ENDPOINTS[domain]
        entity_names = DOMAIN_FALLBACK_ENTITIES.get(domain, [])
        resource_nodes = "".join(
            f"    API --> {t.get('table', '').title()}[{t.get('table', '').replace('_', ' ').title()}]\n"
            for t in db_schema[:4]
        )
        return {
            "tech_stack": stack,
            "component_diagram": (
                f"graph TD\n"
                f"  Client --> API[FastAPI]\n"
                f"  API --> DB[({db_type})]\n"
                f"  API --> Auth[JWT Auth]\n"
                f"  subgraph Resources\n"
                f"{resource_nodes}"
                f"  end"
            ),
            "database_schema": db_schema,
            "api_endpoints": endpoints,
            "data_flow": (
                "sequenceDiagram\n"
                "  Client->>API: HTTP Request\n"
                "  API->>Auth: Validate JWT\n"
                "  Auth-->>API: Payload\n"
                f"  API->>Service: Business Logic\n"
                f"  Service->>DB: SQL Query\n"
                f"  DB-->>Service: Rows\n"
                f"  Service-->>API: Result\n"
                "  API-->>Client: JSON Response"
            ),
            "security_considerations": profile.security_requirements + [
                "Pydantic input validation on all endpoints",
                "SQL injection prevention via ORM",
            ],
            "scalability_notes": (
                f"Stateless FastAPI app — scale horizontally behind nginx. "
                f"{db_type} with read replicas."
            ),
            "_fallback": True,
            "_detected_resources": entity_names,
            "domain": domain,
        }

    resources = extract_resources(raw_input, domain=domain)
    primary = resources[0] if resources else {"resource": "item", "table": "items",
                                               "columns": ["id", "name", "created_at"]}

    # Database schema: one table per detected resource + users
    db_schema = []
    seen: set = set()
    for r in resources:
        if r["table"] not in seen:
            db_schema.append({"table": r["table"], "columns": r["columns"]})
            seen.add(r["table"])
    if "users" not in seen:
        db_schema.append({"table": "users",
                          "columns": ["id", "email", "password_hash", "created_at"]})

    # API endpoints: full CRUD for primary resource + auth + health
    res_name  = primary["resource"]
    res_table = primary["table"]
    endpoints = [
        {"method": "GET",    "path": "/health",
         "description": "Health check", "auth": False},
        {"method": "POST",   "path": "/auth/register",
         "description": "Register user", "auth": False},
        {"method": "POST",   "path": "/auth/login",
         "description": "Login and get JWT token", "auth": False},
        {"method": "GET",    "path": f"/{res_table}",
         "description": f"List all {res_table}", "auth": True},
        {"method": "POST",   "path": f"/{res_table}",
         "description": f"Create a new {res_name}", "auth": True},
        {"method": "GET",    "path": f"/{res_table}/{{id}}",
         "description": f"Get {res_name} by ID", "auth": True},
        {"method": "PUT",    "path": f"/{res_table}/{{id}}",
         "description": f"Update {res_name}", "auth": True},
        {"method": "DELETE", "path": f"/{res_table}/{{id}}",
         "description": f"Delete {res_name}", "auth": True},
    ]
    # Add secondary resource endpoints
    for r in resources[1:3]:
        endpoints.append({
            "method": "GET", "path": f"/{r['table']}",
            "description": f"List all {r['table']}", "auth": True,
        })
        endpoints.append({
            "method": "POST", "path": f"/{r['table']}",
            "description": f"Create {r['resource']}", "auth": True,
        })

    stack = {**TECH_STACK_DEFAULTS, **profile.suggested_tech_stack}
    db_type = stack.get("database", "PostgreSQL")

    component_diagram = (
        f"graph TD\n"
        f"  Client --> API[FastAPI]\n"
        f"  API --> DB[({db_type})]\n"
        f"  API --> Auth[JWT Auth]\n"
        f"  subgraph Resources\n"
        + "".join(f"    API --> {r['table'].title()}[{r['table'].title()}]\n"
                  for r in resources[:4])
        + "  end"
    )

    return {
        "tech_stack": stack,
        "component_diagram": component_diagram,
        "database_schema": db_schema,
        "api_endpoints": endpoints,
        "data_flow": (
            "sequenceDiagram\n"
            "  Client->>API: HTTP Request\n"
            "  API->>Auth: Validate JWT\n"
            "  Auth-->>API: Payload\n"
            f"  API-->>{res_table.title()}Service: Business Logic\n"
            f"  {res_table.title()}Service->>DB: SQL Query\n"
            f"  DB-->>{res_table.title()}Service: Rows\n"
            f"  {res_table.title()}Service-->>API: Result\n"
            "  API-->>Client: JSON Response"
        ),
        "security_considerations": profile.security_requirements + [
            "Pydantic input validation on all endpoints",
            "SQL injection prevention via ORM",
        ],
        "scalability_notes": (
            f"Stateless FastAPI app — scale horizontally behind nginx. "
            f"{db_type} with read replicas for {res_table}. "
        ),
        "_fallback": True,
        "_detected_resources": [r["resource"] for r in resources],
        "domain": domain
    }


def fix_tech_stack(result: dict) -> dict:
    """Ensure all required tech stack keys are present, filling defaults if missing."""
    ts = result.get("tech_stack", {})
    if not isinstance(ts, dict):
        ts = {}
    for k, v in TECH_STACK_DEFAULTS.items():
        if not ts.get(k):
            ts[k] = v
    result["tech_stack"] = ts
    if not result.get("api_endpoints"):
        result["api_endpoints"] = [
            {"method": "GET", "path": "/health",
             "description": "Health check", "auth": False}
        ]
    return result
