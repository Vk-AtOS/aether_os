"""KAN-69 SC-07: the CLI config (holds the token) is never readable by others, not even briefly; no deploy script
puts a secret on a curl command line."""
import os
import re
import stat
from pathlib import Path

from aether_os.cli import aetheros

ROOT = Path(__file__).resolve().parents[1]


def test_config_is_created_private(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "home" / ".aetheros"
    monkeypatch.setattr(aetheros, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(aetheros, "CONFIG_FILE", cfg_dir / "config.json")
    old = os.umask(0o022)           # a normal umask would make a plain write_text 0644
    try:
        aetheros._save_cfg({"token": "t", "url": "u"})
        aetheros._save_cfg({"token": "t2", "url": "u"})
    finally:
        os.umask(old)
    assert stat.S_IMODE((cfg_dir / "config.json").stat().st_mode) == 0o600
    assert stat.S_IMODE(cfg_dir.stat().st_mode) == 0o700
    assert aetheros._load_cfg()["token"] == "t2"


def test_no_script_passes_a_secret_in_a_curl_data_argument():
    script = (ROOT / "deploy" / "setup-bedrock.sh").read_text()
    assert not re.search(r'-d\s+"[^"]*(PASS|SECRET|PASSWORD)', script)
