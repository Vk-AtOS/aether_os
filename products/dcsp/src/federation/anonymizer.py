from __future__ import annotations
import re
import hashlib
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Regex patterns for sensitive data
PATTERNS = {
    "ip_address": re.compile(
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    "email": re.compile(
        r'\b[A-Za-z0-9._%+-]+'
        r'@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    "api_key": re.compile(
        r'\b[A-Za-z0-9_\-]{32,64}\b'),
    "jwt_token": re.compile(
        r'eyJ[A-Za-z0-9_\-]+\.'
        r'[A-Za-z0-9_\-]+\.'
        r'[A-Za-z0-9_\-]+'),
    "secret_key": re.compile(
        r'(?i)(?:secret|password|token|key)'
        r'\s*[=:]\s*["\']?'
        r'([A-Za-z0-9_\-!@#$%^&*]{8,})'
        r'["\']?'),
    "url": re.compile(
        r'https?://[^\s<>"\']+'),
    "file_path": re.compile(
        r'(?:/[a-zA-Z0-9_.\-]+){2,}'),
}

REPLACEMENT_TOKENS = {
    "ip_address":  "<IP_ADDRESS>",
    "email":       "<EMAIL>",
    "api_key":     "<API_KEY>",
    "jwt_token":   "<JWT_TOKEN>",
    "secret_key":  "<SECRET>",
    "file_path":   "<FILE_PATH>",
    "url":         "<URL>",
    "repo_name":   "<REPO>",
}

@dataclass
class AnonymizedPattern:
    original_fingerprint: str
    anonymized_fingerprint: str
    error_type: str
    language: str
    patch_template: str
    anonymized_log: str
    replacements_made: int = 0
    is_safe: bool = True

def anonymize_text(
    text: str,
    extra_terms: list[str] | None = None
) -> tuple[str, int]:
    """
    Anonymize sensitive data in text.
    Returns (anonymized_text, replacements_count)
    """
    if not text:
        return text, 0
    
    result = text
    count = 0
    
    # Apply each pattern
    for name, pattern in PATTERNS.items():
        token = REPLACEMENT_TOKENS.get(
            name, f"<{name.upper()}>")
        new_result, n = re.subn(
            pattern, token, result)
        result = new_result
        count += n
    
    # Replace extra terms (e.g. repo names)
    if extra_terms:
        for term in extra_terms:
            if term and term in result:
                result = result.replace(
                    term,
                    REPLACEMENT_TOKENS[
                        "repo_name"])
                count += 1
    
    return result, count

def anonymize_repo_name(
    repo_name: str
) -> str:
    """
    Hash repo name for federation sharing.
    Returns consistent anonymized ID.
    """
    return "repo_" + hashlib.sha256(
        repo_name.encode()
    ).hexdigest()[:12]

def anonymize_patch(
    patch_diff: str,
    repo_name: Optional[str] = None
) -> str:
    """
    Anonymize a patch diff for sharing.
    Removes file paths, secrets etc.
    """
    if not patch_diff:
        return patch_diff
    
    extra = [repo_name] \
        if repo_name else None
    anonymized, _ = anonymize_text(
        patch_diff, extra)
    return anonymized

def create_anonymized_pattern(
    fingerprint: str,
    error_type: str,
    language: str,
    patch_diff: str,
    log_snippet: str,
    repo_name: Optional[str] = None
) -> AnonymizedPattern:
    """
    Create a fully anonymized pattern for
    federation sharing.
    """
    extra_terms = [repo_name] \
        if repo_name else []
    
    anon_log, log_replacements = \
        anonymize_text(log_snippet, extra_terms)
    anon_patch, patch_replacements = \
        anonymize_text(patch_diff, extra_terms)
    
    total_replacements = \
        log_replacements + patch_replacements
    
    # Anonymize the fingerprint itself
    anon_fingerprint = \
        "anon_" + hashlib.sha256(
            fingerprint.encode()
        ).hexdigest()[:16]
    
    return AnonymizedPattern(
        original_fingerprint=fingerprint,
        anonymized_fingerprint=anon_fingerprint,
        error_type=error_type,
        language=language,
        patch_template=anon_patch,
        anonymized_log=anon_log,
        replacements_made=total_replacements,
        is_safe=True
    )

def is_safe_to_share(
    pattern: AnonymizedPattern
) -> bool:
    """
    Final safety check before federation.
    Ensures no residual sensitive data.
    """
    sensitive_indicators = [
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        r'[A-Za-z0-9._%+-]+@'
            r'[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}',
        r'eyJ[A-Za-z0-9_\-]+\.'
            r'[A-Za-z0-9_\-]+',
    ]
    
    combined = (
        pattern.patch_template + " " +
        pattern.anonymized_log
    )
    
    for pat in sensitive_indicators:
        if re.search(pat, combined):
            pattern.is_safe = False
            logger.warning(
                f"Pattern {pattern.anonymized_fingerprint}"
                f" failed safety check")
            return False
    
    return True
