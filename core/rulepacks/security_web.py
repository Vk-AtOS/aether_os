"""Regex security checks for frontend code, containers, dependency files and committed config.

SEC-001 provider key / token formats and credentials in URLs (any text file)
SEC-003 private key material             SEC-006 dev server flags in container commands
SEC-014 tokens in localStorage           SEC-015 raw HTML / eval in the browser
SEC-016 target=_blank without rel        SEC-017 container runs as root / unpinned base image
SEC-020 unpinned dependencies            SEC-021 committed .env file / secret exposed through VITE_*
SEC-022 Dockerfile without HEALTHCHECK
"""
from __future__ import annotations

import json
import logging
import re

from aether_os.core.rulepacks.base import Finding, Project, is_test_path, line_of, make
from aether_os.core.rulepacks.jsx import iter_tags, strip_comments
from aether_os.core.rulepacks.security_py import PLACEHOLDER

logger = logging.getLogger(__name__)
PACK = "security"

# (pattern, label, severity). Shapes of real provider credentials; test-mode keys are lower severity.
KEY_FORMATS = (
    (re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"), "AWS access key id", "critical"),
    (re.compile(r"\b[rs]k_live_[0-9a-zA-Z]{16,}"), "Stripe live key", "critical"),
    (re.compile(r"\bsk_test_[0-9a-zA-Z]{16,}"), "Stripe test key", "medium"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "Google API key", "high"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"), "GitHub token", "critical"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token", "high"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "Anthropic API key", "critical"),
    (re.compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{32,}"), "OpenAI-style API key", "critical"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "JWT literal", "medium"),
)
CRED_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s:@'\"]+):([^/\s:@'\"]+)@")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
EXAMPLE_ENV = re.compile(r"\.env\.(?:example|sample|template|dist|defaults)$|\.example$")
SKIP_SECRET_SCAN = re.compile(r"(?:^|/)(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock|poetry\.lock)$|\.md$")


def _secret_formats(p: Project, out: list[Finding]) -> None:
    for rel in p.files:
        if is_test_path(rel) or SKIP_SECRET_SCAN.search(rel) or EXAMPLE_ENV.search(rel):
            continue
        text = p.text(rel)
        if PRIVATE_KEY.search(text):
            out.append(make(PACK, p, "SEC-003", "critical", rel, line_of(text, PRIVATE_KEY.search(text).start()),
                            "private key committed in the project", "delete the file, rotate the key, mount it at runtime as a secret"))
        for rx, label, sev in KEY_FORMATS:
            for m in rx.finditer(text):
                out.append(make(PACK, p, "SEC-001", sev, rel, line_of(text, m.start()), f"{label} in source",
                                "revoke it, then read the value from an environment variable"))
        for m in CRED_URL.finditer(text):
            pw = m.group(2)
            if pw.startswith(("$", "{", "<", "%")) or PLACEHOLDER.search(pw):
                continue
            out.append(make(PACK, p, "SEC-001", "medium", rel, line_of(text, m.start()),
                            f"credentials embedded in a connection URL (user {m.group(1)})",
                            "build the URL from environment variables; keep only placeholders in .env.example"))


def _frontend(p: Project, out: list[Finding]) -> None:
    for rel in p.web_files():
        text = strip_comments(p.text(rel))
        for m in re.finditer(r"(?:localStorage|sessionStorage)\s*(?:\.setItem\(\s*([^,)]*)|\[\s*([^\]]+)\]\s*=|\.(\w+)\s*=(?!=))", text):
            key = next(g for g in m.groups() if g is not None)
            if re.search(r"token|jwt|auth|session|access|refresh|bearer", key, re.I):
                out.append(make(PACK, p, "SEC-014", "medium", rel, line_of(text, m.start()),
                                "auth token stored in web storage (readable by any injected script)",
                                "have the backend set an HttpOnly, Secure, SameSite cookie; keep tokens out of localStorage"))
        for m in re.finditer(r"dangerouslySetInnerHTML\s*=\s*\{\{\s*__html\s*:", text):
            expr = text[m.end():m.end() + 200].split("}}")[0]
            if not re.search(r"sanitize|DOMPurify|purify", expr, re.I):
                out.append(make(PACK, p, "SEC-015", "high", rel, line_of(text, m.start()), "dangerouslySetInnerHTML without sanitizing",
                                "render text normally, or wrap the value in DOMPurify.sanitize(...)"))
        for m in re.finditer(r"\.innerHTML\s*=(?!=)|\bdocument\.write\(|(?<![\w.])eval\(|\bnew Function\(", text):
            line = text.splitlines()[line_of(text, m.start()) - 1]
            if "sanitize" in line or "DOMPurify" in line:
                continue
            sev = "high" if "eval" in m.group(0) or "Function" in m.group(0) else "medium"
            out.append(make(PACK, p, "SEC-015", sev, rel, line_of(text, m.start()), f"{m.group(0).strip('(= ')} in browser code",
                            "build DOM with React elements or textContent; never evaluate strings"))
        if rel.endswith((".tsx", ".jsx")):
            for t in iter_tags(text, ("a", "Link", "NavLink")):
                target = (t.value("target") or "").strip("'\" ")
                if target != "_blank" or "{..." in t.attrs:
                    continue
                rel_v = t.value("rel") or ""
                if "noopener" not in rel_v and "noreferrer" not in rel_v:
                    out.append(make(PACK, p, "SEC-016", "low", rel, t.line, 'target="_blank" without rel="noopener noreferrer"',
                                    'add rel="noopener noreferrer"'))
    for rel in p.files:
        if is_test_path(rel):
            continue
        for m in re.finditer(r"\bVITE_\w*(?:SECRET|PRIVATE|PASSWORD|SERVICE_ROLE)\w*", p.text(rel)):
            out.append(make(PACK, p, "SEC-021", "high", rel, line_of(p.text(rel), m.start()),
                            f"{m.group(0)} is bundled into the public JavaScript", "keep secrets on the backend; VITE_* values are public"))
            break


def _dockerfile_lines(text: str) -> list[tuple[int, str]]:
    """(line, instruction text) with backslash continuations joined and comments dropped."""
    out, buf, start = [], "", 0
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not buf and (not s or s.startswith("#")):
            continue
        if not buf:
            start = i
        buf += " " + s.rstrip("\\").strip()
        if not s.endswith("\\"):
            out.append((start, buf.strip()))
            buf = ""
    if buf:
        out.append((start, buf.strip()))
    return out


def _docker(p: Project, out: list[Finding]) -> None:
    for rel in p.named(r"^Dockerfile(?:\.[\w.-]+)?$|\.Dockerfile$"):
        ins = _dockerfile_lines(p.text(rel))
        stages, final_from, user, health = set(), None, None, False
        for line, s in ins:
            word, _, rest = s.partition(" ")
            word = word.upper()
            if word == "FROM":
                parts = [x for x in rest.split() if not x.startswith("--")]
                image = parts[0] if parts else ""
                if len(parts) >= 3 and parts[1].lower() == "as":
                    stages.add(parts[2].lower())
                final_from, user, health = (line, image), None, False
                if image.lower() in stages or image == "scratch" or "$" in image:
                    continue
                tag = image.rsplit("/", 1)[-1]
                if "@sha256:" not in image and (":" not in tag or tag.endswith(":latest")):
                    out.append(make(PACK, p, "SEC-017", "medium", rel, line, f"base image {image} is not pinned to a version",
                                    "pin a version tag (python:3.12-slim, node:20-alpine) or a digest"))
            elif word == "USER":
                user = (line, rest.strip())
            elif word == "HEALTHCHECK":
                health = not rest.strip().upper().startswith("NONE")
            elif word in ("CMD", "ENTRYPOINT") and re.search(r"--reload\b|\bnpm\"?,?\s*\"?run\"?,?\s*\"?dev\b|vite\"?\s*\]?$", rest):
                out.append(make(PACK, p, "SEC-006", "medium", rel, line, "container starts a development server",
                                "run the production server (uvicorn without --reload / gunicorn, or nginx serving the build)"))
            elif word in ("ENV", "ARG") and re.search(r"(?i)(?:password|secret|token|api_?key)\w*\s*[= ]\s*['\"]?[^\s'\"$]{6,}", rest) \
                    and not PLACEHOLDER.search(rest):
                out.append(make(PACK, p, "SEC-001", "high", rel, line, "secret baked into the image with ENV/ARG",
                                "pass it at runtime (compose env_file / orchestrator secret)"))
        if final_from is None:
            continue
        image = final_from[1].lower()
        if user is None or user[1] in ("root", "0", "0:0"):
            unprivileged = "unprivileged" in image or "distroless" in image and "nonroot" in image
            if not unprivileged:
                sev = "low" if image.startswith(("nginx", "nginxinc/")) else "medium"
                out.append(make(PACK, p, "SEC-017", sev, rel, (user or final_from)[0], "container runs as root",
                                "create a user (RUN useradd -r app) and switch to it with USER app before CMD"))
        if not health:
            out.append(make(PACK, p, "SEC-022", "low", rel, final_from[0], "final image has no HEALTHCHECK",
                            "add HEALTHCHECK CMD curl -fsS http://localhost:<port>/health || exit 1 (or the compose healthcheck)"))


def _deps(p: Project, out: list[Finding]) -> None:
    for rel in p.named(r"^requirements[\w.-]*\.txt$"):
        loose, first = [], 0
        for i, raw in enumerate(p.text(rel).splitlines(), 1):
            s = raw.split("#", 1)[0].strip()
            if not s or s.startswith(("-", "--")) or "://" in s:
                continue
            if "==" not in s:
                loose.append(re.split(r"[<>=!~;\[ ]", s, maxsplit=1)[0])
                first = first or i
        if loose:
            out.append(make(PACK, p, "SEC-020", "low", rel, first, f"{len(loose)} unpinned requirement(s): {', '.join(loose[:8])}",
                            "pin exact versions (pkg==1.2.3) or install from a lock file"))
    for rel in p.named(r"^package\.json$"):
        try:
            data = json.loads(p.text(rel))
        except ValueError as e:
            logger.warning("rulepacks: %s is not valid JSON: %s", rel, e)
            continue
        if not isinstance(data, dict):
            continue
        for section in ("dependencies", "devDependencies"):
            for name, ver in (data.get(section) or {}).items():
                if str(ver).strip() in ("*", "latest", "", "x"):
                    out.append(make(PACK, p, "SEC-020", "medium", rel, line_of(p.text(rel), p.text(rel).find(f'"{name}"')),
                                    f"{name} has no version range ({ver!r})", "use a caret range and commit the lock file"))
    for rel in p.files:
        name = rel.rsplit("/", 1)[-1]
        if name == ".env" or (name.startswith(".env.") and not EXAMPLE_ENV.search(name)):
            text = p.text(rel)
            secretish = re.search(r"(?im)^\s*\w*(?:SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE)\w*\s*=\s*['\"]?[^\s'\"#]{6,}", text)
            out.append(make(PACK, p, "SEC-021", "high" if secretish else "medium", rel, 1,
                            "environment file with values is part of the project",
                            "remove it, add .env to .gitignore and .dockerignore, ship .env.example with placeholders"))


def scan_web(p: Project) -> list[Finding]:
    out: list[Finding] = []
    _secret_formats(p, out)
    _frontend(p, out)
    _docker(p, out)
    _deps(p, out)
    return out
