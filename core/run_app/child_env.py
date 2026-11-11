"""Environment for processes that run generated code.

Generated apps (and their build scripts) are untrusted. They are started from
the platform process, whose environment holds the platform's database URL, JWT
keys, provider keys, AWS variables and field-encryption key. Children therefore
get an explicit allowlist, never a copy of os.environ.
"""
from __future__ import annotations

import os
from typing import Dict

# Needed to find executables, a home directory for tool caches, locale and temp files.
# ponytail: HOME is the real home (pip --user packages and the npm cache live there);
# a host process can read those files regardless. Real isolation is a container.
_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR")


def child_env(**own: str) -> Dict[str, str]:
    """Allowlisted parent variables plus the child's own values (port, database, ...)."""
    env = {k: os.environ[k] for k in _PASSTHROUGH if k in os.environ}
    env.update(own)
    return env
