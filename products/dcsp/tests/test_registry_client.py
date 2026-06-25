from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from src.federation.registry_client import (
    is_registry_enabled,
    submit_pattern,
    pull_patterns,
    submit_repair_result,
    RegistrySubmitResult,
    RegistryPullResult,
    SharedPattern,
    REGISTRY_TIMEOUT
)
from src.federation.anonymizer import (
    AnonymizedPattern
)

# ---------- helpers ----------
def make_pattern(safe=True):
    return AnonymizedPattern(
        original_fingerprint="fp_test",
        anonymized_fingerprint="anon_abc123",
        error_type="AttributeError",
        language="python",
        patch_template="+x = x or {}",
        anonymized_log="error fixed",
        is_safe=safe
    )

# ---------- tests ----------
def test_registry_disabled_by_default():
    """Without env vars, registry is disabled."""
    assert is_registry_enabled() is False

def test_submit_skipped_when_disabled():
    result = submit_pattern(make_pattern())
    assert result.skipped is True
    assert result.success is False
    assert "not enabled" in (
        result.skip_reason or "").lower()

def test_submit_skipped_unsafe_pattern():
    """Unsafe patterns are not submitted."""
    with patch(
        "src.federation.registry_client.is_registry_enabled",
        return_value=True
    ), patch(
        "src.federation.registry_client.is_safe_to_share",
        return_value=False
    ):
        unsafe = make_pattern(safe=False)
        result = submit_pattern(unsafe)
        assert result.skipped is True
        assert "safety" in (
            result.skip_reason or "").lower()

def test_pull_skipped_when_disabled():
    result = pull_patterns()
    assert result.skipped is True
    assert result.success is False

def test_submit_repair_result_skipped():
    result = submit_repair_result(
        fingerprint="fp",
        error_type="TypeError",
        language="python",
        patch_diff="+x = 1",
        log_snippet="TypeError: int expected"
    )
    assert result.skipped is True

def test_submit_pattern_success_mock():
    """Mock successful registry response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": "pat_abc123"}

    with patch(
        "src.federation.registry_client.is_registry_enabled",
        return_value=True
    ), patch(
        "src.federation.registry_client.requests.post",
        return_value=mock_resp
    ):
        result = submit_pattern(make_pattern())
        assert result.success is True
        assert result.pattern_id == "pat_abc123"

def test_submit_pattern_registry_error():
    """Registry 500 returns failure."""
    mock_resp = MagicMock()
    mock_resp.status_code = 500

    with patch(
        "src.federation.registry_client.is_registry_enabled",
        return_value=True
    ), patch(
        "src.federation.registry_client.requests.post",
        return_value=mock_resp
    ):
        result = submit_pattern(make_pattern())
        assert result.success is False
        assert "500" in (result.error or "")

def test_submit_pattern_connection_error():
    """Connection error returns graceful failure."""
    from requests.exceptions import \
        ConnectionError as ConnErr
    with patch(
        "src.federation.registry_client.is_registry_enabled",
        return_value=True
    ), patch(
        "src.federation.registry_client.requests.post",
        side_effect=ConnErr("refused")
    ):
        result = submit_pattern(make_pattern())
        assert result.success is False
        assert result.skipped is False

def test_pull_patterns_success_mock():
    """Mock successful pull from registry."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "patterns": [
            {
                "id": "p1",
                "error_type": "AttributeError",
                "language": "python",
                "patch_template": "+x = x or {}",
                "success_count": 5,
                "confidence": 0.87,
                "source_hash": "abc"
            }
        ]
    }

    with patch(
        "src.federation.registry_client.is_registry_enabled",
        return_value=True
    ), patch(
        "src.federation.registry_client.requests.get",
        return_value=mock_resp
    ):
        result = pull_patterns(
            error_type="AttributeError",
            language="python"
        )
        assert result.success is True
        assert len(result.patterns) == 1
        assert result.patterns[0].pattern_id \
            == "p1"
        assert result.patterns[0].confidence \
            == 0.87

def test_pull_patterns_timeout():
    """Timeout returns graceful failure."""
    from requests.exceptions import Timeout
    with patch(
        "src.federation.registry_client.is_registry_enabled",
        return_value=True
    ), patch(
        "src.federation.registry_client.requests.get",
        side_effect=Timeout()
    ):
        result = pull_patterns()
        assert result.success is False
        assert "unreachable" in \
            (result.error or "").lower()

def test_registry_timeout_default():
    assert isinstance(REGISTRY_TIMEOUT, int)
    assert REGISTRY_TIMEOUT > 0

def test_shared_pattern_dataclass():
    p = SharedPattern(
        pattern_id="p1",
        error_type="TypeError",
        language="python",
        patch_template="+x = 1"
    )
    assert p.success_count == 0
    assert p.confidence == 0.0
