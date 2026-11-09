# src/harness/api/app.py — create_app(store_root) (M7, enterprise 04)
"""Error envelope for every error (incl. pydantic 422 -> validation_failed),
the Idempotency-Key middleware on POSTs, and the routers. Single tenant,
loopback bind (02 §12); no TLS here."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from harness.api import sse
from harness.api.routes import core, lifecycle, work
from harness.service import auth, idempotency, system
from harness.service.authz import ServiceError

_HTTP_CODES = {401: "unauthenticated", 403: "permission_denied", 404: "not_found",
               405: "method_not_allowed", 409: "conflict"}


def envelope(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {},
                      "trace_id": uuid.uuid4().hex}}


async def _send_json(send, status: int, body: bytes, *, replayed: bool = False) -> None:
    headers = [(b"content-type", b"application/json"),
               (b"content-length", str(len(body)).encode())]
    if replayed:
        headers.append((b"idempotent-replayed", b"true"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class IdempotencyMiddleware:
    """Pure ASGI (the body must be read once and fed back to the route). A POST
    carrying Idempotency-Key: same key + same request -> stored 2xx replayed;
    same key + different request -> 409 idempotency_conflict. Keyed per principal;
    an unauthenticated request passes through (the route answers 401)."""

    def __init__(self, app, store_root: Path):
        self.app, self.store_root = app, store_root

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        hdrs = {k.lower(): v for k, v in scope["headers"]}
        key = hdrs.get(b"idempotency-key", b"").decode("latin-1").strip()
        if not key:
            return await self.app(scope, receive, send)
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        fed = False

        async def replay():
            nonlocal fed
            if not fed:
                fed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        authz_h = hdrs.get(b"authorization", b"").decode("latin-1")
        token = authz_h[7:].strip() if authz_h.lower().startswith("bearer ") else None
        req_hash = hashlib.sha256(b"\0".join(
            [b"POST", scope["path"].encode(), scope.get("query_string", b""), body])
        ).hexdigest()
        con = system.open_db(self.store_root)
        try:
            p = auth.principal_for(con, token)
            if p is None:
                return await self.app(scope, replay, send)
            try:
                hit = idempotency.lookup(con, p["user_id"], key, req_hash)
            except ServiceError as e:
                return await _send_json(send, e.status, json.dumps(
                    envelope(e.code, e.message, e.details)).encode())
            if hit:
                return await _send_json(send, hit[0], hit[1].encode(), replayed=True)
            got = {"status": 0, "body": b""}

            async def capture(msg):
                if msg["type"] == "http.response.start":
                    got["status"] = msg["status"]
                elif msg["type"] == "http.response.body":
                    got["body"] += msg.get("body", b"")
                await send(msg)

            await self.app(scope, replay, capture)
            if 200 <= got["status"] < 300:
                idempotency.store(con, p["user_id"], key, req_hash, got["status"],
                                  got["body"].decode("utf-8", "replace"))
        finally:
            con.close()


def create_app(store_root, *, sse_heartbeat_s: float = 15.0, sse_poll_s: float = 0.5,
               sse_max_s: float | None = None, web_dist=None, worker: str | None = None,
               worker_poll_s: float = 1.0) -> FastAPI:
    """M8: `web_dist` (the built React client) is served at / after the API
    routes, so OpenAPI is unchanged; `worker="demo"` runs the harbour-freight
    demo body as one lifespan task (harness.service.worker)."""
    lifespan = None
    if worker is not None:
        if worker != "demo":
            raise ValueError(f"unknown worker body: {worker!r}")
        import asyncio
        from contextlib import asynccontextmanager

        from harness.service import worker as _worker

        @asynccontextmanager
        async def lifespan(_app):
            task = asyncio.create_task(_worker.loop(
                store_root, _worker.demo_body(store_root), poll_s=worker_poll_s))
            try:
                yield
            finally:
                task.cancel()

    app = FastAPI(title="IronFleet harness API", version="1", lifespan=lifespan)
    app.state.store_root = Path(store_root)
    app.state.sse = {"heartbeat_s": sse_heartbeat_s, "poll_s": sse_poll_s,
                     "max_s": sse_max_s}

    @app.exception_handler(ServiceError)
    async def _service_error(request, exc: ServiceError):
        return JSONResponse(status_code=exc.status,
                            content=envelope(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content=envelope(
            "validation_failed", "request validation failed",
            {"errors": jsonable_encoder(exc.errors())}))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=envelope(
            _HTTP_CODES.get(exc.status_code, "http_error"), str(exc.detail)),
            headers=getattr(exc, "headers", None))

    for r in (core.router, core.ops, work.router, lifecycle.router, sse.router):
        app.include_router(r)
    if web_dist is not None and Path(web_dist).is_dir():
        from starlette.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    app.add_middleware(IdempotencyMiddleware, store_root=Path(store_root))
    return app
