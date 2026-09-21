"""The loopback egress proxy (S7b / A-1).

OpenCode's ONLY configured provider points here. We speak the OpenAI API to it and
translate each request into an LLMRequest for the existing EgressGate — the gate does
all classification, admission, provenance and tracing. This file never touches a
provider directly and never decides policy.

Fail-closed throughout: unknown alias, unreadable matter, gate refusal, transport
error — every one returns an error response. There is no passthrough.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from harness.alias import resolve_alias, UnknownAlias
from harness.gate import EgressGate, LLMRequest, GateRefusal

_loop_lock = threading.Lock()      # one background loop, shared by all request threads
_bg_loop: asyncio.AbstractEventLoop | None = None


def _dispatch_async(gate: EgressGate, request: LLMRequest):
    """Run the gate's async dispatch on a dedicated background loop.

    BaseHTTPRequestHandler is synchronous; the gate is async. A fresh loop per request
    works but cannot share the gate's connection pooling — one persistent loop, created
    lazily under a lock, serves all request threads.
    """
    global _bg_loop
    with _loop_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            _bg_loop = asyncio.new_event_loop()
            # run_coroutine_threadsafe only makes progress while the loop is being driven;
            # a loop that is merely created never runs the coroutine. One daemon thread
            # drives it for the process lifetime — shared by every request thread.
            threading.Thread(target=_bg_loop.run_forever, daemon=True).start()
    return asyncio.run_coroutine_threadsafe(gate.dispatch(request), _bg_loop).result()


def _read_matter(path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        raise UnknownMatter(str(path))
    if not isinstance(doc, dict) or "matter_ref" not in doc:
        raise UnknownMatter(str(path))
    return doc


class UnknownMatter(RuntimeError):
    """matter.json unreadable or missing a matter_ref. Nothing may dispatch without it."""


def _sse_chunks(resp) -> bytes:
    """Emit a batch gate result as a single SSE delta + [DONE].

    The gate's transport is batch (it must be — provenance and usage are only known
    once the call completes), so streaming is presentation, not plumbing: the whole
    completion arrives as one chunk. Provider-side streaming would bypass provenance
    assembly and is deliberately not supported."""
    delta = {"id": "gate-dispatch", "object": "chat.completion.chunk", "model": resp.model,
             "choices": [{"index": 0, "finish_reason": None,
                          "delta": {"role": "assistant", "content": resp.content}}]}
    final = {"id": "gate-dispatch", "object": "chat.completion.chunk", "model": resp.model,
             "choices": [{"index": 0, "finish_reason": "stop", "delta": {}}]}
    return (f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
            f"data: {json.dumps(final)}\n\ndata: [DONE]\n\n").encode()


class _Handler(BaseHTTPRequestHandler):
    proxy: "EgressProxy" = None        # set by the server factory below

    def log_message(self, *args):      # keep the test output clean
        pass

    def _send_json(self, code: int, doc: dict) -> None:
        body = json.dumps(doc, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send_json(200, {"object": "list", "data": [
                {"id": a, "object": "model", "owned_by": "ironfleet-gate"}
                for a in sorted(self.proxy.aliases)]})
        else:
            self._send_json(404, {"error": {"message": f"no such path {self.path}",
                                            "type": "not_found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": f"no such path {self.path}",
                                            "type": "not_found"}})
            return
        try:
            raw = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)))
        except (ValueError, KeyError):
            self._send_json(400, {"error": {"message": "malformed JSON body",
                                            "type": "bad_request"}})
            return
        try:
            task_class = resolve_alias(raw.get("model", ""), self.proxy.aliases)
        except UnknownAlias:
            self._send_json(400, {"error": {
                "message": f"unknown model '{raw.get('model')}': not a gate alias",
                "type": "bad_request"}})
            return
        try:
            matter = _read_matter(self.proxy.matter_file)
        except UnknownMatter as ex:
            # Nothing dispatches without a matter record — agent identity is a record.
            self._send_json(500, {"error": {"message": f"matter record unavailable: {ex}",
                                            "type": "matter_unavailable"}})
            return
        request = LLMRequest(matter_ref=matter["matter_ref"], task_class=task_class,
                             messages=raw.get("messages", []),
                             model=raw.get("model_override"),
                             classification=matter.get("classification", "LOCAL_PREFERRED"),
                             max_tokens=raw.get("max_tokens", 128_000))
        # Snapshot the row count BEFORE dispatching. by_matter() is matter-scoped, not
        # request-scoped — the gate's first append for THIS request is rows[prior], and
        # concurrent requests sharing a matter_ref can append in between. rows[-1] would
        # read another request's row and misreport a transport failure as a policy refusal.
        prior = len(self.proxy.gate.trace.by_matter(request.matter_ref))
        try:
            resp = _dispatch_async(self.proxy.gate, request)
        except GateRefusal as ex:
            # The gate already traced the refusal before raising. No fallback exists.
            # The gate raises one exception type for two different failures: "no eligible
            # provider" (policy) and "all candidates failed" (upstream). They are told apart
            # by the trace row the gate wrote just before raising — a refused row is a 403,
            # an error row is a 502. The trace is the proof, not just the status code.
            code, kind = 403, "gate_refusal"
            rows = self.proxy.gate.trace.by_matter(request.matter_ref)
            if len(rows) > prior and rows[prior].status == "error":
                code, kind = 502, "dispatch_error"
            self._send_json(code, {"error": {"message": str(ex), "type": kind}})
            return
        except Exception as ex:                     # noqa: BLE001 — surface, never pass through
            self._send_json(502, {"error": {"message": f"dispatch failed: {ex}",
                                            "type": "dispatch_error"}})
            return
        if raw.get("stream"):
            body = _sse_chunks(resp)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send_json(200, {"id": "gate-dispatch", "object": "chat.completion",
                              "model": resp.model,
                              "choices": [{"index": 0, "finish_reason": "stop",
                                           "message": {"role": "assistant",
                                                       "content": resp.content}}],
                              "usage": resp.usage})


class EgressProxy:
    def __init__(self, host: str, port: int, gate: EgressGate, routing,
                 aliases: dict, matter_file) -> None:
        self.gate, self.routing, self.aliases = gate, routing, aliases
        self.matter_file = matter_file
        self._server = ThreadingHTTPServer((host, port), self._make_handler())
        self._server.allow_reuse_address = True

    def _make_handler(self):
        proxy = self
        class Handler(_Handler):
            pass
        Handler.proxy = proxy
        return Handler

    @property
    def server_address(self):
        return self._server.server_address

    def start(self) -> None:
        t = threading.Thread(target=self._server.serve_forever, daemon=True)
        t.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
