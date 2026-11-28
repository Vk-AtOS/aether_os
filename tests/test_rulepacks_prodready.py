"""KAN-243 rule packs: prod-readiness checks over a generated project tree (positive + negative per check)."""
import pytest

from aether_os.tests import rulepacks_fixtures as F

APP = "backend/app"
EXTRA = f"{APP}/extra.py"


def sub(text: str, old: str, new: str) -> str:
    assert old in text, old
    return text.replace(old, new)


def ids(tmp_path, overrides):
    return F.rule_ids(tmp_path, overrides, packs=("prodready",))


NO_HEALTH = sub(F.MAIN, '@app.get("/health")\ndef health():\n    return {"status": "ok"}\n', "")
READY_NO_DB = sub(F.MAIN, '    with SessionLocal() as db:\n        db.execute(text("SELECT 1"))\n', "")
CREATE_ALL = F.MAIN + "\nfrom app.database import Base, engine\nBase.metadata.create_all(bind=engine)\n"
SEEDED = F.MAIN + "\nfrom app.seed import seed_demo_data\n\n\n@app.on_event(\"startup\")\ndef boot():\n    seed_demo_data()\n"

POSITIVE = [
    ("PRD-001", {f"{APP}/main.py": NO_HEALTH}),
    ("PRD-002", {f"{APP}/main.py": READY_NO_DB}),
    ("PRD-003", {"backend/alembic/versions/0001_init.py": None}),
    ("PRD-003", {"backend/alembic/versions/0001_init.py": "def upgrade():\n    pass\n"}),
    ("PRD-003", {"backend/alembic.ini": None, "backend/alembic/env.py": None, "backend/alembic/versions/0001_init.py": None}),
    ("PRD-004", {f"{APP}/main.py": CREATE_ALL}),
    ("PRD-005", {f"{APP}/config.py": sub(F.CONFIG, "    DATABASE_URL: str\n", '    DATABASE_URL: str = "sqlite:///./app.db"\n')}),
    ("PRD-005", {f"{APP}/database.py": sub(F.DATABASE, "create_engine(settings.DATABASE_URL", 'create_engine("sqlite:///./app.db"')}),
    ("PRD-005", {EXTRA: 'import os\nURL = os.getenv("DATABASE_URL", "sqlite:///dev.db")\n'}),
    ("PRD-006", {EXTRA: 'import os\nKEY = os.environ["MAPS_API_KEY"]\n'}),
    ("PRD-006", {"frontend/src/lib/x.ts": "export const s = import.meta.env.VITE_SENTRY_DSN;\n"}),
    ("PRD-006", {".env.example": F.ENV_EXAMPLE + f"WEBHOOK_SECRET={F.FAKE_WEBHOOK}\n"}),
    ("PRD-006", {".env.example": None}),
    ("PRD-007", {EXTRA: "def f(x):\n    print(x)\n"}),
    ("PRD-007", {f"{APP}/main.py": sub(F.MAIN, "logging.basicConfig(level=settings.LOG_LEVEL)\n", "")}),
    ("PRD-008", {EXTRA: "import requests\n\ndef f(u):\n    return requests.get(u)\n"}),
    ("PRD-008", {EXTRA: "import httpx\n\ndef f(u):\n    return httpx.get(u, timeout=None)\n"}),
    ("PRD-009", {"docker-compose.yml": F.COMPOSE + "  redis:\n    image: redis:7-alpine\n"}),
    ("PRD-009", {"backend/Dockerfile": None}),
    ("PRD-010", {".github/workflows/ci.yml": None}),
    ("PRD-011", {EXTRA: "def f():\n    # TODO: handle errors\n    return 1\n"}),
    ("PRD-011", {EXTRA: "def refund(order):\n    raise NotImplementedError\n"}),
    ("PRD-011", {"frontend/src/pages/X.tsx": "export default function X() {\n  // ... rest of the component\n  return null;\n}\n"}),
    ("PRD-012", {"README.md": None}),
    ("PRD-012", {"README.md": "# Tasks\n\nA task app.\n"}),
    ("PRD-013", {f"{APP}/main.py": SEEDED}),
    ("PRD-013", {"backend/entrypoint.sh": "#!/bin/sh\nalembic upgrade head\npython -m app.seed\nexec uvicorn app.main:app\n"}),
    ("PRD-013", {"backend/Dockerfile": sub(F.DOCKERFILE, 'CMD ["uvicorn"', 'CMD python seed.py && exec ["uvicorn"')}),
]


@pytest.mark.parametrize("rule,overrides", POSITIVE, ids=[f"{r}-{i}" for i, (r, _) in enumerate(POSITIVE)])
def test_rule_fires(tmp_path, rule, overrides):
    assert rule in ids(tmp_path, overrides)


NEGATIVE = [
    ("PRD-001", {f"{APP}/main.py": sub(F.MAIN, '@app.get("/health")', '@app.get("/api/health")')}),
    ("PRD-004", {f"{APP}/main.py": F.MAIN + "\nfrom app.database import Base, engine\nif settings.LOG_LEVEL == 'TEST':\n"
                                           "    Base.metadata.create_all(bind=engine)\n"}),
    ("PRD-004", {"backend/tests/conftest.py": "from app.database import Base, engine\nBase.metadata.create_all(bind=engine)\n"}),
    ("PRD-005", {EXTRA: 'import os\nURL = os.environ["DATABASE_URL"]\n'}),
    ("PRD-006", {EXTRA: 'import os\nHOME = os.getenv("HOME")\n'}),                    # set by the OS
    ("PRD-007", {"backend/scripts/report.py": "print('done')\n"}),                     # scripts may print
    ("PRD-008", {EXTRA: "import requests\n\ndef f(u):\n    return requests.get(u, timeout=10)\n"}),
    ("PRD-008", {EXTRA: "import httpx\n\ndef f(u):\n    return httpx.get(u)\n"}),          # httpx has a default timeout
    ("PRD-009", {"docker-compose.yml": F.COMPOSE + "  migrate:\n    build: ./backend\n    command: alembic upgrade head\n"}),
    ("PRD-011", {EXTRA: "from abc import ABC, abstractmethod\n\nclass Store(ABC):\n    @abstractmethod\n"
                        "    def save(self):\n        raise NotImplementedError\n"}),
    ("PRD-011", {"frontend/src/pages/X.tsx": "export const phone = 'XXX-XXX-XXXX';\n"}),   # not a comment marker
    ("PRD-013", {f"{APP}/main.py": SEEDED.replace("    seed_demo_data()\n", "    if settings.SEED_DEMO:\n        seed_demo_data()\n")}),
    ("PRD-013", {"backend/entrypoint.sh": '#!/bin/sh\nif [ "$SEED_DEMO" = "1" ]; then\n  python -m app.seed\nfi\nexec uvicorn app.main:app\n'}),
]


@pytest.mark.parametrize("rule,overrides", NEGATIVE, ids=[f"{r}-{i}" for i, (r, _) in enumerate(NEGATIVE)])
def test_rule_stays_quiet(tmp_path, rule, overrides):
    assert rule not in ids(tmp_path, overrides)


def test_clean_project_has_no_prodready_findings(tmp_path):
    assert ids(tmp_path, {}) == []


def test_env_example_lists_the_missing_names(tmp_path):
    over = {EXTRA: 'import os\nA = os.getenv("MAPS_API_KEY")\nB = os.environ.get("SMTP_HOST")\n'}
    f = next(x for x in F.findings(tmp_path, over, packs=("prodready",)) if x.rule_id == "PRD-006")
    assert "MAPS_API_KEY" in f.message and "SMTP_HOST" in f.message and f.file == ".env.example"


def test_frontend_only_site_skips_backend_checks(tmp_path):
    files = {k: None for k in F.clean_files() if k.startswith("backend/") or k == "docker-compose.yml"}
    got = set(ids(tmp_path, files))
    assert not got & {"PRD-001", "PRD-002", "PRD-003", "PRD-005", "PRD-009"}
