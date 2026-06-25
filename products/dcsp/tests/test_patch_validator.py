"""
Tests for SLM Patch Validator.
"""

from __future__ import annotations
from src.slm.patch_validator import PatchValidator

def test_valid_diff_passes():
    diff = "--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-old\n+new"
    assert PatchValidator.is_valid_diff(diff) is True

def test_invalid_diff_fails():
    assert PatchValidator.is_valid_diff("This is not a diff") is False
    assert PatchValidator.is_valid_diff("") is False

def test_extract_diff_from_prose():
    response = "Sure, here is the fix:\n--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-old\n+new\nHope this helps!"
    diff = PatchValidator.extract_diff(response)
    assert diff.startswith("--- a/file.py")
    assert "@@" in diff

def test_extract_diff_returns_none_if_no_diff():
    assert PatchValidator.extract_diff("Just some text") is None

def test_can_apply_with_matching_context():
    file_content = "import os\ndef main():\n    print('hello')\n"
    patch = "--- a/file.py\n+++ b/file.py\n@@ -2,1 +2,1 @@\n def main():\n-    print('hello')\n+    print('world')"
    # Context line 'def main():' exists in file_content
    assert PatchValidator.can_apply(patch, file_content) is True

def test_can_apply_with_no_context():
    # Patch with only +/- lines (not really valid diff but check can_apply logic)
    patch = "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-a\n+b"
    assert PatchValidator.can_apply(patch, "any content") is True
