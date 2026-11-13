# src/harness/service/counsel.py — matter-aware Counsel chat (owner pick 2026-11-13)
"""Hybrid answers + "chat proposes, you confirm".

ask() answers a lawyer's message about ONE matter, in any run state:
  1. an imperative ("pause", "cancel", "redirect advice to: …", "start a run to …") is
     matched by rule and returned as a PROPOSAL; nothing here changes a run — the UI shows a
     confirm card and calls the existing command endpoints (pause/resume/cancel/redirect,
     POST /conversations/{cid}/messages for a new run);
  2. a status-type question (where are we, what failed, what's waiting on me, deliverables,
     deadlines, approvals, what a stage found) is answered from persisted records, no model;
  3. anything else goes through the egress gate as plain text — no tools, no JSON mode, so
     any provider the gate can route to serves it — with the matter's records as the only
     context; every [kind:id] citation is checked against those records.
Question and answer persist as thread messages; the answer's provenance rides `actor`
(counsel:records | counsel:model:<provider>/<model> | counsel:proposal | counsel:unavailable),
so no schema change."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from harness.service import authz, conversations
from harness.workflow import audit

DISPATCH = "matter.dispatch"
LIVE = {"executing", "waiting_human", "paused"}
WORD = {"executing": "running", "waiting_human": "waiting for your approval", "paused": "paused",
        "completed": "completed", "failed": "stopped (failed)", "cancelled": "cancelled"}
CTX_CAP = 24_000          # chars of record context handed to the model
# answer budget: reasoning models spend thinking tokens against max_tokens (thomson1 needs >=16k)
MAX_TOKENS = 16_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# -- the matter's records ---------------------------------------------------------------

def snapshot(con, mid: str, eid: str | None) -> dict:
    """Everything an answer may use, read fresh; the run is `eid` when it belongs to this
    matter, else the matter's latest run (None before any run)."""
    rows = lambda q, *a: [dict(r) for r in con.execute(q, a)]  # noqa: E731
    matter = dict(con.execute("SELECT * FROM matters WHERE matter_id=?", (mid,)).fetchone())
    run = None
    if eid:
        r = con.execute("SELECT * FROM executions WHERE execution_id=? AND matter_id=?",
                        (eid, mid)).fetchone()
        run = dict(r) if r else None
    if run is None:
        r = con.execute("SELECT * FROM executions WHERE matter_id=? ORDER BY started_at DESC"
                        " LIMIT 1", (mid,)).fetchone()
        run = dict(r) if r else None
    case = con.execute("SELECT state FROM cases WHERE matter_id=?", (mid,)).fetchone()
    return {
        "matter": matter, "run": run, "case_state": case["state"] if case else None,
        "tasks": rows("SELECT * FROM tasks WHERE execution_id=? ORDER BY seq",
                      run["execution_id"]) if run else [],
        "approvals": rows("SELECT approval_id, execution_id, kind, requested_at FROM approvals"
                          " WHERE matter_id=? AND state='pending'", mid),
        "artifacts": rows("SELECT artifact_id, execution_id, kind, title, review_state, content,"
                          " created_at FROM artifacts WHERE matter_id=? ORDER BY created_at", mid),
        "deadlines": rows("SELECT deadline_id, what, due, status, kind FROM deadlines"
                          " WHERE matter_id=? ORDER BY due", mid),
        "documents": rows("SELECT doc_id, filename, doc_type, ingest_status FROM documents"
                          " WHERE matter_id=? ORDER BY created_at", mid),
    }


def _refs(s: dict) -> dict[str, str]:
    """citation id -> human label, for every record the snapshot holds"""
    out = {}
    if s["run"]:
        out[f"run:{s['run']['execution_id']}"] = f"run {s['run']['execution_id']}"
    for t in s["tasks"]:
        out[f"stage:{t['key']}"] = f"stage {t['key']}"
    for a in s["approvals"]:
        out[f"approval:{a['approval_id']}"] = f"approval {a['kind']}"
    for a in s["artifacts"]:
        out[f"deliverable:{a['artifact_id']}"] = a["title"] or a["artifact_id"]
    for d in s["deadlines"]:
        out[f"deadline:{d['deadline_id']}"] = f"deadline {d['what']}"
    for d in s["documents"]:
        out[f"document:{d['doc_id']}"] = d["filename"] or d["doc_id"]
    return out


def _current(s: dict) -> dict | None:
    """the stage needing attention: the parked approval stage, else the first unfinished"""
    ts, run = s["tasks"], s["run"]
    if run and run["state"] == "waiting_human":
        done = [t for t in ts if t["state"] == "completed"]
        if done and done[-1]["approval_kind"]:
            return done[-1]
    return next((t for t in ts if t["state"] != "completed"), None)


# -- 1. commands (rule-matched, model-free) -----------------------------------------------

VERBS = {"pause": "pause", "hold": "pause", "resume": "resume", "unpause": "resume",
         "continue": "resume", "cancel": "cancel", "stop": "cancel", "abort": "cancel",
         "halt": "cancel", "redirect": "redirect", "rescope": "redirect", "refocus": "redirect",
         "change": "redirect", "start": "dispatch", "run": "dispatch", "launch": "dispatch",
         "begin": "dispatch", "dispatch": "dispatch", "skip": "skip"}
AMBIGUOUS = {"run", "change", "continue", "start", "stop"}
POLITE = re.compile(r"^(?:please|pls|kindly|ok(?:ay)?|now|then|and|can you|could you|would you|"
                    r"will you|lead counsel,?)\s+", re.I)


def command_of(text: str) -> tuple[str, str] | None:
    """(verb, rest) when the message is an instruction, else None. Imperative = the first
    word after any politeness is a command verb; 'why did it stop?' stays a question."""
    t = text.strip()
    while (m := POLITE.match(t)):
        t = t[m.end():]
    first, _, rest = t.partition(" ")
    verb = VERBS.get(first.lower().strip(",.!?:"))
    # "run status?", "change in the law?": these verbs double as nouns in questions
    if first.lower() in AMBIGUOUS and text.strip().endswith("?"):
        return None
    return (verb, rest.strip().rstrip("?").strip()) if verb else None


def propose(s: dict, verb: str, rest: str, text: str, can_act: bool) -> tuple[str, dict | None]:
    run = s["run"]
    if not can_act:
        return ("You can ask about this matter here, but changing a run needs dispatch "
                "permission on it."), None
    if verb == "dispatch":
        task = re.sub(r"^(?:a\s+)?(?:new\s+)?(?:run\s+)?(?:to|for|on|that|which|:)?\s*", "", rest,
                      flags=re.I).strip()
        if not task:
            return "What should the new run do? Say e.g. “start a run to draft the statutory demand”.", None
        busy = run and run["state"] in LIVE
        return f"I can start a new run with the task: “{task}”.", {
            "command": "dispatch", "task_text": task, "execution_id": None,
            "title": "Start a new run", "confirm": "Start run",
            "detail": ("Runs the legal pipeline on this matter with this task; its stage digest is "
                       "posted here when it completes."
                       + (f" Run {run['execution_id']} is still {WORD.get(run['state'], run['state'])}."
                          if busy else ""))}
    if not run:
        return "This matter has no run yet, so there is nothing to change. Say “start a run to …” to begin one.", None
    eid, state = run["execution_id"], run["state"]
    cur = _current(s)
    if verb == "skip":
        return ("Stages cannot be skipped: the orchestrator runs every stage in plan order. You "
                "can redirect a stage that has not started (“redirect <stage> to: …”) or cancel "
                "the run."), None
    if verb == "pause":
        if state != "executing":
            return f"Run {eid} is {WORD.get(state, state)}, so it cannot be paused.", None
        return f"I can pause run {eid}.", {
            "command": "pause", "execution_id": eid, "title": f"Pause run {eid}", "confirm": "Confirm pause",
            "detail": "Takes effect at the next stage boundary"
                      + (f"; stage {cur['key']} finishes first." if cur and cur["state"] == "running" else ".")}
    if verb == "resume":
        if state != "paused":
            return f"Run {eid} is {WORD.get(state, state)}, not paused, so there is nothing to resume.", None
        return f"I can resume run {eid}.", {
            "command": "resume", "execution_id": eid, "title": f"Resume run {eid}", "confirm": "Confirm resume",
            "detail": f"The run continues from stage {cur['key']}." if cur else "The run continues."}
    if verb == "cancel":
        if state not in LIVE:
            return f"Run {eid} is already {WORD.get(state, state)}.", None
        return f"I can cancel run {eid}.", {
            "command": "cancel", "execution_id": eid, "title": f"Cancel run {eid}", "confirm": "Confirm cancel",
            "detail": "Stages that have not started will not run. This cannot be undone."}
    # redirect: a named, not-yet-started stage plus the new instruction
    pending = [t for t in s["tasks"] if t["state"] == "pending"]
    if state not in LIVE or not pending:
        return f"Run {eid} has no stage left that can be redirected.", None
    low = text.lower()
    hit = next((t for t in pending if re.search(rf"\b{re.escape(t['key'].lower())}\b", low)), None)
    if hit is None:
        return ("Which stage? Stages not yet started: " + ", ".join(t["key"] for t in pending)
                + ". Say e.g. “redirect " + pending[0]["key"] + " to: focus on remedies”."), None
    m = re.search(rf"\b{re.escape(hit['key'])}\b\s*(?:stage\s*)?(?:to|:|so that|so it)\s*:?\s*(.+)",
                  text, re.I | re.S)
    instruction = m.group(1).strip() if m else ""
    if not instruction:
        return f"What should stage {hit['key']} do instead? Say “redirect {hit['key']} to: …”.", None
    return f"I can redirect stage {hit['key']} of run {eid}.", {
        "command": "redirect", "execution_id": eid, "task_id": hit["task_id"], "stage": hit["key"],
        "instruction": instruction, "title": f"Redirect stage {hit['key']}", "confirm": "Confirm redirect",
        "detail": f"New instruction: “{instruction}”. It replaces the stage's current instruction before it starts."}


# -- 2. record answers (model-free) -------------------------------------------------------

def _status(s: dict) -> tuple[str, list[str]]:
    run = s["run"]
    if not run:
        st = f" The case is at {s['case_state']}." if s["case_state"] else ""
        return f"This matter has no runs yet.{st} Say “start a run to …” to begin one.", []
    eid, ts, cur = run["execution_id"], s["tasks"], _current(s)
    done = sum(t["state"] == "completed" for t in ts)
    out = [f"Run {eid} is {WORD.get(run['state'], run['state'])}"
           + (f" at stage {ts.index(cur) + 1} of {len(ts)} ({cur['key']})" if cur and run["state"] in LIVE else "")
           + f"; {done} of {len(ts)} stages complete."]
    refs = [f"run:{eid}"] + ([f"stage:{cur['key']}"] if cur else [])
    failed = [t for t in ts if t["state"] in ("failed", "timed_out")]
    out.append("Failed: " + ", ".join(t["key"] for t in failed) + "." if failed else "Nothing has failed.")
    waits = []
    if run["state"] == "paused":
        waits.append("resume the run")
    appr = s["approvals"]
    if appr:
        # approvals are matter-wide: name the run when it is not the one being discussed
        waits.append(f"{len(appr)} approval{'s' if len(appr) > 1 else ''} ("
                     + ", ".join(a["kind"] + ("" if a["execution_id"] == eid else f" on run {a['execution_id']}")
                                 for a in appr) + ")")
        refs += [f"approval:{a['approval_id']}" for a in appr]
    out.append("Waiting on you: " + " and ".join(waits) + "." if waits else "Nothing is waiting on you.")
    return " ".join(out), refs


def _failures(s: dict) -> tuple[str, list[str]]:
    failed = [t for t in s["tasks"] if t["state"] in ("failed", "timed_out")]
    if not s["run"]:
        return "This matter has no runs yet, so nothing has failed.", []
    if not failed:
        return f"No stage of run {s['run']['execution_id']} has failed.", [f"run:{s['run']['execution_id']}"]
    return " ".join(f"Stage {t['key']} failed after {t['attempts']} of {t['max_attempts']} attempts"
                    + (f": {t['result_summary']}" if t["result_summary"] else " (no error text was recorded).")
                    for t in failed), [f"stage:{t['key']}" for t in failed]


def _deliverables(s: dict) -> tuple[str, list[str]]:
    arts = s["artifacts"]
    if not arts:
        return "No deliverables have been produced on this matter yet.", []
    return "Deliverables on this matter: " + "; ".join(
        f"{a['title'] or a['artifact_id']} ({a['kind'] or 'artifact'}, "
        f"{str(a['review_state'] or 'unreviewed').replace('_', ' ')})" for a in arts) + ".", \
        [f"deliverable:{a['artifact_id']}" for a in arts]


def _deadlines(s: dict) -> tuple[str, list[str]]:
    dl = [d for d in s["deadlines"] if (d["status"] or "open") not in ("done", "met", "closed")]
    if not dl:
        return "No open deadlines are recorded for this matter.", []
    return "Open deadlines: " + "; ".join(f"{d['what']} — due {d['due']}" for d in dl) + ".", \
        [f"deadline:{d['deadline_id']}" for d in dl]


def _approvals(s: dict) -> tuple[str, list[str]]:
    if not s["approvals"]:
        return "No approvals are waiting on this matter.", []
    return "Waiting for your decision: " + "; ".join(
        f"{a['kind']} (run {a['execution_id']})" for a in s["approvals"]) + ". Decide them in the run's overview or the Approval Center.", \
        [f"approval:{a['approval_id']}" for a in s["approvals"]]


def _stage(s: dict, t: dict) -> tuple[str, list[str]]:
    body = t["result_summary"] or ("no summary was recorded" if t["state"] == "completed"
                                   else f"it has not finished ({t['state']})")
    return f"Stage {t['key']} ({t['agent_id'] or 'agent'}): {body}", [f"stage:{t['key']}"]


ASK = [(re.compile(r"\b(fail\w*|error\w*|went wrong|broke\w*)\b"), _failures),
       (re.compile(r"\b(deliverables?|drafts?|outputs?|produced|artifacts?)\b"), _deliverables),
       (re.compile(r"\b(deadlines?|due)\b"), _deadlines),
       (re.compile(r"\b(approv\w*|sign.?off|checkpoints?)\b"), _approvals),
       (re.compile(r"\b(status|where are we|progress|happening|how far|blocked|blocking|stuck|"
                   r"waiting|what'?s next|next step|state of)\b"), _status)]
STAGE_Q = re.compile(r"\b(find|found|say|said|conclude\w*|result\w*|summar\w*|output|did|do)\b")


def records_answer(s: dict, text: str) -> tuple[str, list[str]] | None:
    low = text.lower()
    for t in s["tasks"]:                       # "what did research find?"
        if re.search(rf"\b{re.escape(t['key'].lower())}\b", low) and STAGE_Q.search(low):
            return _stage(s, t)
    for rx, fn in ASK:
        if rx.search(low):
            return fn(s)
    return None


# -- 3. model answer (any provider the gate routes to) -----------------------------------

def context(s: dict) -> str:
    m, run = s["matter"], s["run"]
    lines = [f"Matter: {m['title']} ({m['matter_type'] or 'type not recorded'}, "
             f"{m['jurisdiction'] or 'jurisdiction not recorded'}); case stage: {s['case_state'] or 'not recorded'}."]
    if m.get("objectives"):
        lines.append(f"Objectives: {m['objectives']}")
    if run:
        lines.append(f"[run:{run['execution_id']}] task: {run['input_task_text']}; state: {run['state']}.")
        for t in s["tasks"]:
            lines.append(f"[stage:{t['key']}] agent {t['agent_id']}; state {t['state']}; "
                         f"summary: {(t['result_summary'] or 'none')[:800]}")
    else:
        lines.append("No run has been started on this matter.")
    for a in s["approvals"]:
        lines.append(f"[approval:{a['approval_id']}] pending {a['kind']} approval for run {a['execution_id']}.")
    for d in s["deadlines"]:
        lines.append(f"[deadline:{d['deadline_id']}] {d['what']} due {d['due']} ({d['status'] or 'open'}).")
    for d in s["documents"]:
        lines.append(f"[document:{d['doc_id']}] uploaded document {d['filename']} ({d['doc_type'] or 'type not recorded'}).")
    for a in s["artifacts"]:
        lines.append(f"[deliverable:{a['artifact_id']}] {a['title']} ({a['kind']}, {a['review_state']}):\n"
                     f"{(a['content'] or '')[:1500]}")
    out = "\n".join(lines)
    return out if len(out) <= CTX_CAP else out[:CTX_CAP] + "\n[records truncated]"


SYSTEM = ("You answer a lawyer's question about ONE legal matter inside IronFleet. Use ONLY the "
          "matter records provided. After every fact, cite the record id in square brackets "
          "exactly as written in the records, e.g. [stage:research]. If the records do not answer "
          "the question, say so plainly and suggest starting a run to research it. Never invent "
          "facts, authorities, dates, documents or record ids. Be concise and plain.")
CITE = re.compile(r"\[([a-z]+:[^\]\s]+)\]")


def check_citations(answer: str, refs: dict[str, str]) -> tuple[str, list[str]]:
    """keep citations that name a real record; mark the rest unverified"""
    cited = []

    def sub(m):
        if m.group(1) in refs:
            cited.append(m.group(1))
            return m.group(0)
        return "[unverified citation]"
    return CITE.sub(sub, answer), list(dict.fromkeys(cited))


_GATE: dict = {"key": None, "gate": None}


def _default_dispatch(req, store_root: Path):
    """One plain-text completion through the egress gate. Rebuilt when Model settings change,
    so the admin's per-task assignment (any provider) applies without a restart."""
    from harness.bootstrap import build_gate
    from harness.cli import default_routing
    from harness.paths import resolve_store_root
    settings = resolve_store_root()[0] / "model-settings.json"
    key = settings.stat().st_mtime if settings.exists() else 0
    if _GATE["gate"] is None or _GATE["key"] != key:
        _GATE["gate"], _rt, _al = build_gate(Path(store_root) / "counsel_trace.sqlite3", default_routing())
        _GATE["key"] = key
    return asyncio.run(_GATE["gate"].dispatch(req))


dispatch = _default_dispatch     # tests swap this for a gate with a fake transport


def model_answer(s: dict, text: str, mid: str, store_root: Path) -> tuple[str, list[str], str]:
    from harness.gate import LLMRequest
    req = LLMRequest(matter_ref=mid, task_class="analysis", max_tokens=MAX_TOKENS,
                     # same classification the live pipeline's stages run under (factory default)
                     classification="LOCAL_PREFERRED",
                     messages=[{"role": "system", "content": SYSTEM},
                               {"role": "user", "content": f"MATTER RECORDS:\n{context(s)}\n\nQUESTION: {text}"}])
    try:
        res = dispatch(req, store_root)
    except Exception as ex:                                  # noqa: BLE001 — answered honestly below
        return (f"No model could answer this ({str(ex)[:200]}). Record answers still work: ask "
                "where the run is, what failed, what is waiting on you, deliverables, deadlines, "
                "or what a stage found."), [], "counsel:unavailable"
    if not (res.content or "").strip():
        return ("The model returned no answer (it may have spent its output budget reasoning). "
                "Try a narrower question."), [], f"counsel:model:{res.provider}/{res.model}"
    body, cited = check_citations(res.content.strip(), _refs(s))
    return body, cited, f"counsel:model:{res.provider}/{res.model}"


# -- the endpoint's use-case ---------------------------------------------------------------

def ask(con, principal: dict, cid: str, body: dict, *, store_root: Path) -> dict:
    conv = con.execute("SELECT * FROM conversations WHERE conversation_id=?", (cid,)).fetchone()
    if conv is None:
        raise authz.not_found("conversation_not_found", f"conversation {cid!r} not found")
    mid = conv["matter_id"]
    authz.require(con, principal, authz.READ, mid)
    text = ((body or {}).get("text") or "").strip()
    if not text:
        raise authz.ServiceError(422, "validation_failed", "text required")
    s = snapshot(con, mid, (body or {}).get("execution_id"))
    refs = _refs(s)
    action, cmd = None, command_of(text)
    if cmd:
        can_act = DISPATCH in authz.matter_perms(con, principal, mid)
        answer, action = propose(s, cmd[0], cmd[1], text, can_act)
        cited, actor = [], "counsel:proposal" if action else "counsel:records"
    elif (rec := records_answer(s, text)) is not None:
        (answer, cited), actor = rec, "counsel:records"
    else:
        answer, cited, actor = model_answer(s, text, mid, store_root)
    sources = [{"ref": r, "label": refs[r]} for r in cited if r in refs]
    stored = answer + ("\n\nSources: " + " · ".join(x["label"] for x in sources) if sources else "")
    qid, aid = f"msg-{uuid.uuid4().hex[:12]}", f"msg-{uuid.uuid4().hex[:12]}"
    con.execute("BEGIN IMMEDIATE")
    try:
        # execution_id stays NULL: a question is not a dispatched turn awaiting a run digest
        con.execute("INSERT INTO messages(message_id, conversation_id, matter_id, role, text,"
                    " execution_id, actor, ts) VALUES(?,?,?,?,?,?,?,?)",
                    (qid, cid, mid, "user", text, None, principal["username"], _now()))
        con.execute("INSERT INTO messages(message_id, conversation_id, matter_id, role, text,"
                    " execution_id, actor, ts, sources_json) VALUES(?,?,?,?,?,?,?,?,?)",
                    (aid, cid, mid, "lead", stored, None, actor, _now(),
                     json.dumps(sources) if sources else None))
        audit.append(con, matter_id=mid, actor=principal["username"], action="counsel.asked",
                     target=qid, outputs_digest=actor)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    get = lambda i: conversations.message_row(con.execute("SELECT * FROM messages WHERE message_id=?", (i,)).fetchone())  # noqa: E731
    return {"question": get(qid), "answer": get(aid), "sources": sources, "action": action}
