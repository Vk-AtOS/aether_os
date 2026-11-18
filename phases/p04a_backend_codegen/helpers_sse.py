"""SSE realtime router generator — split from helpers.py to keep it under 600 lines.

Provides _generate_sse_router for generating Server-Sent Events routers.
"""
from __future__ import annotations

import re
import textwrap


def _generate_sse_router(features: list, project_name: str) -> str:
    """Generate src/routers/realtime_router.py with a Server-Sent Events stream.

    The generated router streams a JSON heartbeat every 5 seconds, scoped to
    the calling user's org_id when present.  The list of realtime_features is
    embedded as a comment so developers can see what spec features drove it.
    """
    def one_line(x) -> str:      # a newline in a comment would end it and the rest would run as code
        return re.sub(r"[\r\n]+", " ", str(x))
    project_name = one_line(project_name)
    features_comment = one_line(", ".join(str(f) for f in features)) if features else "generic realtime stream"
    return textwrap.dedent(f"""\
        # Generated realtime SSE router for {project_name}
        # Realtime features: {features_comment}
        from __future__ import annotations
        import asyncio
        import json
        import os
        import time
        from fastapi import APIRouter, Depends
        from fastapi.responses import StreamingResponse
        from auth import get_current_user

        realtime_router = APIRouter(prefix="/realtime", tags=["Realtime"])
        # A stream that never ends pins a worker connection for ever (clients that vanish behind a proxy are
        # never noticed): it ends after SSE_MAX_SECONDS and the browser's EventSource reconnects by itself.
        _MAX_SECONDS = int(os.environ.get("SSE_MAX_SECONDS", "1800"))


        @realtime_router.get("/stream")
        async def event_stream(user: dict = Depends(get_current_user)):
            \"\"\"Server-Sent Events stream scoped to the caller's org.\"\"\"
            async def generate():
                started = time.monotonic()
                yield ": connected\\n\\n"        # a comment frame is a heartbeat: it opens the stream through proxies
                while time.monotonic() - started < _MAX_SECONDS:
                    payload = json.dumps({{
                        "ts": time.time(),
                        "org_id": user.get("org_id"),
                        "user_id": user.get("id"),
                    }})
                    yield f"data: {{payload}}\\n\\n"
                    await asyncio.sleep(5)
                yield "event: stream_limit\\ndata: {{}}\\n\\n"

            # no-cache and X-Accel-Buffering: nginx buffers a response until it is full, so without the
            # header the events arrive in bursts or not at all.
            return StreamingResponse(generate(), media_type="text/event-stream",
                                     headers={{"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}})
    """)
