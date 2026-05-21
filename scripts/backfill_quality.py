"""One-shot backfill: score all completed runs and write quality_score + GlobalPattern."""
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://aetheros_user:aetheros_pass@127.0.0.1:5432/aetheros")


async def main():
    from aether_os.core.db import get_session_factory, init_db
    from aether_os.core.models import Run
    from aether_os.core.quality.metrics import score_project
    from aether_os.core.services.global_pattern_service import record_global_pattern
    from sqlalchemy import select, update

    await init_db()
    sf = get_session_factory()

    async with sf() as session:
        rows = (await session.execute(
            select(Run.id, Run.domain, Run.project_name)
            .where(Run.status == "completed")
        )).fetchall()

    print(f"Found {len(rows)} completed runs to backfill")

    projects_base = Path.home() / ".aether_os" / "projects"

    for run_id, domain, project_name in rows:
        project_dir = projects_base / run_id
        if not project_dir.exists():
            print(f"  SKIP {run_id[:8]} {project_name} — no artifacts on disk")
            continue

        try:
            qscore = score_project(project_dir)
            async with sf() as session:
                await session.execute(
                    update(Run).where(Run.id == run_id).values(quality_score=int(qscore.total))
                )
                await session.commit()

            async with sf() as session:
                await record_global_pattern(
                    run_id=run_id,
                    domain=domain or "general",
                    quality_score_total=float(qscore.total),
                    quality_details=qscore.details,
                    session=session,
                )

            print(f"  OK {run_id[:8]} {project_name:25} score={qscore.total} domain={domain}")
        except Exception as e:
            print(f"  ERR {run_id[:8]} {project_name} — {e}")

    print("\nBackfill complete.")


if __name__ == "__main__":
    asyncio.run(main())
