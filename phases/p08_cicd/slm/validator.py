"""
SLM response validation and extraction for the AetherOS CI/CD phase.
"""

from __future__ import annotations

class PatchValidator:
    @staticmethod
    def is_valid_diff(patch_text: str) -> bool:
        """Check if text is a valid unified diff."""
        if not patch_text:
            return False
        required = ["---", "+++", "@@"]
        return all(marker in patch_text for marker in required)

    @staticmethod
    def extract_diff(response_text: str) -> str | None:
        """
        Extract diff from SLM response that may contain prose before/after the diff.
        """
        if not response_text:
            return None
            
        lines = response_text.split('\n')
        diff_start = None
        for i, line in enumerate(lines):
            if line.startswith('--- ') or line.startswith('diff --git'):
                diff_start = i
                break
        
        if diff_start is None:
            return None
            
        # Optional: try to find where it ends if there is prose after
        # For now, just return till the end or until a line doesn't look like diff content
        # but unified diff is tricky. Simplest is till end.
        return '\n'.join(lines[diff_start:])

    @staticmethod
    def can_apply(patch_text: str, file_content: str) -> bool:
        """
        Check if patch context lines exist in the file (basic applicability check).
        """
        if not patch_text or not file_content:
            return False
            
        context_lines = []
        for line in patch_text.split('\n'):
            if line.startswith(' ') and len(line.strip()) > 3:
                context_lines.append(line[1:].strip())
        
        if not context_lines:
            return True  # No context to check
            
        # Check first 5 non-empty context lines
        test_context = context_lines[:5]
        matches = sum(1 for ctx in test_context if ctx in file_content)
        
        return matches >= min(3, len(test_context))
