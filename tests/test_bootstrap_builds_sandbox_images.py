"""The single-host bootstrap builds both sandbox images; the browser one builds FROM the base one, so order matters."""
from pathlib import Path

BOOT = Path(__file__).resolve().parents[1] / "deploy/terraform/aws/environments/prod-single/bootstrap.sh"


def test_bootstrap_builds_base_then_browser_sandbox_image():
    text = BOOT.read_text()
    base = text.find("-t aether-sandbox:1 -f core/sandbox/Dockerfile ")
    browser = text.find("-t aether-sandbox-browser:1 -f core/sandbox/Dockerfile.browser")
    assert base != -1 and browser != -1 and base < browser
