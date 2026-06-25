"""
Tests for OllamaClient.
"""

from __future__ import annotations

import pytest
import requests
from unittest.mock import MagicMock, patch
from src.slm.ollama_client import OllamaClient


def test_ollama_unavailable_returns_none():
    """Test that connection errors return None."""
    client = OllamaClient()
    # Mock is_available to return True first, then post fails
    with patch.object(OllamaClient, "is_available", return_value=True), \
         patch("requests.post", side_effect=requests.exceptions.ConnectionError):
        patch_res = client.generate_patch("system", "user")
        assert patch_res is None


def test_generate_patch_returns_string():
    """Test successful patch generation."""
    client = OllamaClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    # Must be valid diff for validate_diff to pass
    valid_diff = "--- a/file.py\n+++ b/file.py\n@@ -1,1 +1,1 @@\n-old\n+new"
    mock_response.json.return_value = {"response": valid_diff}
    
    with patch.object(OllamaClient, "is_available", return_value=True), \
         patch("requests.post", return_value=mock_response):
        patch_res = client.generate_patch("system", "user")
        assert patch_res == valid_diff

def test_ollama_is_available():
    client = OllamaClient()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("requests.get", return_value=mock_resp):
        assert client.is_available() is True

def test_ollama_is_not_available():
    client = OllamaClient()
    with patch("requests.get", side_effect=Exception("Offline")):
        assert client.is_available() is False
