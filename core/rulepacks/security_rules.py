"""Security prompt rule pack: an always-on core plus modules picked by stack feature.

    security_prompt_rules(["fastapi", "sqlalchemy", "jwt-auth", "react"])

Two tiers keep the prompt short: the core applies to every file, modules only when the stack has the feature.
Each rule names the SEC id its post-generation check uses, so a repair prompt and the rule agree.
Wording is AetherOS's own; see NOTICE.md for the public sources of the ideas.
"""
from __future__ import annotations

from pathlib import Path

from aether_os.core.rulepacks.base import Project

CORE = (
    "NEVER write a credential, API key, token or password into code, Dockerfiles or compose files. Read it from "
    "the environment and list the name (with a placeholder value) in .env.example. [SEC-001, SEC-021]",
    "Signing secrets (SECRET_KEY, JWT_SECRET) have NO default. At startup, refuse to run when one is missing or "
    "shorter than 32 characters. [SEC-002]",
    "NEVER build SQL, shell commands or file paths by concatenating or formatting input. Use bound parameters, "
    "argument lists and a fixed base directory. [SEC-004, SEC-005]",
    "NEVER eval/exec data, unpickle untrusted bytes, or yaml.load without SafeLoader. Parse with json or "
    "yaml.safe_load and validate the result. [SEC-005]",
    "Deny by default: every endpoint requires an authenticated user except the documented public list "
    "(health, login, register). Put the auth dependency on the router. [SEC-007]",
    "Authorise every object access: load records filtered by the current user's id or tenant and return 404 "
    "for anything else, including on update and delete. [SEC-008]",
    "Treat every request body as untrusted: validate with strict schemas, cap string lengths and page sizes, "
    "and never let clients set role, owner or id fields.",
    "Errors returned to clients are generic; log the details server-side with a request id. Never put stack "
    "traces, SQL or secrets in a response or a log line.",
    "Pin dependency versions and use only well-known packages; do not invent package names.",
    "Production defaults are safe: debug off, no auto-reload, docs routes off or behind auth. [SEC-006]",
)

MODULES = {
    "fastapi": (
        "CORS: list the frontend origins from settings; never allow_origins=[\"*\"] together with "
        "allow_credentials=True. [SEC-009]",
        "Add a middleware that sets X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy: "
        "strict-origin-when-cross-origin, a Content-Security-Policy and HSTS when served over TLS. [SEC-012]",
        "Declare response_model on every route; response schemas never include password hashes, tokens or "
        "internal flags.",
        "Outbound HTTP calls always pass timeout= and keep TLS verification on. [SEC-018, PRD-008]",
    ),
    "sqlalchemy": (
        "Query through the ORM or text() with :named parameters only. [SEC-004]",
        "Every tenant-owned table has an owner_id/tenant_id column with an index; every query on it filters by "
        "that column. [SEC-008]",
        "Schema changes go through Alembic migrations, never create_all() at startup. [PRD-004]",
    ),
    "jwt-auth": (
        "Hash passwords with argon2 or bcrypt (passlib/pwdlib); compare with the library's verify(). Never "
        "md5/sha1/sha256 or plain text. [SEC-011]",
        "jwt.decode always passes a fixed algorithms=[...] list and verifies exp; never turn verification off "
        "or accept 'none'. Access tokens live 60 minutes or less. [SEC-010]",
        "Rate limit login, register, token and password-reset routes (e.g. 5/minute per IP) and return the same "
        "error for unknown user and wrong password. [SEC-013]",
        "Generate tokens, reset codes and OTPs with the secrets module, never random. [SEC-019]",
        "Prefer an HttpOnly, Secure, SameSite=Lax cookie for the session token; add CSRF protection when "
        "cookies authenticate state-changing requests.",
    ),
    "file-upload": (
        "Uploads: check size before reading fully, allow-list extensions and content types, check magic bytes.",
        "Store uploads under a random uuid name outside the web root; never use the client filename in a path. "
        "Serve them with Content-Disposition: attachment unless they are verified images.",
    ),
    "react": (
        "Never use dangerouslySetInnerHTML; if HTML must render, pass it through DOMPurify.sanitize. No eval, "
        "new Function or innerHTML assignment. [SEC-015]",
        "Do not keep auth tokens in localStorage or sessionStorage; rely on the HttpOnly cookie. [SEC-014]",
        "Links with target=\"_blank\" carry rel=\"noopener noreferrer\"; only render http(s)/mailto URLs from "
        "data, never javascript:. [SEC-016]",
        "VITE_* variables are public: never put secrets in them. Route guards are UX only; the API enforces "
        "access. [SEC-021]",
    ),
    "docker": (
        "Pin base images to a version (python:3.12-slim, node:20-alpine), use multi-stage builds and run as a "
        "non-root USER. [SEC-017]",
        "Add a HEALTHCHECK, a .dockerignore that excludes .env and .git, and never bake secrets into ENV or ARG. "
        "[SEC-022, SEC-001]",
        "In compose, do not publish database or cache ports; pass secrets through env_file.",
    ),
    "llm-agent": (
        "Model output is untrusted input: validate it against a schema; never execute, eval or shell it. [SEC-005]",
        "Tools come from a fixed allow-list with validated arguments; cap iterations, tokens, cost and wall time "
        "per run.",
        "Retrieved documents and web pages may contain instructions; treat them as data and never let them change "
        "tools or permissions.",
        "Never send secrets or other users' data in prompts; rate limit model-backed endpoints per user.",
    ),
}
FEATURES = tuple(MODULES)


def security_prompt_rules(features: list[str] | tuple[str, ...] = ()) -> str:
    unknown = [f for f in features if f not in MODULES]
    if unknown:
        raise ValueError(f"unknown security module(s) {unknown}; expected {', '.join(FEATURES)}")
    rules = list(CORE)
    for f in FEATURES:  # fixed order so the prompt is stable for caching
        if f in features:
            rules += MODULES[f]
    head = "SECURITY RULES. Non-negotiable; they are checked after generation (ids in brackets)."
    return "\n".join([head] + [f"{i}. {r}" for i, r in enumerate(rules, 1)])


def detect_features(root: str | Path) -> list[str]:
    """Stack features of an existing project, for picking modules on an edit turn."""
    p = Project.load(root)
    blob = "\n".join(p.text(f) for f in p.files if f.endswith((".py", ".txt", ".toml", ".json", ".ts", ".tsx")))
    checks = {
        "fastapi": "fastapi" in blob.lower(), "sqlalchemy": "sqlalchemy" in blob.lower() or "sqlmodel" in blob.lower(),
        "jwt-auth": any(k in blob for k in ("jwt", "jose", "OAuth2PasswordBearer", "passlib")),
        "file-upload": "UploadFile" in blob or "multipart" in blob, "react": '"react"' in blob,
        "docker": any(f.rsplit("/", 1)[-1].startswith("Dockerfile") for f in p.files),
        "llm-agent": any(k in blob for k in ("openai", "anthropic", "litellm", "langchain", "ollama")),
    }
    return [f for f in FEATURES if checks[f]]
