"""KAN-51: the checkpoint copy goes to a separate place, carries only the public key, and never overwrites."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/scripts/backup_checkpoints.sh"


def _env(tmp_path):
    key = tmp_path / "key.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)], check=True, capture_output=True)
    anchors = tmp_path / "anchors.jsonl"
    anchors.write_text('{"chain_id":"c","chain_seq":1}\n')
    dest = tmp_path / "vault"
    return {**os.environ, "AETHER_LEDGER_ANCHOR_FILE": str(anchors), "AETHER_LEDGER_SIGNING_KEY": str(key),
            "CHECKPOINT_DEST": str(dest)}, dest


def test_copies_checkpoints_and_only_the_public_key(tmp_path):
    env, dest = _env(tmp_path)
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    names = sorted(p.name.split("_")[0] + "_" + p.name.split("_")[1] for p in dest.iterdir())
    assert len(list(dest.iterdir())) == 3
    assert not any("PRIVATE" in p.read_text() for p in dest.glob("*.pem"))
    assert any(p.name.startswith("ledger_anchors_") for p in dest.iterdir()) and names


def test_second_run_adds_new_files_and_never_overwrites(tmp_path):
    env, dest = _env(tmp_path)
    assert subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True).returncode == 0
    first = {p.name: p.read_bytes() for p in dest.iterdir()}
    import time
    time.sleep(1.1)   # the stamp has one-second resolution
    assert subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True).returncode == 0
    after = {p.name: p.read_bytes() for p in dest.iterdir()}
    assert len(after) == 6 and all(after[n] == b for n, b in first.items())


def test_refuses_when_there_is_nothing_to_protect(tmp_path):
    env, dest = _env(tmp_path)
    Path(env["AETHER_LEDGER_ANCHOR_FILE"]).write_text("")
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and not dest.exists()
