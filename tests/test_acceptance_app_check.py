"""The acceptance click-through check stays importable without a browser and is configured by env, not a baked host."""
import importlib.util
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "scripts" / "acceptance" / "app_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("app_check", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)            # playwright is imported lazily inside main()
    return mod


def test_imports_without_playwright_and_has_no_baked_host():
    mod = _load()
    assert callable(mod.main)
    text = SRC.read_text()
    assert "AETHER_BASE_URL" in text and "sslip.io" not in text
    for check in ("C1 real UI", "C2 sign-in", "C3 pages load", "C4 data from API", "C5 create via form"):
        assert check in text


def test_error_boundary_text_counts_as_a_crash():
    """Run 22: the admin landing page showed the error boundary after sign-in and C2 still passed."""
    mod = _load()
    assert mod.crashed("Something went wrong Show Error Try again")
    assert mod.crashed("Failed to load projects")
    assert not mod.crashed("Dashboard Users 12 Projects 3")
