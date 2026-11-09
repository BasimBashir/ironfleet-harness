# src/harness/api/routes/lifecycle.py — the 08 §16 lifecycle catalogue (M7)
# (+ POST /lifecycle per plan §0.4: doc 07 wins — the operator enters COURT).
# parse -> one service call -> serialize. deadlines.ics is M9 (not here).
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from harness.api.deps import get_con, get_principal, page, paged
from harness.api.schemas import DebriefIn, FactsIn, IntakeAnswerIn, NoteIn, ToIn
from harness.service import lifecycle_api as lc

router = APIRouter(prefix="/api/v1/matters/{mid}")
P = Depends(get_principal)
C = Depends(get_con)


@router.get("/lifecycle")
def get_lifecycle(mid: str, p=P, con=C):
    return lc.lifecycle(con, p, mid)


@router.post("/lifecycle")
def post_lifecycle(mid: str, body: ToIn, p=P, con=C):
    return lc.transition(con, p, mid, body.model_dump())


@router.get("/next-actions")
def next_actions(mid: str, pg=Depends(page), p=P, con=C):
    return paged(lc.next_actions(con, p, mid, **pg))


@router.post("/next-actions/{aid}/complete", status_code=202)
def complete_next_action(mid: str, aid: str, body: NoteIn | None = None, p=P, con=C):
    return lc.complete_next_action(con, p, mid, aid, body.model_dump() if body else {})


@router.get("/dossier/facts")
def get_facts(mid: str, p=P, con=C):
    return lc.facts(con, p, mid)


@router.post("/dossier/facts", status_code=202)
def post_facts(mid: str, body: FactsIn, p=P, con=C):
    return lc.post_facts(con, p, mid, body.model_dump())


@router.get("/intake/questions")
def intake_questions(mid: str, p=P, con=C):
    return lc.intake_questions(con, p, mid)


@router.post("/intake/answers", status_code=202)
def intake_answers(mid: str, body: IntakeAnswerIn, p=P, con=C):
    return lc.intake_answer(con, p, mid, body.model_dump())


@router.get("/strategy")
def strategy(mid: str, pg=Depends(page), p=P, con=C):
    return paged(lc.strategy(con, p, mid, **pg))


@router.get("/strategy/{v}/diff")
def strategy_diff(mid: str, v: int, against: int = Query(...), p=P, con=C):
    return lc.strategy_diff(con, p, mid, v, against)


@router.get("/predictions")
def predictions(mid: str, pg=Depends(page), p=P, con=C):
    return paged(lc.predictions(con, p, mid, **pg))


@router.get("/flaws")
def flaws(mid: str, state: str = "", severity: str = "", pg=Depends(page), p=P, con=C):
    return paged(lc.flaws(con, p, mid, state=state, severity=severity, **pg))


@router.get("/hearing-pack")
def hearing_pack(mid: str, p=P, con=C):
    return lc.hearing_pack(con, p, mid)


@router.post("/mock-hearing", status_code=202)
def mock_hearing(mid: str, p=P, con=C):
    return lc.mock_hearing(con, p, mid)


@router.get("/debrief/questions")
def debrief_questions(mid: str, p=P, con=C):
    return lc.debrief_questions(con, p, mid)


@router.post("/debrief", status_code=202)
def debrief(mid: str, body: DebriefIn, p=P, con=C):
    return lc.post_debrief(con, p, mid, body.model_dump())


@router.get("/deadlines")
def deadlines(mid: str, pg=Depends(page), p=P, con=C):
    return paged(lc.deadline_list(con, p, mid, **pg))


@router.get("/lawyer-now")
def lawyer_now(mid: str, p=P, con=C):
    return lc.lawyer_now_read(con, p, mid)


@router.get("/closure-checklist")
def closure_checklist(mid: str, p=P, con=C):
    return lc.closure_checklist(con, p, mid)


@router.post("/close", status_code=202)
def close(mid: str, body: NoteIn | None = None, p=P, con=C):
    return lc.close(con, p, mid, body.model_dump() if body else {})
