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
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from harness.alias import resolve_alias, UnknownAlias
from harness.gate import EgressGate, LLMRequest, GateRefusal
from harness.scheduler import TurnScheduler
from harness.capacity import machine_capacity

_loop_lock = threading.Lock()      # one background loop, shared by all request threads
_bg_loop: asyncio.AbstractEventLoop | None = None


class _QueueTimeout(RuntimeError):
    """A turn waited beyond the scheduler's queue_timeout. Mapped to 503 + Retry-After."""


class _DispatchFailed(RuntimeError):
    """A turn ran and failed — the gate's exception was recorded on the handle by the
    scheduler (which records rather than re-raises). do_POST then decides 403 vs 502 from
    the TRACE ROW, exactly as the S7b path did from the exception type."""


def _dispatch_scheduled(proxy: "EgressProxy", request: LLMRequest):
    """Run the gate's dispatch as a scheduled turn on the shared background loop (A-5).

    The scheduler serializes same-matter turns FIFO and bounds total concurrency by the
    machine's measured capacity; the HTTP thread blocks on the result exactly as before.

    The scheduler RECORDS the fn's exceptions on the handle instead of re-raising them, so
    a GateRefusal does not propagate out of here — it arrives as handle.status == "failed".
    do_POST therefore distinguishes the two outcomes by inspecting the handle, and 403-vs-502
    by the trace row the gate already wrote, which is the same evidence the S7b path used.
    """
    global _bg_loop
    with _loop_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            _bg_loop = asyncio.new_event_loop()
            # run_coroutine_threadsafe only makes progress while the loop is being driven;
            # one daemon thread drives it for the process lifetime (S7b lesson).
            threading.Thread(target=_bg_loop.run_forever, daemon=True).start()

    async def _run():
        handle = proxy.scheduler.submit(request.matter_ref, "chat",
                                        lambda: proxy.gate.dispatch(request))
        return await handle.wait(), handle

    future = asyncio.run_coroutine_threadsafe(_run(), _bg_loop)
    resp, handle = future.result()          # a transport/thread failure still raises here
    if handle.status == "failed":
        if "queue timeout" in handle.error:
            raise _QueueTimeout(handle.error)
        # The fn raised (policy refusal or upstream error). The gate traced the row before
        # the scheduler recorded the exception — do_POST reads that row for the status code.
        raise _DispatchFailed(handle.error)
    if handle.status == "cancelled":
        raise _DispatchFailed("turn cancelled before dispatch")
    return resp, handle


class UnknownMatter(RuntimeError):
    """Matter identity is unreadable or unregistered. Nothing may dispatch without it —
    there is no default matter and no routing by alias."""


def _read_matter(path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        raise UnknownMatter(str(path))
    if not isinstance(doc, dict) or "matter_ref" not in doc:
        raise UnknownMatter(str(path))
    return doc


def _read_matter_registry(matter_file) -> tuple[dict[str, dict], dict | None]:
    """A matter_file may be a single record (the S7b legacy form) or a directory of
    per-matter records (<root>/matters/<ref>/matter.json). Both resolve to the same
    {matter_ref: record} map; an unreadable or empty registry is UnknownMatter.

    The second return value is the DEFAULT record, and only the legacy single-record form
    yields one — a request carrying no identity falls back to the one matter.json on disk.
    A directory never yields a default, even a directory holding exactly one record: there
    is no default matter in the directory form (spec §4). Keeping that asymmetry here,
    rather than testing a record count in do_POST, makes "no default matter" a property of
    the form instead of an accident of how many records happen to be on disk.

    Read on every request, not cached at construction: adding a window is dropping a
    record into the directory, and the proxy must see it without a restart."""
    p = Path(matter_file)
    if p.is_dir():
        out: dict[str, dict] = {}
        for child in sorted(p.iterdir()):
            rec = child / "matter.json"
            if rec.is_file():
                doc = _read_matter(rec)
                out[doc["matter_ref"]] = doc
        if not out:
            raise UnknownMatter(str(p))
        return out, None
    doc = _read_matter(p)
    return {doc["matter_ref"]: doc}, doc


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
        # A-5 (spec §4): two shapes are accepted — the legacy /v1/chat/completions and the
        # per-matter /v1/m/<ref>/chat/completions. The ref captured here is the path-form
        # identity; a header, if present, takes precedence over it below.
        path_matter = None
        parts = self.path.split("/")
        if parts[:2] == ["", "v1"] and len(parts) > 4 and parts[2] == "m" \
                and parts[4:] == ["chat", "completions"]:
            path_matter = parts[3]
        elif self.path != "/v1/chat/completions":
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
        # A-5 (spec §4): matter identity in fixed precedence — header, then path, then the
        # legacy single record. An unregistered or unreadable matter is 500
        # matter_unavailable: no passthrough, no default matter, no routing by alias.
        try:
            registry, legacy_default = _read_matter_registry(self.proxy.matter_file)
        except UnknownMatter as ex:
            self._send_json(500, {"error": {"message": f"matter record unavailable: {ex}",
                                            "type": "matter_unavailable"}})
            return
        ref = self.headers.get("X-IronFleet-Matter") or path_matter
        matter = registry.get(ref) if ref else None
        if matter is None and ref is None and legacy_default is not None:
            # The S7b form: one matter.json on disk, no identity on the request. The single
            # record IS the matter. A directory never takes this branch — it has no default.
            matter = legacy_default
        if matter is None:
            self._send_json(500, {"error": {"message":
                f"matter {ref!r} is not registered — nothing dispatches without a record",
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
            resp, handle = _dispatch_scheduled(self.proxy, request)
        except _QueueTimeout as ex:
            # A saturated queue makes the client back off with a header it can act on,
            # rather than piling its own retries onto the queue (spec §3.4).
            body = json.dumps({"error": {"message": str(ex), "type": "queue_timeout"}})
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "5")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())
            return
        except _DispatchFailed as ex:
            # The gate already traced the row before the exception was recorded on the
            # handle. One failure mode, two causes: "no eligible provider" (policy) and
            # "all candidates failed" (upstream). They are told apart by the trace row the
            # gate wrote just before failing — a refused row is a 403, an error row is a
            # 502. The trace is the proof, not just the status code. (The S7b path reached
            # this branch via `except GateRefusal`; the scheduler boundary records rather
            # than re-raises, so the handle's status is the signal and the trace is still
            # the evidence — the S7b race test in tests/test_egress_proxy.py covers both.)
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
            self.send_header("X-IronFleet-Queue-Ms", f"{handle.queue_ms:.3f}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        # The queue wait is observable per-request: 0.0 when the turn never queued, > 0 when
        # it waited behind a same-matter turn or the global cap. C6 asserts the queued turn
        # genuinely queued; nothing else reads this header.
        self.send_header("X-IronFleet-Queue-Ms", f"{handle.queue_ms:.3f}")
        body = json.dumps({"id": "gate-dispatch", "object": "chat.completion",
                           "model": resp.model,
                           "choices": [{"index": 0, "finish_reason": "stop",
                                        "message": {"role": "assistant",
                                                    "content": resp.content}}],
                           "usage": resp.usage}, ensure_ascii=False).encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class EgressProxy:
    def __init__(self, host: str, port: int, gate: EgressGate, routing,
                 aliases: dict, matter_file, scheduler: TurnScheduler | None = None) -> None:
        self.gate, self.routing, self.aliases = gate, routing, aliases
        self.matter_file = matter_file
        # A scheduler built from the real machine's capacity when the caller omits one
        # (the tests pass a small synthetic one; the live driver builds its own).
        self.scheduler = scheduler or TurnScheduler(machine_capacity())
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
