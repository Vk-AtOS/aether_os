"""SSE realtime router generator — split from helpers.py to keep it under 600 lines.

Provides _generate_sse_router for generating Server-Sent Events routers.
"""
from __future__ import annotations

import textwrap


def _generate_sse_router(features: list, project_name: str) -> str:
    """Generate src/routers/realtime_router.py with a Server-Sent Events stream.

    The generated router streams a JSON heartbeat every 5 seconds, scoped to
    the calling user's org_id when present.  The list of realtime_features is
    embedded as a comment so developers can see what spec features drove it.
    """
    features_comment = ", ".join(features) if features else "generic realtime stream"
    return textwrap.dedent(f"""\
        # Generated realtime SSE router for {project_name}
        # Realtime features: {features_comment}
        from __future__ import annotations
        import asyncio
        import json
        import time
        from fastapi import APIRouter, Depends
        from fastapi.responses import StreamingResponse
        from auth import get_current_user

        realtime_router = APIRouter(prefix="/realtime", tags=["Realtime"])


        @realtime_router.get("/stream")
        async def event_stream(user: dict = Depends(get_current_user)):
            \"\"\"Server-Sent Events stream scoped to the caller's org.\"\"\"
            async def generate():
                while True:
                    payload = json.dumps({{
                        "ts": time.time(),
                        "org_id": user.get("org_id"),
                        "user_id": user.get("id"),
                    }})
                    yield f"data: {{payload}}\\n\\n"
                    await asyncio.sleep(5)

            return StreamingResponse(generate(), media_type="text/event-stream")
    """)
