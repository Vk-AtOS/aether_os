from __future__ import annotations
import os
import pytest

ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)))

def test_readme_exists():
    assert os.path.isfile(
        os.path.join(ROOT, "README.md"))

def test_readme_substantial():
    with open(os.path.join(
            ROOT, "README.md")) as f:
        content = f.read()
    assert len(content) > 3000
    assert "DCSP" in content
    assert "Quick Start" in content or \
        "quickstart" in content.lower()

def test_readme_has_features():
    with open(os.path.join(
            ROOT, "README.md")) as f:
        content = f.read()
    assert "webhook" in content.lower() or \
        "Webhook" in content
    assert "dashboard" in content.lower()
    assert "docker" in content.lower()

def test_readme_has_env_vars():
    with open(os.path.join(
            ROOT, "README.md")) as f:
        content = f.read()
    assert "DATABASE_URL" in content
    assert "WEBHOOK_SECRET" in content or \
        "webhook_secret" in content.lower()

def test_quickstart_exists():
    assert os.path.isfile(os.path.join(
        ROOT, "docs", "QUICKSTART.md"))

def test_quickstart_substantial():
    with open(os.path.join(
            ROOT, "docs",
            "QUICKSTART.md")) as f:
        content = f.read()
    assert len(content) > 500
    assert "curl" in content or \
        "pip" in content

def test_webhook_integration_exists():
    assert os.path.isfile(os.path.join(
        ROOT, "docs",
        "WEBHOOK_INTEGRATION.md"))

def test_webhook_integration_has_examples():
    with open(os.path.join(
            ROOT, "docs",
            "WEBHOOK_INTEGRATION.md")) as f:
        content = f.read()
    assert "GitHub" in content or \
        "github" in content.lower()
    assert "curl" in content

def test_api_reference_exists():
    assert os.path.isfile(os.path.join(
        ROOT, "docs", "API_REFERENCE.md"))

def test_api_reference_has_endpoints():
    with open(os.path.join(
            ROOT, "docs",
            "API_REFERENCE.md")) as f:
        content = f.read()
    assert "/webhook/ci" in content
    assert "/health" in content
    assert "GET" in content
    assert "POST" in content
