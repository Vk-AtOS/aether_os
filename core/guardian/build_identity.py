"""
Build identity for the Guardian file-integrity baseline.

The integrity baseline must belong to the code that was deployed, not to the first boot of a Redis volume: a Redis volume
outlives image rebuilds, so a first-boot-only baseline raised a critical file_tamper alert after every legitimate deploy.

At image build time the Dockerfile calls write_manifest(), which writes a manifest of the critical files' SHA-256
hashes next to the code (root-owned, read-only to the app user). At runtime the build id is, in order:
  1. AETHER_BUILD_ID from the environment (baked into the image by the Dockerfile ARG, e.g. the git commit) — it lives in
     the image config, so nothing running inside the container can change it;
  2. otherwise a digest of the manifest, so every build whose critical files differ gets its own id automatically;
  3. otherwise None (bare-metal installs without a manifest): the legacy first-boot baseline is used.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
# Paths relative to the package root; the threat detector hashes exactly these.
CRITICAL_REL_PATHS: List[str] = [
    "gateway/api.py",
    "gateway/auth.py",
    "core/models.py",
    "core/db.py",
    "alembic/env.py",
]
MANIFEST_NAME = ".guardian_build_manifest.json"
MANIFEST_PATH = PACKAGE_ROOT / MANIFEST_NAME
BUILD_ID_ENV = "AETHER_BUILD_ID"


def sha256_file(path: Path) -> Optional[str]:
    """Return SHA-256 hex digest of a file, or None if unreadable."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as exc:
        logger.warning("Guardian: cannot hash %s: %s", path, exc)
        return None


def compute_manifest(root: Path = PACKAGE_ROOT, rel_paths: Optional[List[str]] = None) -> Dict[str, object]:
    """Hash the critical files under root. Missing files are left out (the detector reports them as missing)."""
    files: Dict[str, str] = {}
    for rel in rel_paths or CRITICAL_REL_PATHS:
        path = root / rel
        if path.exists():
            digest = sha256_file(path)
            if digest:
                files[rel] = digest
    version_file = root / "VERSION"
    version = version_file.read_text().strip() if version_file.exists() else ""
    return {"version": version, "files": files}


def write_manifest(path: Path = MANIFEST_PATH, root: Path = PACKAGE_ROOT) -> Dict[str, object]:
    manifest = compute_manifest(root)
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    return manifest


def load_manifest(path: Path = MANIFEST_PATH) -> Optional[Dict[str, str]]:
    """Return {rel_path: sha256} from the build manifest, or None when there is none or it is unreadable."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        files = data.get("files")
        if not isinstance(files, dict):
            raise ValueError("manifest has no 'files' mapping")
        return {str(k): str(v) for k, v in files.items()}
    except Exception as exc:
        logger.warning("Guardian: build manifest %s unreadable, ignoring it: %s", path, exc)
        return None


def resolve_build_identity(manifest_path: Path = MANIFEST_PATH) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """Return (build_id, manifest_files). build_id is None when the deploy carries no build identity at all."""
    manifest = load_manifest(manifest_path)
    env_id = os.environ.get(BUILD_ID_ENV, "").strip()
    if env_id:
        return f"env:{env_id}", manifest
    if manifest:
        canonical = json.dumps(manifest, sort_keys=True).encode()
        return f"manifest:{hashlib.sha256(canonical).hexdigest()[:16]}", manifest
    return None, None

