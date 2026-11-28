"""Prod-readiness checks over the generated project tree.

PRD-003 Alembic missing or without a real revision     PRD-006 .env.example missing / incomplete / holds a secret
PRD-009 no backend Dockerfile, compose service without healthcheck
PRD-010 no CI workflow                                  PRD-011 TODO / placeholder / NotImplemented in shipped code
PRD-012 README without run or deploy steps              PRD-013 demo seed run unconditionally by a container
Code-level checks (PRD-001/002/004/005/007/008/013) live in prodready_code.py.
"""
from __future__ import annotations

import ast
import logging
import math
import re
from collections import Counter

import yaml

from aether_os.core.rulepacks.base import Finding, Project, call_name, const_str, dotted, is_test_path, line_of, make
from aether_os.core.rulepacks.prodready_code import NON_PROD_PATH, check_code, check_health
from aether_os.core.rulepacks.pyroutes import collect_routes
from aether_os.core.rulepacks.security_py import PLACEHOLDER
from aether_os.core.rulepacks.secret_patterns import KEY_FORMATS
from aether_os.core.rulepacks.security_web import EXAMPLE_ENV

logger = logging.getLogger(__name__)
PACK = "prodready"
# Set by the OS, the platform or the toolchain; a project does not document these.
ENV_BUILTIN = {"PATH", "HOME", "PWD", "USER", "SHELL", "TERM", "HOSTNAME", "TZ", "LANG", "PYTHONPATH",
               "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "NODE_ENV", "MODE", "DEV", "PROD", "SSR", "BASE_URL",
               "CI", "TMPDIR", "VIRTUAL_ENV"}
TODO = re.compile(r"(?:#|//|/\*|\*|<!--)\s*(TODO|FIXME|HACK|XXX)\b")
ELISION = re.compile(r"(?:#|//|/\*|\{/\*)\s*\.\.\.\s*(?:rest|existing|more|remaining|other|same)\b|"
                     r"\brest of (?:the )?(?:code|implementation|file|component)\b|\byour[_-]\w+[_-]here\b|"
                     r"(?:#|//)\s*implement (?:this|me|later|here)\b|throw new Error\(\s*['\"`]not implemented", re.I)


def _env_reads(p: Project) -> dict[str, tuple[str, int]]:
    reads: dict[str, tuple[str, int]] = {}
    for rel in p.python_files():
        tree = p.tree(rel)
        if tree is None:
            continue
        for n in ast.walk(tree):
            name = None
            if isinstance(n, ast.Call) and n.args and (call_name(n).endswith(("getenv", "environ.get")) or call_name(n) == "config"):
                name = const_str(n.args[0])
            elif isinstance(n, ast.Subscript) and dotted(n.value).endswith("environ"):
                name = const_str(n.slice)
            if name:
                reads.setdefault(name, (rel, n.lineno))
            if isinstance(n, ast.ClassDef) and any("BaseSettings" in ast.unparse(b) for b in n.bases):
                src = ast.unparse(n)
                prefix = (re.search(r"env_prefix\s*=\s*['\"]([^'\"]*)", src) or [None, ""])[1]
                for b in n.body:
                    if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name) and b.target.id != "model_config":
                        alias = re.search(r"(?:validation_)?alias\s*=\s*['\"]([^'\"]+)", ast.unparse(b.value)) if b.value else None
                        reads.setdefault(alias.group(1) if alias else (prefix + b.target.id).upper(), (rel, b.lineno))
    web = re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]*)|process\.env\.([A-Z][A-Z0-9_]*)")
    compose = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::?[-?][^}]*)?\}")  # ${X} is interpolation only in compose files
    for rx, files in ((web, p.web_files()), (compose, p.named(r"^(?:docker-)?compose[\w.-]*\.ya?ml$"))):
        for rel in files:
            text = p.text(rel)
            for m in rx.finditer(text):
                reads.setdefault(next(g for g in m.groups() if g), (rel, line_of(text, m.start())))
    return {k: v for k, v in reads.items() if k not in ENV_BUILTIN}


def _entropy(s: str) -> float:
    counts = Counter(s)
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


def check_env_example(p: Project, out: list[Finding]) -> None:
    reads = _env_reads(p)
    examples = [f for f in p.files if EXAMPLE_ENV.search(f.rsplit("/", 1)[-1]) and f.rsplit("/", 1)[-1].startswith(".env")]
    if not examples:
        if reads:
            rel, line = next(iter(reads.values()))
            out.append(make(PACK, p, "PRD-006", "medium", rel, line, f"no .env.example; the code reads {len(reads)} env var(s)",
                            "add .env.example listing every variable with a placeholder value: " + ", ".join(sorted(reads)[:12])))
        return
    documented = set()
    for rel in examples:
        for i, raw in enumerate(p.text(rel).splitlines(), 1):
            m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", raw)
            if not m:
                continue
            key, value = m.group(1), m.group(2).strip().strip("'\"")
            documented.add(key)
            real = any(rx.search(value) for rx, _, _ in KEY_FORMATS)
            if not real and re.search(r"SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE", key, re.I) and len(value) >= 16 \
                    and not PLACEHOLDER.search(value) and re.search(r"\d", value) and re.search(r"[A-Za-z]", value):
                real = _entropy(value) > 3.5
            if real:
                out.append(make(PACK, p, "PRD-006", "high", rel, i, f"{key} in {rel} looks like a real secret",
                                "replace it with a placeholder such as change-me and rotate the real value", secret=value))
    missing = sorted(set(reads) - documented)
    if missing:
        out.append(make(PACK, p, "PRD-006", "medium", examples[0], 1,
                        f"{len(missing)} env var(s) read by the code are missing from .env.example: {', '.join(missing[:12])}"
                        + (" ..." if len(missing) > 12 else ""), "add each one with a placeholder value and a one-line comment"))


def check_alembic(p: Project, out: list[Finding]) -> None:
    uses_sql = [f for f in p.python_files() if re.search(r"^\s*(?:from|import) (?:sqlalchemy|sqlmodel)", p.text(f), re.M)]
    if not uses_sql:
        return
    revisions = [f for f in p.files if re.search(r"(^|/)(?:alembic|migrations)/versions/[^/]+\.py$", f)]
    has_env = any(re.search(r"(^|/)(?:alembic|migrations)/env\.py$", f) for f in p.files) or p.named(r"^alembic\.ini$")
    if not has_env:
        out.append(make(PACK, p, "PRD-003", "high", uses_sql[0], 1, "SQLAlchemy models but no Alembic setup",
                        "add alembic.ini, alembic/env.py and an initial revision generated from the models"))
        return
    real = [f for f in revisions if re.search(r"op\.(?:create_table|add_column|create_index|execute|alter_column|create_foreign_key)", p.text(f))]
    if not real:
        out.append(make(PACK, p, "PRD-003", "high", (revisions or p.named(r"^alembic\.ini$") or uses_sql)[0], 1,
                        "Alembic has no revision that creates the schema",
                        "generate the initial revision (alembic revision --autogenerate) and commit it"))


def check_containers(p: Project, has_backend: bool, out: list[Finding]) -> None:
    dockerfiles = p.named(r"^Dockerfile(?:\.[\w.-]+)?$|\.Dockerfile$")
    if has_backend and not dockerfiles:
        out.append(make(PACK, p, "PRD-009", "medium", "", 0, "no Dockerfile for the backend",
                        "add a multi-stage Dockerfile with a non-root user and a HEALTHCHECK"))
    for rel in dockerfiles:
        for i, line in enumerate(p.text(rel).splitlines(), 1):
            # RUN happens at build time against no database; only the start command reaches production data.
            if re.match(r"\s*(CMD|ENTRYPOINT)\b", line, re.I) and re.search(r"\bseed\w*(?:\.py)?\b", line, re.I) \
                    and not re.search(r"\bif\b|\[\s|\btest\b", line):
                out.append(make(PACK, p, "PRD-013", "medium", rel, i, "container start runs the demo seed unconditionally",
                                "gate seeding behind an env flag (SEED_DEMO=1) that is off in production"))
    for rel in p.files:
        if rel.endswith(".sh") and not is_test_path(rel) and re.search(r"entrypoint|start|run|boot", rel, re.I):
            depth = 0
            for i, line in enumerate(p.text(rel).splitlines(), 1):
                s = line.strip()
                depth += bool(re.match(r"(if|case)\b", s)) - bool(re.match(r"(fi|esac)\b", s))
                if depth == 0 and re.search(r"python\S*\s+(?:-m\s+)?\S*seed", s) and not re.search(r"\[\s|\btest\b|&&|\|\|", s.split("python")[0]):
                    out.append(make(PACK, p, "PRD-013", "medium", rel, i, "entrypoint runs the demo seed unconditionally",
                                    "wrap it: if [ \"$SEED_DEMO\" = \"1\" ]; then ...; fi"))
    for rel in p.named(r"^(?:docker-)?compose[\w.-]*\.ya?ml$"):
        try:
            data = yaml.safe_load(p.text(rel)) or {}
        except yaml.YAMLError as e:
            logger.warning("rulepacks: cannot parse %s: %s", rel, e)
            continue
        services = data.get("services") if isinstance(data, dict) else None
        for name, svc in (services or {}).items():
            if not isinstance(svc, dict) or "healthcheck" in svc:
                continue
            cmd = str(svc.get("command", "")) + str(svc.get("entrypoint", ""))
            if str(svc.get("restart", "")).strip("'\"") == "no" or re.search(r"alembic|migrat|seed", cmd + name, re.I):
                continue  # one-shot jobs exit; a healthcheck does not apply
            text = p.text(rel)
            out.append(make(PACK, p, "PRD-009", "low", rel, line_of(text, max(0, text.find(f"{name}:"))),
                            f"compose service '{name}' has no healthcheck",
                            "add healthcheck (pg_isready for postgres, redis-cli ping, curl /health for the API) and "
                            "depends_on: condition: service_healthy"))


def check_ci(p: Project, out: list[Finding]) -> None:
    ci = [f for f in p.files if re.match(r"\.github/workflows/[^/]+\.ya?ml$", f) or f in (".gitlab-ci.yml", ".circleci/config.yml",
                                                                                     "bitbucket-pipelines.yml")]
    if not ci and not (p.root / "Jenkinsfile").exists():
        out.append(make(PACK, p, "PRD-010", "medium", "", 0, "no CI workflow",
                        "add .github/workflows/ci.yml running lint, tests and the frontend build on every push"))


def check_placeholders(p: Project, out: list[Finding]) -> None:
    for rel in p.python_files() + p.web_files():
        if NON_PROD_PATH.search(rel):
            continue
        text = p.text(rel)
        for i, line in enumerate(text.splitlines(), 1):
            if ELISION.search(line):
                out.append(make(PACK, p, "PRD-011", "high", rel, i, "elided or unimplemented code", "write the full implementation"))
            elif TODO.search(line):
                out.append(make(PACK, p, "PRD-011", "medium", rel, i, f"{TODO.search(line).group(1)} left in shipped code",
                                "finish the work or delete the note"))
        tree = p.tree(rel) if rel.endswith(".py") else None
        for fn in ast.walk(tree) if tree is not None else []:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any("abstract" in ast.unparse(d) or "overload" in ast.unparse(d) for d in fn.decorator_list):
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Raise) and n.exc is not None and "NotImplementedError" in ast.unparse(n.exc):
                    out.append(make(PACK, p, "PRD-011", "high", rel, n.lineno, f"{fn.name}() raises NotImplementedError",
                                    "implement it, or remove the feature and its route"))


def check_readme(p: Project, out: list[Finding]) -> None:
    readme = next((f for f in p.files if "/" not in f and f.lower() in ("readme.md", "readme.rst", "readme.txt", "readme")), None)
    if readme is None:
        out.append(make(PACK, p, "PRD-012", "medium", "", 0, "no README", "add README.md with setup, run, test and deploy steps"))
        return
    text = p.text(readme)
    missing = []
    if not re.search(r"docker compose up|docker-compose up|npm (?:run|start|install)|uvicorn|pip install|make \w+|"
                     r"^#+\s*(?:getting started|quick ?start|run|running|setup|install)", text, re.I | re.M):
        missing.append("how to run it locally")
    if not re.search(r"deploy|production|docker|kubernetes|render\.com|fly\.io|railway|vercel", text, re.I):
        missing.append("how to deploy it")
    if missing:
        out.append(make(PACK, p, "PRD-012", "low", readme, 1, f"README does not say {' or '.join(missing)}",
                        "add Run locally and Deploy sections with exact commands and the env vars to set"))


def check_prodready(p: Project) -> list[Finding]:
    out: list[Finding] = []
    has_backend = any(re.search(r"\bFastAPI\(|\bAPIRouter\(", p.text(f)) for f in p.python_files())
    if has_backend:
        check_health(p, collect_routes(p), out)
    check_code(p, out)
    check_alembic(p, out)
    check_env_example(p, out)
    check_containers(p, has_backend, out)
    check_ci(p, out)
    check_placeholders(p, out)
    check_readme(p, out)
    return out
