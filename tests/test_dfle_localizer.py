"""DFLE: the failure site is where the exception was raised; frames resolve into the call graph."""
from aether_os.phases.p08_cicd.dfle.call_graph import CallGraph
from aether_os.phases.p08_cicd.dfle.localizer import localize
from aether_os.phases.p08_cicd.dfle.log_parser import parse_log

LOG = '''Traceback (most recent call last):
  File "/home/runner/work/app/tests/test_a.py", line 10, in test_a
    run()
  File "/home/runner/work/app/src/pay.py", line 42, in charge
    return 1 / 0
ZeroDivisionError: division by zero
'''


def test_failure_site_is_the_raise_site_not_the_test_runner():
    trace = parse_log(LOG).primary_trace
    assert trace.top_frame.function == "charge"
    assert trace.failure_site == "/home/runner/work/app/src/pay.py:42:charge"


def test_absolute_ci_paths_and_call_site_lines_match_the_call_graph():
    # graph ids: repo-relative path, def line (40), name
    cg = CallGraph(callers={"src/pay.py:40:charge": ["tests/test_a.py:8:test_a"]},
                   callees={"src/pay.py:40:charge": [], "tests/test_a.py:8:test_a": ["charge"]})
    cands = localize(parse_log(LOG), cg)
    by_fn = {c.target_function: c for c in cands}
    assert by_fn["charge"].dependency_radius >= 1  # resolved to the node, so its callers were found
    assert cands[0].target_function == "charge"
