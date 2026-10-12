# src/harness/providers/http_fetch.py
from __future__ import annotations
import json
import os
import httpx

# Local 27B-class models can take minutes on a COLD first load (weights not yet in memory);
# cloud APIs always answer well inside this. Override with HARNESS_HTTP_TIMEOUT (seconds).
DEFAULT_TIMEOUT = float(os.environ.get("HARNESS_HTTP_TIMEOUT", "300"))

# A reasoning model (Atria-Dawn-Preview) can spend its ENTIRE output budget on reasoning_content
# and only start emitting an answer near the end — measured ~730s of pure reasoning at a 32k cap.
# A buffered response delivers nothing until generation completes, so a read timeout fires
# mid-generation and a legitimate call dies. Streaming keeps the connection alive with deltas, so
# the read timeout bounds a STALLED stream rather than a merely long one. Verified live: non-stream
# at 16k timed out past 1500s; the identical streaming request completed in 433s.
DEFAULT_STREAM_TIMEOUT = float(os.environ.get("HARNESS_HTTP_STREAM_TIMEOUT", "1800"))


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


async def openai_stream_fetch(url: str, headers: dict, payload: dict | None = None,
                              timeout: float = DEFAULT_STREAM_TIMEOUT) -> dict | None:
    """Streaming POST that reassembles an OpenAI-style completion from SSE deltas.

    Raises httpx.HTTPError on a transport failure (a stall, a reset) so the retrying wrapper below
    the gate can redo the call; returns None only on an HTTP error status, matching openai_fetch."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{url}",
                                     headers={**headers, "Content-Type": "application/json"},
                                     json={**(payload or {}), "stream": True}) as r:
                if r.status_code >= 400:
                    await r.aread()
                    return None
                content_parts: list[str] = []
                reasoning_parts: list[str] = []
                model: str | None = None
                usage: dict | None = None
                finish_reason: str | None = None
                saw_done = False
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[len("data:"):].strip()
                    if not body:
                        continue
                    if body == "[DONE]":
                        saw_done = True
                        continue
                    try:
                        chunk = json.loads(body)
                    except ValueError:
                        continue
                    model = chunk.get("model", model)
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            content_parts.append(delta["content"])
                        if delta.get("reasoning_content"):
                            reasoning_parts.append(delta["reasoning_content"])
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
        if not saw_done and finish_reason is None:
            # The stream ended without a terminator and without the server naming a finish_reason —
            # a truncated generation, not a completed one. Handing the partial content on with a
            # fabricated `finish_reason: "stop"` would score a truncated answer as a real result
            # with no tokens, silently corrupting the quality means. Raise instead: this is an
            # httpx.RemoteProtocolError (an httpx.HTTPError), so the retrying wrapper below the
            # gate redoes the call, and only a persistent truncation reaches the sidecar.
            raise httpx.RemoteProtocolError(
                "stream closed without [DONE] or a finish_reason — truncated generation")
        # None (not "") when the answer channel never arrived: a reasoning model that spent the
        # whole budget on reasoning_content is a CAP failure, and the gate distinguishes the two.
        content = "".join(content_parts) if content_parts else None
        return {
            "choices": [{"index": 0, "finish_reason": finish_reason or "stop",
                         "message": {"role": "assistant", "content": content,
                                     "reasoning_content": "".join(reasoning_parts) or None}}],
            "model": model,
            "usage": usage or {},
        }
    except ValueError:
        return None
