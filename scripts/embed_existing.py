"""
Retroactively embed artifacts for completed runs that have no embeddings yet.

Usage:
    python3 scripts/embed_existing.py
"""
import asyncio
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

_PROJECTS_DIR = Path.home() / ".aether_os" / "projects"
_EMBED_EXTENSIONS = {".py", ".js", ".ts", ".html", ".css", ".json", ".md", ".sql"}


async def _get_pending_runs():
    """Return (run_id, org_id) pairs for completed runs with no embeddings yet."""
    from aether_os.core.db import get_session_factory
    from aether_os.core.models import Run, ArtifactEmbedding
    from sqlalchemy import select, not_, exists

    sf = get_session_factory()
    async with sf() as session:
        stmt = (
            select(Run.id, Run.org_id)
            .where(Run.status == "completed")
            .where(
                not_(
                    exists(
                        select(ArtifactEmbedding.id).where(
                            ArtifactEmbedding.run_id == Run.id
                        )
                    )
                )
            )
        )
        rows = (await session.execute(stmt)).all()
    return [(run_id, org_id) for run_id, org_id in rows]


async def embed_run(run_id: str, org_id: str) -> int:
    """Embed all artifacts for a single run. Returns number of files embedded."""
    from aether_os.core.artifact_store import get_artifact_store
    store = get_artifact_store()

    project_dir = _PROJECTS_DIR / run_id
    if not project_dir.exists():
        return 0

    count = 0
    for f in project_dir.rglob("*"):
        if f.is_file() and f.suffix in _EMBED_EXTENSIONS:
            try:
                content = f.read_text(errors="replace")
                rel = str(f.relative_to(project_dir))
                await store.store_artifact(run_id, rel, content, org_id=org_id)
                count += 1
                if count >= 50:
                    break
            except Exception as exc:
                print(f"  [warn] {f.name}: {exc}")
    return count


async def main() -> None:
    pending = await _get_pending_runs()
    if not pending:
        print("No completed runs without embeddings found.")
        return

    print(f"Found {len(pending)} run(s) to embed.")
    total = 0
    for run_id, org_id in pending:
        print(f"  Embedding run {run_id} (org={org_id}) ...", end=" ", flush=True)
        n = await embed_run(run_id, org_id)
        print(f"{n} file(s)")
        total += n

    print(f"\nDone. Embedded {total} artifact(s) across {len(pending)} run(s).")


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL") and not os.environ.get("AETHER_SECRET_KEY"):
        raise SystemExit(
            "ERROR: DATABASE_URL (or AETHER_SECRET_KEY for SQLite fallback) is not set.\n"
            "Source your .env file before running: source .env && python3 scripts/embed_existing.py"
        )
    asyncio.run(main())
