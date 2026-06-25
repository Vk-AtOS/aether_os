from __future__ import annotations
import pytest
from src.federation.anonymizer import (
    anonymize_text,
    anonymize_repo_name,
    anonymize_patch,
    create_anonymized_pattern,
    is_safe_to_share,
    AnonymizedPattern
)

def test_anonymize_ip_address():
    text = "Connection to 192.168.1.100 failed"
    result, count = anonymize_text(text)
    assert "192.168.1.100" not in result
    assert "<IP_ADDRESS>" in result
    assert count >= 1

def test_anonymize_email():
    text = "Sent by user@example.com today"
    result, count = anonymize_text(text)
    assert "user@example.com" not in result
    assert "<EMAIL>" in result

def test_anonymize_url():
    text = "Failed at https://api.example.com/v1/data"
    result, count = anonymize_text(text)
    assert "https://api.example.com" not in result
    assert "<URL>" in result

def test_anonymize_file_path():
    text = "Error in /home/user/project/app.py"
    result, count = anonymize_text(text)
    assert "/home/user/project/app.py" \
        not in result

def test_anonymize_extra_terms():
    text = "acme/billing-service threw error"
    result, count = anonymize_text(
        text, ["acme/billing-service"])
    assert "acme/billing-service" not in result
    assert "<REPO>" in result
    assert count >= 1

def test_anonymize_empty_text():
    result, count = anonymize_text("")
    assert result == ""
    assert count == 0

def test_anonymize_none_text():
    result, count = anonymize_text(None)
    assert result is None
    assert count == 0

def test_anonymize_repo_name_consistent():
    """Same repo always hashes the same."""
    r1 = anonymize_repo_name("acme/billing")
    r2 = anonymize_repo_name("acme/billing")
    assert r1 == r2
    assert r1.startswith("repo_")

def test_anonymize_repo_name_different():
    """Different repos hash differently."""
    r1 = anonymize_repo_name("acme/billing")
    r2 = anonymize_repo_name("acme/payments")
    assert r1 != r2

def test_anonymize_patch():
    patch = (
        "+conn = connect('192.168.1.1')\n"
        "-conn = connect('10.0.0.1')\n"
    )
    result = anonymize_patch(
        patch, "acme/service")
    assert "192.168.1.1" not in result
    assert "10.0.0.1" not in result

def test_create_anonymized_pattern():
    pattern = create_anonymized_pattern(
        fingerprint="AttributeError:NoneType",
        error_type="AttributeError",
        language="python",
        patch_diff="+x = x or {}\n-x = x\n",
        log_snippet=(
            "Error at 192.168.1.1: "
            "AttributeError"),
        repo_name="acme/billing"
    )
    assert pattern.error_type == "AttributeError"
    assert pattern.language == "python"
    assert pattern.anonymized_fingerprint\
        .startswith("anon_")
    assert pattern.original_fingerprint == \
        "AttributeError:NoneType"
    assert "192.168.1.1" not in \
        pattern.anonymized_log

def test_anonymized_pattern_replacements():
    """Counts replacements correctly."""
    pattern = create_anonymized_pattern(
        fingerprint="fp",
        error_type="TypeError",
        language="python",
        patch_diff="diff",
        log_snippet=(
            "Error from 10.0.0.1 "
            "user@test.com"),
        repo_name=None
    )
    assert pattern.replacements_made >= 2

def test_is_safe_to_share_clean():
    pattern = AnonymizedPattern(
        original_fingerprint="fp",
        anonymized_fingerprint="anon_abc",
        error_type="TypeError",
        language="python",
        patch_template="+x = x or {}",
        anonymized_log="AttributeError fixed"
    )
    assert is_safe_to_share(pattern) is True

def test_is_safe_to_share_with_ip():
    """Pattern with IP fails safety check."""
    pattern = AnonymizedPattern(
        original_fingerprint="fp",
        anonymized_fingerprint="anon_abc",
        error_type="TypeError",
        language="python",
        patch_template="+conn = '192.168.1.1'",
        anonymized_log="error"
    )
    assert is_safe_to_share(pattern) is False
    assert pattern.is_safe is False
