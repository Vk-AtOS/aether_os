from fastapi import WebSocket
from typing import List
import asyncio, json, logging

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, event: dict):
        message = json.dumps(event)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_job_update(
        self, event_type: str, job: dict):
        await self.broadcast({
            "type": event_type,
            "job": job
        })

    async def broadcast_status(self, message: str):
        await self.broadcast({
            "type": "status",
            "message": message
        })

MANAGER = ConnectionManager()
