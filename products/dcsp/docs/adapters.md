# Custom Adapters Guide

DCSP is built with a plugin architecture, allowing you to easily add support for new CI systems and programming languages.

## 1. CI Adapters

A CI Adapter standardizes incoming webhook payloads from different CI systems into a unified format.

### Implementation Steps

1.  Create a new file in `src/adapters/` (e.g., `my_ci.py`).
2.  Subclass `CIAdapter` from `src/adapters/base.py`.
3.  Implement the `name` property and `parse()` method.

### Example: Minimal CI Adapter

```python
from src.adapters.base import CIAdapter, CIFailureEvent

class MyCustomCIAdapter(CIAdapter):
    @property
    def name(self) -> str:
        return "my_custom_ci"

    def parse(self, payload: dict) -> CIFailureEvent | None:
        if "custom_ci_id" not in payload:
            return None
        
        return CIFailureEvent(
            repo_name=payload["project"],
            branch=payload["ref"],
            commit_sha=payload["sha"],
            log_output=payload.get("logs", ""),
            ci_system=self.name,
            raw_payload=payload
        )
```

### Registration

Register your adapter in `src/adapters/detector.py` by adding it to the `adapters` list in `detect_adapter()`.

---

## 2. Language Adapters

A Language Adapter parses raw build logs to extract structured failure information (error type, file, line number).

### Implementation Steps

1.  Create a new file in `src/lang/` (e.g., `go_adapter.py`).
2.  Subclass `LanguageAdapter` from `src/lang/base.py`.
3.  Implement `language_name`, `file_extensions`, and `parse()`.

### Example: Minimal Language Adapter

```python
import re
from src.lang.base import LanguageAdapter, LanguageFailure

class GoAdapter(LanguageAdapter):
    @property
    def language_name(self) -> str:
        return "go"

    @property
    def file_extensions(self) -> list[str]:
        return [".go"]

    def parse(self, log_output: str) -> LanguageFailure | None:
        if "panic:" not in log_output:
            return None
        
        # Use regex to extract details...
        return LanguageFailure(
            language=self.language_name,
            error_type="Panic",
            error_message="Runtime panic",
            failing_file="main.go",
            failing_function="main",
            line_number=10,
            raw_traceback=log_output
        )
```

### Registration

Register your adapter in `src/lang/detector.py` by adding it to the `adapters` list in `detect_language_adapter()`.

## 3. Testing Your Adapter

Add a new test file in `tests/adapters/` or `tests/lang/` using `pytest`. Follow the pattern of existing tests:
- Mock realistic payloads/logs.
- Verify correct extraction of all fields.
- Ensure `None` is returned for incompatible inputs.
