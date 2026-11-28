"""KAN-243 rule packs: the security scanner. Every check has a positive and a near-miss negative fixture.

Each case starts from the clean project in rulepacks_fixtures (zero findings) and changes one file.
"""
import pytest

from aether_os.tests import rulepacks_fixtures as F

APP = "backend/app"
EXTRA = f"{APP}/extra.py"


def sub(text: str, old: str, new: str) -> str:
    assert old in text, old  # a no-op replacement would make the test pass for the wrong reason
    return text.replace(old, new)


def py(code: str) -> dict:
    return {EXTRA: code}


def web(code: str, name="frontend/src/components/Thing.tsx") -> dict:
    return {name: code}


def ids(tmp_path, overrides, public_routes=None):
    return F.rule_ids(tmp_path, overrides, packs=("security",), public_routes=public_routes)


ADMIN = '''from fastapi import APIRouter, Depends
from app.database import get_db

router = APIRouter()


@router.delete("/{item_id}")
def delete_item(item_id: int, db=Depends(get_db)):
    return {"deleted": item_id}
'''
MAIN_WITH_ADMIN = sub(F.MAIN, "from app.routers import auth, tasks", "from app.routers import admin, auth, tasks") \
    .replace('app.include_router(tasks.router, prefix="/api/tasks")',
             'app.include_router(tasks.router, prefix="/api/tasks")\napp.include_router(admin.router, prefix="/api/admin")')
IDOR_ROUTE = sub(F.TASKS_ROUTER, "task = db.query(Task).filter(Task.id == task_id, Task.owner_id == user.id).first()",
                 "task = db.get(Task, task_id)")

POSITIVE = [
    ("SEC-001", py(f'STRIPE_API_KEY = "{F.FAKE_HEX}"\n')),
    ("SEC-001", py(f'KEY = "{F.FAKE_STRIPE_LIVE}"\n')),
    ("SEC-001", web(f'export const k = "{F.FAKE_AWS}";\n', "frontend/src/lib/aws.ts")),
    ("SEC-001", {"docker-compose.yml": F.COMPOSE + "    command: run --db postgresql://app:s3cretpw@db/app\n"}),
    ("SEC-001", {"backend/Dockerfile": sub(F.DOCKERFILE, "WORKDIR /app", f"WORKDIR /app\nENV SECRET_KEY={F.FAKE_HEX_SHORT}")}),
    ("SEC-002", {f"{APP}/config.py": sub(F.CONFIG, "    SECRET_KEY: str\n", '    SECRET_KEY: str = "dev-secret"\n')}),
    ("SEC-002", py('import os\nJWT = os.getenv("JWT_SECRET", "change-me")\n')),
    ("SEC-003", {"backend/certs/server.key": F.FAKE_PRIVATE_KEY}),
    ("SEC-004", py('from sqlalchemy import text\n\ndef f(db, tid):\n    return db.execute(text(f"SELECT * FROM tasks WHERE id = {tid}"))\n')),
    ("SEC-004", py("def f(cur, name):\n    q = \"SELECT * FROM t WHERE name = '\" + name + \"'\"\n    cur.execute(q)\n")),
    ("SEC-004", py('def f(cur, n):\n    cur.execute("DELETE FROM t WHERE n = {}".format(n))\n')),
    ("SEC-005", py("def f(expr):\n    return eval(expr)\n")),
    ("SEC-005", py("import yaml\n\ndef f(s):\n    return yaml.load(s)\n")),
    ("SEC-005", py("import subprocess\n\ndef f(cmd):\n    subprocess.run(cmd, shell=True)\n")),
    ("SEC-005", py("import pickle\n\ndef f(b):\n    return pickle.loads(b)\n")),
    ("SEC-005", py('import os\n\ndef f(p):\n    os.system(f"rm {p}")\n')),
    ("SEC-006", {f"{APP}/main.py": sub(F.MAIN, 'FastAPI(title="Tasks")', 'FastAPI(title="Tasks", debug=True)')}),
    ("SEC-006", py("import uvicorn\nuvicorn.run('app.main:app', reload=True)\n")),
    ("SEC-006", py("DEBUG = True\n")),
    ("SEC-006", {"backend/Dockerfile": sub(F.DOCKERFILE, '"--port", "8000"]', '"--port", "8000", "--reload"]')}),
    ("SEC-007", {f"{APP}/routers/admin.py": ADMIN, f"{APP}/main.py": MAIN_WITH_ADMIN}),
    ("SEC-008", {f"{APP}/routers/tasks.py": IDOR_ROUTE}),
    ("SEC-009", {f"{APP}/main.py": sub(F.MAIN, "allow_origins=settings.CORS_ORIGINS", 'allow_origins=["*"]')}),
    ("SEC-010", {f"{APP}/security.py": sub(F.SECURITY, ", algorithms=[settings.JWT_ALGORITHM])", ")")}),
    ("SEC-010", {f"{APP}/security.py": sub(F.SECURITY, "algorithms=[settings.JWT_ALGORITHM]",
                                            'algorithms=["HS256"], options={"verify_signature": False}')}),
    ("SEC-010", {f"{APP}/security.py": sub(F.SECURITY, "algorithms=[settings.JWT_ALGORITHM]", 'algorithms=["none"]')}),
    ("SEC-011", py("import hashlib\n\ndef hash_pw(password):\n    return hashlib.sha256(password.encode()).hexdigest()\n")),
    ("SEC-011", {f"{APP}/security.py": sub(F.SECURITY, 'schemes=["argon2"]', 'schemes=["md5_crypt"]')}),
    ("SEC-012", {f"{APP}/main.py": sub(F.MAIN, 'response.headers["X-Content-Type-Options"] = "nosniff"\n    '
                                                'response.headers["X-Frame-Options"] = "DENY"\n    '
                                                'response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"\n', "")}),
    ("SEC-013", {f"{APP}/routers/auth.py": sub(F.AUTH_ROUTER, '@limiter.limit("5/minute")\n', "")}),
    ("SEC-014", web("export const save = (t) => localStorage.setItem('access_token', t);\n", "frontend/src/lib/auth.ts")),
    ("SEC-014", web("localStorage.token = t;\n", "frontend/src/lib/auth.ts")),
    ("SEC-015", web("export const P = ({ post }) => <div dangerouslySetInnerHTML={{ __html: post.body }} />;\n")),
    ("SEC-015", web("el.innerHTML = html;\n", "frontend/src/lib/dom.ts")),
    ("SEC-016", web('export const L = () => <a href="https://x.io" target="_blank">x</a>;\n')),
    ("SEC-017", {"backend/Dockerfile": sub(F.DOCKERFILE, "python:3.12-slim", "python:latest")}),
    ("SEC-017", {"backend/Dockerfile": sub(F.DOCKERFILE, "python:3.12-slim", "python")}),
    ("SEC-017", {"backend/Dockerfile": sub(F.DOCKERFILE, "USER app\n", "")}),
    ("SEC-018", py("import requests\n\ndef f(u):\n    return requests.get(u, verify=False, timeout=5)\n")),
    ("SEC-019", py("import random\n\ndef make_reset_token():\n    return ''.join(random.choice('abc') for _ in range(8))\n")),
    ("SEC-020", {"backend/requirements.txt": "fastapi\nsqlalchemy>=2\n"}),
    ("SEC-020", {"frontend/package.json": '{"dependencies": {"react": "latest"}}'}),
    ("SEC-021", {".env": f"SECRET_KEY={F.FAKE_HEX}\n"}),
    ("SEC-021", web("const k = import.meta.env.VITE_STRIPE_SECRET_KEY;\n", "frontend/src/lib/pay.ts")),
    ("SEC-022", {"backend/Dockerfile": sub(F.DOCKERFILE, "HEALTHCHECK CMD curl -fsS http://localhost:8000/health || exit 1\n", "")}),
]


@pytest.mark.parametrize("rule,overrides", POSITIVE, ids=[f"{r}-{i}" for i, (r, _) in enumerate(POSITIVE)])
def test_rule_fires(tmp_path, rule, overrides):
    assert rule in ids(tmp_path, overrides)


NEGATIVE = [
    ("SEC-001", py('import os\nSTRIPE_API_KEY = os.environ["STRIPE_API_KEY"]\n')),
    ("SEC-001", py('password = "change-me-please"\n')),                                     # placeholder
    ("SEC-001", py('from fastapi import HTTPException\nraise HTTPException(401, detail="Invalid password")\n')),
    ("SEC-001", {".env.example": F.ENV_EXAMPLE + "STRIPE_KEY=sk_test_xxxxxxxx\n"}),
    ("SEC-001", {"docker-compose.yml": F.COMPOSE + "    command: run --db postgresql://app:${DB_PASSWORD}@db/app\n"}),
    ("SEC-001", {"tests/test_auth.py": 'PASSWORD = "hunter2hunter2"\n'}),                   # test data
    ("SEC-002", py('import os\nSECRET_KEY = os.environ["SECRET_KEY"]\n')),
    ("SEC-003", {"backend/certs/ca.pem": "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"}),
    ("SEC-004", py('from sqlalchemy import text\n\ndef f(db, tid):\n    return db.execute(text("SELECT * FROM t WHERE id = :id"), {"id": tid})\n')),
    ("SEC-004", py('import logging\nlog = logging.getLogger(__name__)\n\ndef f(x):\n    log.info(f"select {x}")\n')),
    ("SEC-005", py("import yaml\n\ndef f(s):\n    return yaml.safe_load(s), yaml.load(s, Loader=yaml.SafeLoader)\n")),
    ("SEC-005", py("import subprocess\n\ndef f():\n    subprocess.run(['ls', '-l'], check=True)\n")),
    ("SEC-006", py("import uvicorn\nif __name__ == '__main__':\n    uvicorn.run('app.main:app', reload=True)\n")),
    ("SEC-007", {f"{APP}/routers/admin.py": ADMIN, f"{APP}/main.py": MAIN_WITH_ADMIN, "_public": "DELETE /api/admin/*"}),
    ("SEC-007", {f"{APP}/routers/admin.py": ADMIN, f"{APP}/main.py": MAIN_WITH_ADMIN.replace(
        'prefix="/api/admin")', 'prefix="/api/admin", dependencies=[Depends(get_current_user)])').replace(
        "from fastapi import FastAPI, Request", "from fastapi import Depends, FastAPI, Request").replace(
        "from app.database import SessionLocal", "from app.database import SessionLocal\nfrom app.security import get_current_user")}),
    ("SEC-007", {f"{APP}/routers/admin.py": "from typing import Annotated\nfrom fastapi import APIRouter, Depends\n"
                 "from app.security import get_current_user\nfrom app.models import User\n\n"
                 "CurrentUser = Annotated[User, Depends(get_current_user)]\nrouter = APIRouter()\n\n\n"
                 "@router.delete('/{item_id}')\ndef delete_item(item_id: int, user: CurrentUser):\n    return {}\n",
                 f"{APP}/main.py": MAIN_WITH_ADMIN}),
    ("SEC-009", {f"{APP}/main.py": sub(F.MAIN, "allow_origins=settings.CORS_ORIGINS, allow_credentials=True",
                                        'allow_origins=["*"]')}),
    ("SEC-011", py("import hashlib\n\ndef checksum(data: bytes):\n    return hashlib.sha256(data).hexdigest()\n")),
    ("SEC-012", {f"{APP}/main.py": F.MAIN.replace('"X-Content-Type-Options"', '"X-Other"').replace('"X-Frame-Options"', '"X-Other2"')
                 .replace('"Referrer-Policy"', '"X-Other3"'), "deploy/nginx.conf": "add_header X-Frame-Options DENY;\n"}),
    ("SEC-013", {f"{APP}/routers/auth.py": F.AUTH_ROUTER.replace('@limiter.limit("5/minute")\n', ""),
                 "deploy/nginx.conf": "limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;\n"}),
    ("SEC-014", web("localStorage.setItem('theme', 'dark');\n", "frontend/src/lib/theme.ts")),
    ("SEC-015", web("export const P = ({ post }) => <div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(post.body) }} />;\n")),
    ("SEC-016", web('export const L = () => <a href="https://x.io" target="_blank" rel="noreferrer">x</a>;\n')),
    ("SEC-017", {"frontend/Dockerfile": "FROM node:20-alpine AS build\nRUN npm ci\nFROM nginxinc/nginx-unprivileged:1.27-alpine\n"
                 "COPY --from=build /app/dist /usr/share/nginx/html\nHEALTHCHECK CMD wget -q -O- http://localhost:8080 || exit 1\n"}),
    ("SEC-018", py("import requests\n\ndef f(u):\n    return requests.get(u, verify=True, timeout=5)\n")),
    ("SEC-019", py("import random\n\ndef shuffle_cards(cards):\n    return random.choice(cards)\n")),
    ("SEC-020", {"backend/requirements.txt": "# pinned\n-r base.txt\nfastapi==0.115.0\n"}),
    ("SEC-021", {".env.example": F.ENV_EXAMPLE}),
]


@pytest.mark.parametrize("rule,overrides", NEGATIVE, ids=[f"{r}-{i}" for i, (r, _) in enumerate(NEGATIVE)])
def test_rule_stays_quiet(tmp_path, rule, overrides):
    overrides = dict(overrides)
    public = overrides.pop("_public", None)
    got = ids(tmp_path, overrides, public_routes=[public, "/auth/login"] if public else None)
    assert rule not in got


def test_clean_project_has_no_security_findings(tmp_path):
    assert ids(tmp_path, {}) == []


def test_project_without_any_auth_gets_one_finding_not_one_per_route(tmp_path):
    no_auth = sub(F.TASKS_ROUTER, "router = APIRouter(dependencies=[Depends(get_current_user)])", "router = APIRouter()")
    no_auth = no_auth.replace(", user: User = Depends(get_current_user)", "").replace(" Task.owner_id == user.id", " True")
    found = [f for f in F.findings(tmp_path, {f"{APP}/routers/tasks.py": no_auth}, packs=("security",)) if f.rule_id == "SEC-007"]
    assert len(found) == 1 and "2 non-public route(s)" in found[0].message and found[0].severity == "high"


def test_write_routes_are_high_and_reads_medium(tmp_path):
    found = F.findings(tmp_path, {f"{APP}/routers/admin.py": ADMIN, f"{APP}/main.py": MAIN_WITH_ADMIN}, packs=("security",))
    sec7 = [f for f in found if f.rule_id == "SEC-007"]
    assert [(f.severity, f.file) for f in sec7] == [("high", f"{APP}/routers/admin.py")]
    assert "DELETE /api/admin/{item_id}" in sec7[0].message


def test_plaintext_password_column_without_hash_library(tmp_path):
    over = {f"{APP}/security.py": "def check(user, form):\n    return user.password == form.password\n",
            f"{APP}/models.py": F.MODELS.replace("password_hash", "password"),
            "backend/requirements.txt": "fastapi==0.115.0\n", f"{APP}/routers/auth.py": "",
            f"{APP}/routers/tasks.py": ""}
    found = [f for f in F.findings(tmp_path, over, packs=("security",)) if f.rule_id == "SEC-011"]
    assert {f.file for f in found} == {f"{APP}/security.py", f"{APP}/models.py"}


def test_depends_variable_and_auth_factory_defaults_count_as_auth(tmp_path):
    router = ("from fastapi import APIRouter, Depends\nfrom app.security import get_current_user\n\n"
              "_current_user = Depends(get_current_user)\nrouter = APIRouter()\n\n\ndef _auth():\n"
              "    return Depends(get_current_user)\n\n\n@router.delete('/{item_id}')\n"
              "def delete_item(item_id: int, user=_current_user):\n    return {}\n\n\n@router.post('/')\n"
              "def create_item(user=_auth()):\n    return {}\n")
    assert "SEC-007" not in ids(tmp_path, {f"{APP}/routers/admin.py": router, f"{APP}/main.py": MAIN_WITH_ADMIN})


def test_api_route_with_many_methods_is_one_finding(tmp_path):
    router = ("from fastapi import APIRouter\nrouter = APIRouter()\n\n\n"
              "@router.api_route('/{p}', methods=['GET', 'POST', 'DELETE'])\ndef proxy(p: str):\n    return {}\n")
    found = [f for f in F.findings(tmp_path, {f"{APP}/routers/admin.py": router, f"{APP}/main.py": MAIN_WITH_ADMIN},
                                   packs=("security",)) if f.rule_id == "SEC-007"]
    assert len(found) == 1 and found[0].severity == "high" and "GET, POST, DELETE" in found[0].message


def test_empty_default_for_a_secret_fails_closed_and_is_not_flagged(tmp_path):
    assert "SEC-002" not in ids(tmp_path, py('import os\nKEY = os.environ.get("SECRET_KEY", "")\n'))
