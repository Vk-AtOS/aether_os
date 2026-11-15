"""KAN-101: checkpoints signed by a rotated/lost key still verify from its retired public key."""
import os

from cryptography.hazmat.primitives import serialization

from aether_os.core.audit import checkpoints
from aether_os.tests.ledger_helpers import anchor_env  # noqa: F401


def _retire_current(tmp):
    key = checkpoints.signing_key(create=True)
    d = checkpoints.retired_keys_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{checkpoints.key_id(key)}.pem").write_text(checkpoints.public_key_pem(key))
    return key


def test_rotated_key_checkpoints_still_verify_and_unknown_keys_do_not(anchor_env):
    cp = checkpoints.sign("org-a", 3, "ab" * 32, 1.0)
    old = _retire_current(anchor_env)
    os.remove(checkpoints.key_path())            # rotated: a new key is generated on next use
    new = checkpoints.signing_key(create=True)
    assert checkpoints.key_id(new) != checkpoints.key_id(old)
    assert checkpoints.signature_ok(cp)          # old key's public half is in retired_keys/
    assert not checkpoints.signature_ok({**cp, "head_hash": "cd" * 32})
    (checkpoints.retired_keys_dir() / f"{cp['key_id']}.pem").unlink()
    assert not checkpoints.signature_ok(cp)      # nothing known about that key: fails closed


def test_a_retired_file_must_hash_to_the_claimed_key_id(anchor_env):
    cp = checkpoints.sign("org-a", 3, "ab" * 32, 1.0)
    os.remove(checkpoints.key_path())
    other = checkpoints.signing_key(create=True)
    d = checkpoints.retired_keys_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cp['key_id']}.pem").write_text(checkpoints.public_key_pem(other))   # wrong key under that name
    assert not checkpoints.signature_ok(cp)
