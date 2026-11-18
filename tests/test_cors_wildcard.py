"""KAN-69 F21: CORS_ORIGINS=* with credentials enabled was accepted at start-up."""
import pytest

from aether_os.gateway.api_utils import _get_cors_origins


@pytest.mark.parametrize("raw", ["*", "https://app.example.com, *"])
def test_wildcard_origin_refuses_to_start(monkeypatch, raw):
    monkeypatch.setenv("CORS_ORIGINS", raw)
    with pytest.raises(RuntimeError, match="explicit origins"):
        _get_cors_origins()
