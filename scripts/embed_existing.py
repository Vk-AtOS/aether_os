"""
Retroactively embed artifacts for completed runs that have no embeddings yet.

Usage:
    python3 scripts/embed_existing.py
"""
import asyncio
import sqlite3
import sys
import os
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(_root / ".env")
except ImportError:
    pass

_HOME_DB = Path.home() / ".aether_os" / "aether_os.db"
_PROJECTS_DIR = Path.home() / ".aether_os" / "projects"
_EMBED_EXTENSIONS = {".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".sql"}


def _get_completed_runs_without_embeddings():
    """Return (run_id, org_id) pairs for completed runs with no embeddings."""
    if not _HOME_DB.exists():
        print(f"Database not found: {_HOME_DB}")
        return []
    with sqlite3.connect(str(_HOME_DB)) as conn:
        embedded = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT run_id FROM artifact_embeddings"
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT id, org_id FROM runs WHERE status = 'completed'"
        ).fetchall()
    return [(run_id, org_id) for run_id, org_id in rows if run_id not in embedded]


async def embed_run(run_id: str) -> int:
    """Embed all artifacts for a single run. Returns number of files embedded."""
    from aether_os.core.artifact_store import get_artifact_store
    store = get_artifact_store()
    store.init_db()

    project_dir = _PROJECTS_DIR / run_id
    if not project_dir.exists():
        return 0

    count = 0
    for f in project_dir.rglob("*"):
        if f.is_file() and f.suffix in _EMBED_EXTENSIONS:
            try:
                content = f.read_text(errors="replace")
                rel = str(f.relative_to(project_dir))
                await store.store_artifact(run_id, rel, content)
                count += 1
                if count >= 50:
                    break
            except Exception as exc:
                print(f"  [warn] {f.name}: {exc}")
    return count


async def main() -> None:
    pending = _get_completed_runs_without_embeddings()
    if not pending:
        print("No completed runs without embeddings found.")
        return

    print(f"Found {len(pending)} run(s) to embed.")
    total = 0
    for run_id, org_id in pending:
        print(f"  Embedding run {run_id} (org={org_id}) ...", end=" ", flush=True)
        n = await embed_run(run_id)
        print(f"{n} file(s)")
        total += n

    print(f"\nDone. Embedded {total} artifact(s) across {len(pending)} run(s).")


if __name__ == "__main__":
    os.environ.setdefault("AETHER_SECRET_KEY", "embed-script-placeholder")
    asyncio.run(main())
