# src/harness/api/sse.py — GET /api/v1/events (04 §5.7)
"""Replay from Last-Event-ID (WHERE id > ?), then poll workflow_events; a
`: hb` comment every heartbeat_s (15 s; injectable via app.state.sse so tests
don't wait). Channel authorization runs BEFORE the stream opens, so
matter:{other} is a real 404, and again on every poll (access revoked
mid-stream ends the stream)."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from harness.api.deps import get_con, get_principal
from harness.service import events, system
from harness.service.authz import ServiceError

router = APIRouter(prefix="/api/v1")


def frame(e: dict) -> str:
    data = {**e["payload"], "matter_id": e["matter_id"], "ts": e["ts"]}
    return f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps(data, sort_keys=True)}\n\n"


@router.get("/events", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}})
def stream(request: Request, channels: str,
           last_event_id: Annotated[int | None, Header()] = None,
           p=Depends(get_principal), con=Depends(get_con)):
    chans = [c.strip() for c in channels.split(",") if c.strip()]
    if not chans:
        raise ServiceError(422, "validation_failed", "channels required")
    after = last_event_id or 0
    first = events.since(con, p, chans, after)          # authz: matter:B -> 404 here
    cfg = request.app.state.sse
    root = request.app.state.store_root

    async def gen():
        last, batch = after, first
        own = system.open_db(root)     # the request's con closes when the handler returns
        start = last_hb = time.monotonic()
        try:
            while True:
                for e in batch:
                    last = e["id"]
                    yield frame(e)
                now = time.monotonic()
                if now - last_hb >= cfg["heartbeat_s"]:
                    last_hb = now
                    yield ": hb\n\n"
                if cfg["max_s"] is not None and now - start >= cfg["max_s"]:
                    return
                if await request.is_disconnected():
                    return
                await asyncio.sleep(cfg["poll_s"])
                try:
                    batch = events.since(own, p, chans, last)
                except ServiceError:
                    return
        finally:
            own.close()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
