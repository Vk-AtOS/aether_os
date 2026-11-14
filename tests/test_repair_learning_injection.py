"""KAN-110: domain/entity must not break out of the generated validator source."""
import ast

from aether_os.core import repair_learning as rl


def test_domain_cannot_inject_code(tmp_path):
    evil = 'x""" \nimport os; os.environ["PWNED"]="1"\n"""'
    ev = rl.RepairEvent(rl.BugClass.BARE_EXCEPT, evil, evil, "f.py", "fix")
    src = rl.generate_validator(ev)
    tree = ast.parse(src)
    assert not any(isinstance(n, ast.Import) and n.names[0].name == "os"
                   for n in tree.body)
    assert "PWNED" not in src.split('"""')[1] or "import os;" not in src


def test_load_refuses_path_outside_validators_dir(tmp_path, monkeypatch):
    outside = tmp_path / "evil.py"
    outside.write_text("import os\nos.environ['PWNED2']='1'\ndef check(s): return []\n")
    store = tmp_path / "store.json"
    store.write_text('[{"validator_path": "%s"}]' % outside)
    monkeypatch.setattr(rl, "_VALIDATOR_STORE", store)
    import os
    assert rl.load_validators() == []
    assert "PWNED2" not in os.environ
