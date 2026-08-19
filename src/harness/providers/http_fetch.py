# src/harness/providers/http_fetch.py
from __future__ import annotations
import httpx

async def openai_fetch(url: str, headers: dict, payload: dict | None = None) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
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
