"""Every Python code template the generator writes into a customer's app must compile (KAN-276).

agentic_ai.py kept its template in a normal string, so "\\n".join(...) was resolved while the platform module loaded and the
written agent.py had a line break inside a string literal: SyntaxError, run f1f1df48 failed at s03. The multi-tenant template
was mangled the same way by a bulk import-hoisting codemod and nobody noticed for four months, because nothing compiled
the templates. This scans phases/patterns and the p04* phases, so a new template is covered without registering it.
"""
from __future__ import annotations

import importlib
import importlib.util
import pathlib
import pkgutil
import re

import pytest

import aether_os.phases as phases_pkg

# Constants that hold something other than Python source. Anything else long and multi-line in these packages
# must compile.
NOT_PYTHON = re.compile(
    r"(_TSX|_COMPONENT|_JSX|_CSS|_HTML|_YAML|_YML|_JSON|_SQL|_TXT|_MD|_MAKO|_INI|_TOML|_TF|_SH)$"
    r"|DOCKERFILE|ALEMBIC_INI|REQUIREMENTS|ENV_EXAMPLE|PROMPT|EXAMPLE|^_CHECK$|^_SYSTEM"
)
SCANNED = re.compile(r"\.(patterns|p04[a-z_0-9]*)(\.|$)")
FRONTEND_MODULES = re.compile(r"frontend_patterns|\.prompts$")


def _modules():
    for info in pkgutil.walk_packages(phases_pkg.__path__, "aether_os.phases."):
        if SCANNED.search(info.name) and not FRONTEND_MODULES.search(info.name) and ".seed_templates" not in info.name:
            yield importlib.import_module(info.name)


def _seed_template_files():
    """seed_templates/*.py are generated-app source files (`from models import User`): compiled, never imported."""
    spec = importlib.util.find_spec("aether_os.phases.p04a_backend_codegen.seed_templates")
    for f in sorted(pathlib.Path(spec.submodule_search_locations[0]).glob("*.py")):
        yield f"seed_templates/{f.name}", f.read_text()


def _templates():
    """(label, source) for each string constant and each generate_*() template function with defaults."""
    for mod in _modules():
        for name, value in vars(mod).items():
            if name.startswith("__") or NOT_PYTHON.search(name):
                continue
            if isinstance(value, str) and value.count("\n") > 5 and len(value) > 200 and value.lstrip().startswith(
                    ('"""', "'''", "from ", "import ", "#!")):
                yield f"{mod.__name__}.{name}", value
            elif callable(value) and name.startswith("generate_") and getattr(value, "__module__", "") == mod.__name__ \
                    and ".templates" in mod.__name__:
                try:
                    out = value()
                except TypeError:
                    continue            # needs real arguments; covered by its own test
                if isinstance(out, str):
                    yield f"{mod.__name__}.{name}()", out


TEMPLATES = list(_templates()) + list(_seed_template_files())


def test_the_scan_really_finds_the_templates():
    labels = {t[0] for t in TEMPLATES}
    for expected in ("aether_os.phases.patterns.agentic_ai.AGENTIC_AI_CODE",
                     "aether_os.phases.patterns.multi_tenant.MULTI_TENANT_CODE",
                     "aether_os.phases.patterns.websocket.WEBSOCKET_CODE"):
        assert expected in labels
    assert any(label.endswith("generate_ai_client()") for label in labels)


@pytest.mark.parametrize("label,source", TEMPLATES, ids=[t[0].replace("aether_os.phases.", "") for t in TEMPLATES])
def test_template_compiles(label, source):
    compile(source, label, "exec")
