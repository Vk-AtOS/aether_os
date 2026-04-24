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
    """
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

    # 5. Join, lowercase, and hash
    final_text = normalized_text.lower()
    hash_obj = hashlib.sha256(final_text.encode("utf-8"))
    return hash_obj.hexdigest()[:16]
