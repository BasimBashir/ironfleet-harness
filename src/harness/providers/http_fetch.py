# src/harness/providers/http_fetch.py
from __future__ import annotations
import os
import httpx

# Local 27B-class models can take minutes on a COLD first load (weights not yet in memory);
# cloud APIs always answer well inside this. Override with HARNESS_HTTP_TIMEOUT (seconds).
DEFAULT_TIMEOUT = float(os.environ.get("HARNESS_HTTP_TIMEOUT", "300"))

async def openai_fetch(url: str, headers: dict, payload: dict | None = None,
                       timeout: float = DEFAULT_TIMEOUT) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if payload is None:
                r = await client.get(url, headers=headers)
            else:
                r = await client.post(url, headers={**headers, "Content-Type": "application/json"},
                                      json=payload)
        if r.status_code >= 400:
            return None
        return r.json()
    except (httpx.HTTPError, ValueError):
        return None
