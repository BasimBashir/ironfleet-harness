# tests/test_stream_fetch.py — streaming transport for reasoning-model endpoints.
# Atria-Dawn-Preview fills its entire output budget with reasoning_content and only then emits an
# answer; a buffered (non-streaming) response delivers nothing until generation completes, so a
# read timeout fires mid-generation and the call dies. Streaming keeps the connection live with
# deltas — the read timeout then bounds a STALLED stream, not a merely LONG one.
# No network: the server is a loopback SSE emitter.
import json

import pytest

from harness.providers.http_fetch import openai_stream_fetch


class _SSEServer:
    """A minimal loopback SSE server, so the fetch is exercised against a real socket."""

    def __init__(self, chunks: list[dict], stall_after: int | None = None,
                 status: int = 200) -> None:
        self.chunks, self.stall_after, self.status = chunks, stall_after, status
        self.requests: list[dict] = []
        self.server = None

    async def __aenter__(self) -> "_SSEServer":
        import asyncio
        async def handle(reader, writer):
            head = await reader.readuntil(b"\r\n\r\n")
            length = 0
            for line in head.decode(errors="replace").split("\r\n"):
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1])
            body = await reader.readexactly(length) if length else b""
            try:
                self.requests.append(json.loads(body))
            except Exception:                                  # noqa: BLE001 — record best effort
                pass
            if self.status >= 400:
                writer.write(f"HTTP/1.1 {self.status} ERR\r\nContent-Length: 0\r\n\r\n"
                             .encode())
                await writer.drain()
                writer.close()
                return
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n")
            await writer.drain()
            for i, chunk in enumerate(self.chunks):
                if self.stall_after is not None and i == self.stall_after:
                    await asyncio.sleep(3)                      # a stall the read timeout must catch
                writer.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                await writer.drain()
            writer.write(b"data: [DONE]\n\n")
            await writer.drain()
            writer.close()

        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)   # noqa: F821
        host, port = self.server.sockets[0].getsockname()[:2]
        self.url = f"http://{host}:{port}/v1/chat/completions"
        return self

    async def __aexit__(self, *exc) -> None:
        self.server.close()
        await self.server.wait_closed()


_USAGE = {"prompt_tokens": 19, "completion_tokens": 15, "total_tokens": 34,
          "completion_tokens_details": {"reasoning_tokens": 12}}


def _chunks(answer: str | None, reasoning: str | None = None) -> list[dict]:
    out: list[dict] = []
    if reasoning:
        out.append({"choices": [{"index": 0, "delta": {"reasoning_content": reasoning}}]})
    if answer is not None:
        out.append({"choices": [{"index": 0, "delta": {"content": answer},
                                 "finish_reason": None}]})
    out.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "model": "m"})
    out.append({"choices": [], "usage": _USAGE})
    return out


async def test_stream_fetch_assembles_content_and_usage():
    async with _SSEServer(_chunks("answer citing [Act, s 1]", "thinking")) as srv:
            result = await openai_stream_fetch(srv.url, {}, {
                "model": "m", "messages": [{"role": "user", "content": "q"}], "max_tokens": 32})
    assert result is not None
    assert result["choices"][0]["message"]["content"] == "answer citing [Act, s 1]"
    assert result["model"] == "m"
    assert result["usage"]["prompt_tokens"] == 19
    assert result["usage"]["completion_tokens"] == 15


async def test_stream_fetch_marks_stream_true():
    async with _SSEServer(_chunks("a")) as srv:
            await openai_stream_fetch(srv.url, {}, {"model": "m", "messages": []})
    assert srv.requests[0]["stream"] is True


async def test_stream_fetch_empty_content_is_none_not_empty_string():
    # A reasoning model that spends the whole budget on reasoning_content answers nothing. The
    # gate distinguishes None (a CAP failure) from "" (a genuine zero-length answer), so the
    # assembler must not manufacture an empty string.
    async with _SSEServer(_chunks(None, "all budget spent thinking")) as srv:
            result = await openai_stream_fetch(srv.url, {}, {"model": "m", "messages": []})
    assert result is not None
    assert result["choices"][0]["message"]["content"] is None


async def test_stream_fetch_content_arrives_across_many_deltas():
    chunks = [{"choices": [{"index": 0, "delta": {"content": part}}]}
              for part in ("cite ", "[Act, ", "s 1]", " done")]
    chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "model": "m"})
    chunks.append({"choices": [], "usage": _USAGE})
    async with _SSEServer(chunks) as srv:
            result = await openai_stream_fetch(srv.url, {}, {"model": "m", "messages": []})
    assert result["choices"][0]["message"]["content"] == "cite [Act, s 1] done"


async def test_stream_fetch_a_stall_raises_and_is_retryable():
    # The point of streaming: a LONG stream is fine, a STALLED one must still time out, so the
    # retry wrapper sees a failure rather than hanging the run indefinitely. The timeout is passed
    # explicitly — the module default binds at import, so an env override would never reach it.
    import httpx
    async with _SSEServer(_chunks("a"), stall_after=0) as srv:
        with pytest.raises(httpx.HTTPError):
            await openai_stream_fetch(srv.url, {}, {"model": "m", "messages": []}, timeout=1.0)


async def test_stream_fetch_none_on_http_error():
    async with _SSEServer([], status=500) as srv:
            assert await openai_stream_fetch(srv.url, {}, {"model": "m", "messages": []}) is None
