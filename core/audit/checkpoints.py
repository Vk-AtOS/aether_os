"""
AetherOS — signed checkpoints of the audit chains (the external anchor).

A checkpoint states "chain C had N entries and its last entry hash was H at time T",
signed with an Ed25519 key that lives in a file outside the database
(AETHER_LEDGER_SIGNING_KEY). Checkpoints are stored in `audit_checkpoints` and also
appended to a local JSONL file (AETHER_LEDGER_ANCHOR_FILE), and customers can export
them. Anyone holding a checkpoint and the public key can later prove the chain was
not shortened or rewritten behind it: someone with database access alone cannot
forge a checkpoint for a rewritten chain.

This module knows nothing about the chain itself (core/audit/chain.py imports it).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import stat
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import Float, Integer, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from aether_os.core.db import Base

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".aether_os"
CHECKPOINT_TYPE = "aetheros-ledger-checkpoint"


class AuditCheckpoint(Base):
    __tablename__ = "audit_checkpoints"
    __table_args__ = (UniqueConstraint("chain_id", "chain_seq", name="uq_audit_checkpoint_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chain_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    head_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    key_id: Mapped[str] = mapped_column(String(32), nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)  # base64 of 64 bytes


def _reject_mutation(_mapper, _connection, target) -> None:
    raise RuntimeError(f"audit_checkpoints is append-only (checkpoint id={target.id})")


event.listen(AuditCheckpoint, "before_update", _reject_mutation)
event.listen(AuditCheckpoint, "before_delete", _reject_mutation)


def key_path() -> Path:
    return Path(os.environ.get("AETHER_LEDGER_SIGNING_KEY") or _DEFAULT_DIR / "ledger_signing_key.pem")


def anchor_file_path() -> Path:
    return Path(os.environ.get("AETHER_LEDGER_ANCHOR_FILE") or _DEFAULT_DIR / "ledger_anchors.jsonl")


def _create_key(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pem = Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    # O_EXCL: two processes generating at once cannot overwrite each other's key.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    logger.warning("ledger signing key created at %s — back it up; checkpoints cannot be "
                   "verified without its public half", path)


@lru_cache(maxsize=8)
def _load_key(path_text: str, mtime_ns: int) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path_text).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path_text} is not an Ed25519 private key")
    return key


def signing_key(create: bool = False) -> Optional[Ed25519PrivateKey]:
    """The signing key, or None if it does not exist and `create` is False.

    Refuses (raises) a key file that group or others can read: a leaked key lets anyone
    sign checkpoints for a rewritten chain.
    """
    path = key_path()
    if not path.exists():
        if not create:
            return None
        _create_key(path)
    st = path.stat()
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError(f"ledger signing key {path} must be readable by its owner only (chmod 600)")
    return _load_key(str(path), st.st_mtime_ns)


def public_key_pem(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def key_id(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def message(cp: Dict[str, Any]) -> bytes:
    """The exact bytes that are signed: canonical JSON of the checkpoint's statement."""
    body = {"type": CHECKPOINT_TYPE, "v": 1, "chain_id": cp["chain_id"],
            "chain_seq": int(cp["chain_seq"]), "head_hash": cp["head_hash"],
            "created_at": float(cp["created_at"]), "key_id": cp["key_id"]}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(chain_id: str, chain_seq: int, head_hash: str, created_at: float) -> Dict[str, Any]:
    key = signing_key(create=True)
    cp = {"chain_id": chain_id, "chain_seq": int(chain_seq), "head_hash": head_hash,
          "created_at": float(created_at), "key_id": key_id(key)}
    cp["signature"] = base64.b64encode(key.sign(message(cp))).decode()
    return cp


def signature_ok(cp: Dict[str, Any]) -> bool:
    """True only if `cp` was signed by this installation's key. Fails closed: no key,
    another key, a malformed checkpoint or a bad signature are all False."""
    try:
        key = signing_key(create=False)
        if key is None or cp.get("key_id") != key_id(key):
            return False
        key.public_key().verify(base64.b64decode(cp["signature"], validate=True), message(cp))
        return True
    except (InvalidSignature, KeyError, TypeError, ValueError) as e:
        logger.warning("ledger checkpoint failed signature check: %s", e)
        return False


def to_dict(row: AuditCheckpoint) -> Dict[str, Any]:
    return {"chain_id": row.chain_id, "chain_seq": row.chain_seq, "head_hash": row.head_hash,
            "created_at": row.created_at, "key_id": row.key_id, "signature": row.signature}


def append_to_file(cp: Dict[str, Any]) -> None:
    """Append one checkpoint line to the local anchor file (owner-only, fsynced).

    ponytail: the file is append-only by convention; on Linux run `chattr +a` on it
    so even the service user cannot rewrite earlier lines.
    """
    path = anchor_file_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(cp, sort_keys=True, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
