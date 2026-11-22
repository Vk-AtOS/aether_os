"""Checks on a built preview frontend before it is served."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

_REF = re.compile(r"""(?:src|href)=["'](/[^"'#?]*)""")


def assets_outside_base(index_html: Path, base: str) -> List[str]:
    """Root-relative script/style/icon references in index.html that do not start with `base`.

    The preview serves the app under `base` (/app-preview/); a bundle built for "/" references /assets/... which 404s,
    and the page is blank (production run 20, 22 Nov 2026). External URLs and relative paths are fine.
    """
    try:
        html = index_html.read_text(errors="replace")
    except OSError as exc:
        logger.warning("run_app: cannot read %s: %s", index_html, exc)
        return []
    prefix = "/" + base.strip("/") + "/"
    return [ref for ref in _REF.findall(html) if not ref.startswith("//") and not ref.startswith(prefix)]
