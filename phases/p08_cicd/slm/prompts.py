"""
SLM Prompt Templates for the AetherOS CI/CD phase.
Provides specialized system and user prompts based on error types.
"""

from __future__ import annotations

class PromptTemplates:
    BASE_SYSTEM = """You are an expert software engineer specializing in debugging and fixing production code. You analyze CI/CD failure logs and generate minimal, targeted patches.
Rules:
- Generate only the minimal change needed
- Preserve existing code style and formatting
- Never change unrelated code
- Output ONLY a unified diff patch, nothing else
- Start with: --- a/filename\n+++ b/filename"""

    TEMPLATES = {
        "ConnectionTimeout": {
            "system": BASE_SYSTEM,
            "strategy": "Add retry logic with exponential backoff using tenacity or manual retry loop. Add timeout parameter. Catch requests.exceptions.Timeout and requests.exceptions.ConnectionError.",
            "example_fix": "Wrap the request in a for loop with max_retries, catch the exception, sleep with backoff, re-raise on final attempt."
        },
        "NullPointerException": {
            "system": BASE_SYSTEM,
            "strategy": "Add None/null guard checks before accessing nested attributes. Use .get() for dict access. Add optional chaining pattern.",
            "example_fix": "Add 'if x is None: return None' or use dict.get() with defaults before accessing nested keys."
        },
        "AttributeError": {
            "system": BASE_SYSTEM,
            "strategy": "Same as NullPointer — add hasattr() checks or None guards before attribute access.",
            "example_fix": "Check if object is not None and hasattr before access."
        },
        "ImportError": {
            "system": BASE_SYSTEM,
            "strategy": "Wrap imports in try/except ImportError. Add conditional imports. Check if optional dependencies exist before using them.",
            "example_fix": "try: import x except ImportError: x = None and check before use."
        },
        "ModuleNotFoundError": {
            "system": BASE_SYSTEM,
            "strategy": "Same as ImportError.",
            "example_fix": "Add try/except around the failing import."
        },
        "MemoryError": {
            "system": BASE_SYSTEM,
            "strategy": "Replace full-file reads with chunked processing. Use generators instead of lists where possible. Add streaming reads.",
            "example_fix": "Replace f.read() with chunked reading using f.read(chunk_size) in a loop."
        },
        "AuthenticationError": {
            "system": BASE_SYSTEM,
            "strategy": "Replace hardcoded tokens with environment variable reads. Add token refresh logic. Add proper 401 handling with retry after refresh.",
            "example_fix": "Use os.environ.get() for token. Add refresh_token() call on 401 response before retry."
        },
    }

    @classmethod
    def get_template(cls, error_type: str) -> dict:
        """Get template for error type, with fallback."""
        for key in cls.TEMPLATES:
            if key.lower() in error_type.lower():
                return cls.TEMPLATES[key]
        return {
            "system": cls.BASE_SYSTEM,
            "strategy": "Analyze the error and apply the minimal fix.",
            "example_fix": "Fix the root cause shown in the traceback."
        }

    @classmethod
    def build_prompt(cls, error_type: str, 
                     log_content: str, 
                     file_content: str, 
                     filename: str) -> tuple[str, str]:
        """Build system + user prompt for SLM."""
        template = cls.get_template(error_type)
        system = template["system"]
        
        user = f"""CI Failure Log:
{log_content[:2000]}

File to fix: {filename}
Current content:
```python
{file_content}
```

Strategy: {template['strategy']}
Example approach: {template['example_fix']}

Generate the unified diff patch:"""
        
        return system, user
