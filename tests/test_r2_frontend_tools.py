"""KAN-177: real tsc/eslint/axe results feed the frontend critic; regex stays as the fallback."""
import json
import subprocess

from aether_os.core.quality import frontend_tools as ft
from aether_os.core.quality.dimension_critic import critique_artifact, critique_directory

CLEAN = "export function A() {\n  return <button>Save</button>\n}\n"


def test_parse_tsc_and_eslint():
    out = "src/a.tsx(3,5): error TS2322: Type 'x' is not assignable.\nsrc/b.ts(1,1): error TS1005: ';' expected.\nnoise"
    assert ft.parse_tsc(out)["src/a.tsx"] == ["L3 TS2322: Type 'x' is not assignable."]
    raw = json.dumps([{"filePath": "/p/src/a.tsx", "messages": [{"ruleId": "jsx-a11y/alt-text", "severity": 2,
                                                                 "message": "img needs alt", "line": 4}]}])
    assert ft.parse_eslint(raw, ft.Path("/p"))["src/a.tsx"][0]["rule"] == "jsx-a11y/alt-text"


def test_frontend_files_have_a_real_overall_score(tmp_path):
    f = tmp_path / "A.tsx"
    f.write_text(CLEAN)
    r = critique_artifact(str(f), root=str(tmp_path))
    assert r.overall_score == 1.0 and r.passed       # was 0.0 for every frontend file: no weights existed


def test_known_violations_from_the_tools_lower_the_score(tmp_path):
    f = tmp_path / "src" / "A.tsx"
    f.parent.mkdir()
    f.write_text(CLEAN)
    base = critique_artifact(str(f), root=str(tmp_path)).overall_score
    tools = ft.FrontendToolReport(
        tsc_ran=True, eslint_ran=True, axe_violations=3,
        tsc={"src/A.tsx": ["L2 TS2322: bad", "L3 TS2304: nope"]},
        eslint={"src/A.tsx": [{"rule": "jsx-a11y/alt-text", "severity": 2, "message": "m", "line": 1}]},
    )
    worse = critique_artifact(str(f), tools=tools, root=str(tmp_path))
    assert worse.overall_score < base
    text = " ".join(x for d in worse.dimension_scores for x in d.findings)
    assert "tsc: 2 error(s)" in text and "jsx-a11y" in text and "axe-core reported 3" in text
    assert critique_directory(str(tmp_path), tools=tools)[0].overall_score == worse.overall_score


def test_collect_reports_tools_that_did_not_run(tmp_path, monkeypatch):
    assert "node_modules missing" in ft.collect(str(tmp_path)).notes[0]
    (tmp_path / "node_modules").mkdir()

    def fake(argv, **kw):
        if "tsc" in argv:
            return subprocess.CompletedProcess(argv, 2, "src/a.tsx(1,1): error TS2322: x", "")
        return subprocess.CompletedProcess(argv, 2, "", "no config")   # eslint could not run
    monkeypatch.setattr(ft, "run_sync", fake)
    rep = ft.collect(str(tmp_path))
    assert rep.tsc_ran and rep.tsc == {"src/a.tsx": ["L1 TS2322: x"]}
    assert not rep.eslint_ran and any("eslint did not run" in n for n in rep.notes)

    def unavailable(argv, **kw):
        raise ft.SandboxUnavailable("no docker")
    monkeypatch.setattr(ft, "run_sync", unavailable)
    rep = ft.collect(str(tmp_path))
    assert not rep.tsc_ran and not rep.eslint_ran


def test_the_scorer_itself_uses_the_tool_results(tmp_path):
    """KAN-188: the scorers (not only critique_artifact) deduct real tsc/eslint/axe findings."""
    from aether_os.core.quality import dimension_scorer_frontend as sf
    tools = ft.FrontendToolReport(
        tsc_ran=True, eslint_ran=True, axe_violations=2,
        tsc={"src/A.tsx": ["L2 TS2322: bad"]},
        eslint={"src/A.tsx": [{"rule": "jsx-a11y/alt-text", "severity": 2, "message": "m", "line": 1},
                              {"rule": "no-unused-vars", "severity": 2, "message": "m", "line": 1}]},
    )
    path = str(tmp_path / "src" / "A.tsx")
    types = sf.score_typescript_types(CLEAN, path, tools)
    assert types.score == 0.85 and types.findings == ["tsc: 1 error(s), first: L2 TS2322: bad"]
    a11y = sf.score_frontend_a11y(CLEAN, path, tools)
    assert a11y.score < 1.0 and any("jsx-a11y" in f for f in a11y.findings) and any("axe-core" in f for f in a11y.findings)
    assert sf.score_frontend_correctness(CLEAN, path, tools).score == 0.95
    # another file of the same project, and a call without a report, keep the pattern-matching score
    assert sf.score_typescript_types(CLEAN, str(tmp_path / "src" / "B.tsx"), tools).score == 1.0
    assert sf.score_typescript_types(CLEAN, path).score == 1.0
