"""KAN-122: p08_cicd was moved from a `src.` layout; no module may still import from it (even under TYPE_CHECKING)."""
import ast
import typing
from pathlib import Path

from aether_os.phases.p08_cicd.dfle.call_graph import CallGraph
from aether_os.phases.p08_cicd.dsee import impact

P08 = Path(impact.__file__).resolve().parents[1]


def test_no_p08_module_imports_the_old_src_package():
    stale = []
    for path in P08.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [node.module or ""] if isinstance(node, ast.ImportFrom) else \
                    [a.name for a in node.names] if isinstance(node, ast.Import) else []
            stale += [f"{path.relative_to(P08)}:{node.lineno}" for n in names if n == "src" or n.startswith("src.")]
    assert not stale, stale


def test_simulate_impact_annotations_resolve():
    assert typing.get_type_hints(impact.simulate_impact)["call_graph"] is CallGraph


def test_verifier_annotations_resolve():
    from aether_os.phases.p08_cicd.dsee import verifier
    assert typing.get_type_hints(verifier.verify_stability)


def test_predictor_module_can_be_imported():
    # it instantiated a class at import time whose constructor imported src.database
    from aether_os.phases.p08_cicd.intelligence import predictor
    assert predictor.PREDICTOR.known_error_types == []


def test_context_builder_returns_the_failing_function(tmp_path):
    # build() imported src.repo.indexer on every call, so it could only raise ModuleNotFoundError
    from aether_os.phases.p08_cicd.dfle.ast_index import build_index
    from aether_os.phases.p08_cicd.dfle.log_parser import parse_log
    from aether_os.phases.p08_cicd.slm import ContextBuilder
    (tmp_path / "app.py").write_text("def boom():\n    return 1 / 0\n")
    log = ('Traceback (most recent call last):\n  File "app.py", line 2, in boom\n    return 1 / 0\n'
           "ZeroDivisionError: division by zero\n")
    out = ContextBuilder(tmp_path).build(parse_log(log), build_index(tmp_path))
    assert "return 1 / 0" in out and "Function: boom" in out
