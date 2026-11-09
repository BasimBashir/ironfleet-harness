# src/harness/api/routes/work.py — workflows, executions, agents, runs, approvals,
# requests, conversations (04 §5.4–§5.6, §5.8). parse -> one service call -> serialize.
from __future__ import annotations

from fastapi import APIRouter, Depends

from harness.api.deps import get_con, get_principal, page, paged
from harness.api.schemas import (AgentIn, AgentPatch, AnswerIn, ConversationIn,
                                 ExecutionIn, MessageIn, NoteIn, ReasonIn, RedirectIn,
                                 RequestIn, TextIn, WorkflowIn)
from harness.service import catalog, conversations, executions

router = APIRouter(prefix="/api/v1")
P = Depends(get_principal)
C = Depends(get_con)


# -- 5.4 workflows + executions ------------------------------------------------------

@router.get("/workflows")
def list_workflows(p=P, con=C):
    return catalog.list_workflows(con, p)


@router.post("/workflows", status_code=201)
def create_workflow(body: WorkflowIn, p=P, con=C):
    return catalog.create_workflow(con, p, body.model_dump())


@router.post("/matters/{mid}/executions", status_code=202)
def create_execution(mid: str, body: ExecutionIn, p=P, con=C):
    return executions.create(con, p, mid, body.model_dump())


@router.get("/executions/{eid}")
def get_execution(eid: str, p=P, con=C):
    return executions.get(con, p, eid)


@router.get("/executions/{eid}/tasks")
def execution_tasks(eid: str, p=P, con=C):
    return executions.tasks(con, p, eid)


@router.post("/executions/{eid}/pause", status_code=202)
def pause_execution(eid: str, p=P, con=C):
    return executions.pause(con, p, eid)


@router.post("/executions/{eid}/resume", status_code=202)
def resume_execution(eid: str, p=P, con=C):
    return executions.resume(con, p, eid)


@router.post("/executions/{eid}/cancel", status_code=202)
def cancel_execution(eid: str, body: ReasonIn | None = None, p=P, con=C):
    return executions.cancel(con, p, eid, body.model_dump() if body else {})


@router.post("/executions/{eid}/redirect", status_code=202)
def redirect_execution(eid: str, body: RedirectIn, p=P, con=C):
    return executions.redirect(con, p, eid, body.model_dump())


# -- 5.5 agents + runs -------------------------------------------------------------------

@router.get("/agents")
def list_agents(p=P, con=C):
    return catalog.list_agents(con, p)


@router.post("/agents", status_code=201)
def create_agent(body: AgentIn, p=P, con=C):
    return catalog.create_agent(con, p, body.model_dump())


@router.patch("/agents/{aid}")
def patch_agent(aid: str, body: AgentPatch, p=P, con=C):
    return catalog.patch_agent(con, p, aid, body.model_dump(exclude_unset=True))


@router.get("/matters/{mid}/runs")
def list_runs(mid: str, state: str = "", p=P, con=C):
    return catalog.list_runs(con, p, mid, state=state)


@router.get("/runs/{rid}")
def get_run(rid: str, p=P, con=C):
    return catalog.get_run(con, p, rid)


@router.post("/runs/{rid}/interject", status_code=202)
def interject_run(rid: str, body: TextIn, p=P, con=C):
    return catalog.interject(con, p, rid, body.model_dump())


@router.post("/runs/{rid}/cancel", status_code=202)
def cancel_run(rid: str, p=P, con=C):
    return catalog.cancel_run(con, p, rid)


# -- 5.6 approvals + requests -----------------------------------------------------------

@router.get("/approvals")
def list_approvals(state: str = "pending", pg=Depends(page), p=P, con=C):
    return paged(catalog.list_approvals(con, p, state=state, **pg))


@router.get("/matters/{mid}/approvals")
def matter_approvals(mid: str, state: str = "pending", p=P, con=C):
    return catalog.list_approvals(con, p, state=state, matter_id=mid, limit=200)["items"]


@router.post("/approvals/{apid}/approve")
def approve(apid: str, body: NoteIn | None = None, p=P, con=C):
    return catalog.decide(con, p, apid, approve=True, note=body.note if body else "")


@router.post("/approvals/{apid}/reject")
def reject(apid: str, body: NoteIn | None = None, p=P, con=C):
    return catalog.decide(con, p, apid, approve=False, note=body.note if body else "")


@router.post("/matters/{mid}/requests", status_code=201)
def create_request(mid: str, body: RequestIn, p=P, con=C):
    return catalog.create_request(con, p, mid, body.model_dump())


@router.post("/requests/{qid}/answer", status_code=202)
def answer_request(qid: str, body: AnswerIn, p=P, con=C):
    return catalog.answer_request(con, p, qid, body.model_dump())


# -- 5.8 counsel chat ----------------------------------------------------------------------

@router.get("/matters/{mid}/conversations")
def list_conversations(mid: str, p=P, con=C):
    return conversations.list_conversations(con, p, mid)


@router.post("/matters/{mid}/conversations", status_code=201)
def create_conversation(mid: str, body: ConversationIn | None = None, p=P, con=C):
    return conversations.create_conversation(con, p, mid, body.model_dump() if body else {})


@router.get("/conversations/{cid}/messages")
def list_messages(cid: str, pg=Depends(page), p=P, con=C):
    return paged(conversations.list_messages(con, p, cid, **pg))


@router.post("/conversations/{cid}/messages", status_code=202)
def post_message(cid: str, body: MessageIn, p=P, con=C):
    return conversations.post_message(con, p, cid, body.model_dump())
