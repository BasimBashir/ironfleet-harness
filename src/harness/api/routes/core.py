# src/harness/api/routes/core.py — auth, matters, documents/evidence/artifacts, ops
"""Each handler: parse -> one service call -> serialize. No permission checks
here (they live in harness.service; enforced by tests/test_api_layering.py)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from harness.api.deps import get_con, get_principal, page, paged
from harness.api.schemas import (AssignIn, IngestIn, LoginIn, MatterIn, MatterPatch,
                                 MemberIn, PasswordIn, ProviderIn, ProviderNewIn, ReviewIn, SignupIn,
                                 ToIn, UserCreateIn, UserPatchIn)
from harness.service import (auth, conversations, documents, matters, skills, settings,
                             usage, users)

router = APIRouter(prefix="/api/v1")
ops = APIRouter()
P = Depends(get_principal)
C = Depends(get_con)
_RAW = {"requestBody": {"required": True, "content": {"application/octet-stream": {
    "schema": {"type": "string", "format": "binary"}}}}}


# -- 5.1 auth --------------------------------------------------------------------

@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, con=C):
    return auth.signup(con, body.username, body.password)


@router.post("/auth/password")
def set_password(body: PasswordIn, p=P, con=C):
    return auth.set_password(con, p, body.password)


@router.post("/auth/login")
def login(body: LoginIn, con=C):
    return auth.login(con, body.username, body.password)


@router.post("/auth/refresh")
def refresh(p=P, con=C):
    return auth.refresh(con, p)


@router.get("/auth/me")
def me(p=P, con=C):
    return auth.me(con, p)


# -- 5.2 matters -----------------------------------------------------------------

@router.get("/matters")
def list_matters(state: str = "", q: str = "", pg=Depends(page), p=P, con=C):
    return paged(matters.list_matters(con, p, state=state, q=q, **pg))


@router.post("/matters", status_code=201)
def create_matter(body: MatterIn, p=P, con=C):
    return matters.create(con, p, body.model_dump(exclude_none=True))


@router.get("/matters/{mid}")
def get_matter(mid: str, p=P, con=C):
    return matters.get(con, p, mid)


@router.get("/matters/{mid}/tokens")
def matter_tokens(mid: str, p=P, con=C):
    return usage.get(con, p, mid)


@router.patch("/matters/{mid}")
def patch_matter(mid: str, body: MatterPatch, p=P, con=C):
    return matters.patch(con, p, mid, body.model_dump(exclude_unset=True))


@router.delete("/matters/{mid}", status_code=204)
def delete_matter(mid: str, request: Request, p=P, con=C):
    matters.delete(con, p, mid, store_root=request.app.state.store_root)
    return Response(status_code=204)


@router.post("/matters/{mid}/state")
def matter_state(mid: str, body: ToIn, p=P, con=C):
    return matters.set_state(con, p, mid, body.model_dump())


@router.get("/matters/{mid}/members")
def list_members(mid: str, p=P, con=C):
    return matters.members(con, p, mid)


@router.put("/matters/{mid}/members/{uid}")
def put_member(mid: str, uid: str, body: MemberIn, p=P, con=C):
    return matters.put_member(con, p, mid, uid, body.model_dump())


@router.delete("/matters/{mid}/members/{uid}", status_code=204)
def delete_member(mid: str, uid: str, p=P, con=C):
    matters.delete_member(con, p, mid, uid)
    return Response(status_code=204)


# -- users & roles (05 §12; user.admin) -------------------------------------------

@router.get("/users")
def list_users(p=P, con=C):
    return users.list_users(con, p)


@router.post("/users", status_code=201)
def create_user(body: UserCreateIn, p=P, con=C):
    return users.create(con, p, body.model_dump())


@router.patch("/users/{uid}")
def patch_user(uid: str, body: UserPatchIn, p=P, con=C):
    return users.patch(con, p, uid, body.model_dump(exclude_unset=True))


@router.get("/roles")
def list_roles(p=P, con=C):
    return users.list_roles(con, p)


@router.post("/skills", status_code=201, openapi_extra=_RAW)
async def upload_skill(request: Request, name: str = Query(...), p=P, con=C):  # M13.6
    return skills.upload(con, p, name, await request.body(),
                         store_root=request.app.state.store_root)


# -- 5.x model settings (M13.7, user.admin) ------------------------------------------

@router.get("/settings/providers")
async def settings_view(request: Request, p=P, con=C):
    return settings.view(con, p, store_root=request.app.state.store_root)


@router.post("/settings/providers", status_code=201)
async def settings_add(request: Request, body: ProviderNewIn, p=P, con=C):
    return settings.add_provider(con, p, body.model_dump(),
                                 store_root=request.app.state.store_root)


@router.put("/settings/providers")
async def settings_put(request: Request, body: ProviderIn, name: str = Query(...),
                       p=P, con=C):
    return settings.put_provider(con, p, name, body.model_dump(exclude_unset=True),
                                 store_root=request.app.state.store_root)


@router.delete("/settings/providers", status_code=204)
async def settings_delete(request: Request, name: str = Query(...), p=P, con=C):
    settings.delete_provider(con, p, name, store_root=request.app.state.store_root)
    return Response(status_code=204)


@router.post("/settings/providers/test")
async def settings_test(request: Request, name: str = Query(...), p=P, con=C):
    return await settings.test_provider(con, p, name, store_root=request.app.state.store_root)


@router.put("/settings/assign")
async def settings_assign(request: Request, body: AssignIn,
                          task_class: str = Query(...), p=P, con=C):
    return settings.put_assign(con, p, task_class, body.provider,
                               store_root=request.app.state.store_root)


# -- 5.3 documents, evidence, artifacts ---------------------------------------------


@router.post("/matters/{mid}/documents", status_code=201, openapi_extra=_RAW)
async def upload_document(mid: str, request: Request, filename: str = Query(...),
                          doc_type: str = "", jurisdiction: str = "", p=P, con=C):
    # raw body + query params: no python-multipart (plan §0.1)
    return documents.upload(con, p, mid, await request.body(), filename=filename,
                            doc_type=doc_type, jurisdiction=jurisdiction,
                            store_root=request.app.state.store_root)


@router.post("/matters/{mid}/documents/ingest", status_code=202)
def ingest_documents(mid: str, body: IngestIn, request: Request, p=P, con=C):
    return documents.ingest_doc(con, p, mid, body.model_dump(),
                                store_root=request.app.state.store_root)


@router.get("/matters/{mid}/documents")
def list_documents(mid: str, pg=Depends(page), p=P, con=C):
    return paged(documents.list_docs(con, p, mid, **pg))


@router.get("/documents/{doc_id}", response_class=Response,
            responses={200: {"content": {"application/octet-stream": {}}}})
def get_document(doc_id: str, request: Request, p=P, con=C):
    _, data = documents.get_bytes(con, p, doc_id,
                                  store_root=request.app.state.store_root)
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{doc_id}"'})


@router.get("/documents/{doc_id}/meta")
def get_document_meta(doc_id: str, p=P, con=C):
    return documents.get_meta(con, p, doc_id)


@router.get("/documents/{doc_id}/text")
def get_document_text(doc_id: str, request: Request, p=P, con=C):
    return documents.get_text(con, p, doc_id, store_root=request.app.state.store_root)


@router.get("/documents/{doc_id}/chunks")
def get_document_chunks(doc_id: str, request: Request, p=P, con=C):
    return documents.get_chunks(con, p, doc_id, store_root=request.app.state.store_root)


@router.get("/matters/{mid}/evidence")
def list_evidence(mid: str, q: str = "", pg=Depends(page), p=P, con=C):
    return paged(documents.evidence(con, p, mid, q=q, **pg))


@router.get("/matters/{mid}/artifacts")
def list_artifacts(mid: str, review_state: str = "", pg=Depends(page), p=P, con=C):
    return paged(documents.list_artifacts(con, p, mid, review_state=review_state, **pg))


@router.get("/artifacts/{aid}")
def get_artifact(aid: str, p=P, con=C):
    return documents.get_artifact(con, p, aid)


@router.get("/artifacts/{aid}/sources")
def get_artifact_sources(aid: str, request: Request, p=P, con=C):
    return documents.artifact_sources(con, p, aid, store_root=request.app.state.store_root)


@router.post("/artifacts/{aid}/review")
def review_artifact(aid: str, body: ReviewIn, p=P, con=C):
    return documents.review_artifact(con, p, aid, body.model_dump())


@router.delete("/artifacts/{aid}", status_code=204)
def delete_artifact(aid: str, p=P, con=C):
    documents.delete_artifact(con, p, aid)
    return Response(status_code=204)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, request: Request, p=P, con=C):
    documents.delete_document(con, p, doc_id, store_root=request.app.state.store_root)
    return Response(status_code=204)


# -- 5.9 system -----------------------------------------------------------------------

@ops.get("/healthz")
def healthz(con=C):
    return conversations.healthz(con)


@router.get("/metrics")
def metrics(p=P, con=C):
    return usage.metrics(con, p)


@router.get("/usage")
def account_usage(p=P, con=C):
    return usage.account_usage(con, p)


@router.get("/audit")
def audit_list(matter_id: str = "", pg=Depends(page), p=P, con=C):
    return paged(conversations.audit_list(con, p, matter_id=matter_id, **pg))
