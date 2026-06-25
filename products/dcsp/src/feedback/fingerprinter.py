"""
Error fingerprinting for DCSP.
Normalizes log content to extract stable signatures for error patterns.
"""

from __future__ import annotations

import hashlib
import re

def fingerprint(log_content: str) -> str:
    """
    Generates a stable 16-character hex fingerprint from CI log content.
    Includes the target file basename so errors in different files get distinct
    fingerprints and don't accidentally reuse each other's cached patches.
    """
    # 0. Extract the first .py file mentioned — keep it as a disambiguator
    #    before we strip all paths in step 4.
    _file_anchor = ""
    _file_match = re.search(r'[\w./\\-]+\.py', log_content)
    if _file_match:
        import os as _os
        _file_anchor = _os.path.basename(_file_match.group(0))

    # 1. Extract lines containing key error indicators
    keywords = ["error", "exception", "traceback", "failed", "fatal"]
    relevant_lines = []
    for line in log_content.splitlines():
        if any(kw in line.lower() for kw in keywords):
            relevant_lines.append(line.strip())

    normalized_text = "\n".join(relevant_lines)

    # 2. Strip memory addresses
    normalized_text = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", normalized_text)

    # 3. Strip line numbers
    normalized_text = re.sub(r"line \d+", "line N", normalized_text)

    # 4. Strip file paths (quoted or with line numbers)
    # Replaces "/path/to/file.py" or 'file.py:123' with FILE
    normalized_text = re.sub(r"(['\"])(?:(?!\1).)*\1", "FILE", normalized_text)
    normalized_text = re.sub(r"[\w\./\\-]+\.py:\d+", "FILE", normalized_text)

    # 5. Join, lowercase, and hash — include file anchor so same error type
    #    in different files does not collide in repair memory.
    final_text = (_file_anchor + "|" + normalized_text).lower()
    hash_obj = hashlib.sha256(final_text.encode("utf-8"))
    return hash_obj.hexdigest()[:16]
