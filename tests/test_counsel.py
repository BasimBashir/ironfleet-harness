"""Matter-aware Counsel chat (service/counsel.py): rule-matched command proposals, record
answers, a model answer through any gate-routed provider with checked citations, and the
POST /conversations/{cid}/ask contract (authz, persistence, no run is ever changed)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from harness.service import counsel


def snap(state="executing", tasks=None, approvals=(), artifacts=(), deadlines=(), run=True):
    keys = [("intake", "completed", "facts gathered"), ("research", "completed", "s 297 applies [memo]"),
            ("strategy", "running", None), ("advice", "pending", None)]
    ts = tasks if tasks is not None else [
        {"task_id": f"e1-t{i}", "seq": i, "key": k, "agent_id": "clerk", "state": st, "attempts": 1,
         "max_attempts": 3, "result_summary": rs, "approval_kind": None, "instruction": f"do {k}"}
        for i, (k, st, rs) in enumerate(keys)]
    return {"matter": {"matter_id": "m1", "title": "Mainzeal", "matter_type": None, "jurisdiction": "NZ",
                       "objectives": None},
            "run": {"execution_id": "e1", "state": state, "input_task_text": "Analyse s 297"} if run else None,
            "case_state": "ANALYSIS", "tasks": ts if run else [], "approvals": list(approvals),
            "artifacts": list(artifacts), "deadlines": list(deadlines), "documents": []}


class TestCommands:
    @pytest.mark.parametrize("text,verb", [
        ("pause", "pause"), ("Please pause it after research", "pause"), ("can you pause it?", "pause"),
        ("resume", "resume"), ("stop the run", "cancel"), ("cancel", "cancel"),
        ("redirect advice to: focus on remedies", "redirect"), ("start a run to draft the demand", "dispatch"),
        ("skip moot", "skip")])
    def test_imperatives_are_commands(self, text, verb):
        assert counsel.command_of(text)[0] == verb

    @pytest.mark.parametrize("text", ["why did it stop?", "where are we?", "is s 297 relief likely?",
                                      "run status?", "change in the law since 2020?", "what failed"])
    def test_questions_are_not(self, text):
        assert counsel.command_of(text) is None

    def test_pause_only_while_executing_and_names_the_stage_that_finishes_first(self):
        msg, act = counsel.propose(snap(), "pause", "", "pause", True)
        assert act["command"] == "pause" and act["execution_id"] == "e1"
        assert "stage strategy finishes first" in act["detail"]
        assert counsel.propose(snap("paused"), "pause", "", "pause", True)[1] is None

    def test_resume_cancel_by_state(self):
        assert counsel.propose(snap("paused"), "resume", "", "resume", True)[1]["command"] == "resume"
        assert counsel.propose(snap(), "resume", "", "resume", True)[1] is None
        assert counsel.propose(snap("waiting_human"), "cancel", "", "cancel", True)[1]["command"] == "cancel"
        msg, act = counsel.propose(snap("completed"), "cancel", "", "cancel", True)
        assert act is None and "already completed" in msg

    def test_redirect_needs_a_not_started_stage_and_an_instruction(self):
        _, act = counsel.propose(snap(), "redirect", "", "redirect advice to: focus on remedies", True)
        assert (act["task_id"], act["instruction"]) == ("e1-t3", "focus on remedies")
        msg, act = counsel.propose(snap(), "redirect", "", "redirect research to: x", True)
        assert act is None and "Stages not yet started: advice" in msg      # research already ran
        msg, act = counsel.propose(snap(), "redirect", "", "redirect advice", True)
        assert act is None and "What should stage advice do instead" in msg

    def test_dispatch_skip_and_permission(self):
        _, act = counsel.propose(snap(), "dispatch", "a run to draft the demand", "", True)
        assert act["command"] == "dispatch" and act["task_text"] == "draft the demand"
        assert "still running" in act["detail"]
        assert counsel.propose(snap(), "skip", "", "skip moot", True)[1] is None
        msg, act = counsel.propose(snap(), "pause", "", "pause", False)
        assert act is None and "needs dispatch permission" in msg
        msg, act = counsel.propose(snap(run=False), "pause", "", "pause", True)
        assert act is None and "no run yet" in msg


class TestRecordAnswers:
    def test_status_with_waiting_on_you(self):
        s = snap("paused", approvals=[{"approval_id": "ap1", "execution_id": "e1", "kind": "filing"}])
        text, refs = counsel.records_answer(s, "where are we and what's blocking?")
        assert text.startswith("Run e1 is paused at stage 3 of 4 (strategy); 2 of 4 stages complete.")
        assert "Nothing has failed." in text and "Waiting on you: resume the run and 1 approval (filing)." in text
        assert refs == ["run:e1", "stage:strategy", "approval:ap1"]
        other = snap("executing", approvals=[{"approval_id": "ap2", "execution_id": "e9", "kind": "filing"}])
        assert "Waiting on you: 1 approval (filing on run e9)." in counsel.records_answer(other, "status")[0]

    def test_failures_deliverables_deadlines_and_a_stage_finding(self):
        failed = snap("failed", tasks=[{"task_id": "t", "seq": 0, "key": "attack", "agent_id": "a",
                                        "state": "failed", "attempts": 3, "max_attempts": 3,
                                        "result_summary": "TimeoutError", "approval_kind": None}])
        assert "Stage attack failed after 3 of 3 attempts: TimeoutError" in counsel.records_answer(failed, "why did it fail?")[0]
        arts = snap(artifacts=[{"artifact_id": "a1", "title": "memo.md", "kind": "memo", "review_state": "approved"}])
        assert counsel.records_answer(arts, "what deliverables do we have")[0] == "Deliverables on this matter: memo.md (memo, approved)."
        dl = snap(deadlines=[{"deadline_id": "d1", "what": "file defence", "due": "2026-12-01", "status": "open"}])
        assert counsel.records_answer(dl, "what's due?")[0] == "Open deadlines: file defence — due 2026-12-01."
        assert counsel.records_answer(snap(), "what did research find?") == ("Stage research (clerk): s 297 applies [memo]", ["stage:research"])

    def test_before_any_run_and_open_questions_fall_through(self):
        assert counsel.records_answer(snap(run=False), "status?")[0].startswith("This matter has no runs yet. The case is at ANALYSIS.")
        assert counsel.records_answer(snap(), "is s 297 relief likely here?") is None


class TestModelAnswer:
    def test_plain_text_request_any_provider_and_citations_checked(self, monkeypatch, tmp_path):
        seen = {}

        def fake(req, store_root):
            seen["req"] = req
            return SimpleNamespace(content="Relief is arguable [stage:research]; see [deliverable:ghost].",
                                   provider="any-provider", model="any-model")
        monkeypatch.setattr(counsel, "dispatch", fake)
        text, cited, actor = counsel.model_answer(snap(), "is s 297 relief likely?", "m1", tmp_path)
        req = seen["req"]
        assert (req.task_class, req.tools, req.tool_choice) == ("analysis", [], None)   # no tools/JSON mode
        assert "[stage:research]" in req.messages[1]["content"] and "QUESTION: is s 297" in req.messages[1]["content"]
        assert text == "Relief is arguable [stage:research]; see [unverified citation]."
        assert cited == ["stage:research"] and actor == "counsel:model:any-provider/any-model"

    def test_no_provider_or_empty_answer_is_said_plainly(self, monkeypatch, tmp_path):
        def refuse(req, store_root):
            raise RuntimeError("no eligible provider for analysis")
        monkeypatch.setattr(counsel, "dispatch", refuse)
        text, cited, actor = counsel.model_answer(snap(), "q", "m1", tmp_path)
        assert actor == "counsel:unavailable" and "no eligible provider for analysis" in text and cited == []
        monkeypatch.setattr(counsel, "dispatch", lambda r, s: SimpleNamespace(content=None, provider="p", model="m"))
        assert "returned no answer" in counsel.model_answer(snap(), "q", "m1", tmp_path)[0]


class TestEndpoint:
    def ask(self, w, role, text, cid=None, **extra):
        return w.client.post(f"/api/v1/conversations/{cid or w.A['cid']}/ask", headers=w.h(role),
                             json={"text": text, **extra})

    def test_records_answer_persists_both_turns_and_changes_nothing(self, api_world):
        w = api_world
        before = w.client.get(f"/api/v1/runs/{w.A['eid']}", headers=w.h("admin")).json()["state"]
        r = self.ask(w, "admin", "where are we?", execution_id=w.A["eid"])
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["action"] is None and body["answer"]["actor"] == "counsel:records"
        assert body["answer"]["text"].startswith(f"Run {w.A['eid']} is")
        assert body["question"]["execution_id"] is None            # never shown as "pending…"
        msgs = w.client.get(f"/api/v1/conversations/{w.A['cid']}/messages", headers=w.h("admin")).json()["items"]
        assert [m["role"] for m in msgs[-2:]] == ["user", "lead"]
        assert w.client.get(f"/api/v1/runs/{w.A['eid']}", headers=w.h("admin")).json()["state"] == before

    def test_cited_sources_persist_as_refs_on_the_answer(self, api_world, monkeypatch):  # UX-5
        w = api_world
        monkeypatch.setattr(counsel, "records_answer", lambda s, t: None)    # force the model path
        monkeypatch.setattr(counsel, "dispatch", lambda r, s: SimpleNamespace(
            content=f"See [document:{w.A['doc_id']}] and [document:doc-invented].", provider="p", model="m"))
        body = self.ask(w, "admin", "what does the upload say?").json()
        want = [{"ref": f"document:{w.A['doc_id']}", "label": "a.txt"}]
        assert body["sources"] == want and body["answer"]["sources"] == want
        assert "[unverified citation]" in body["answer"]["text"]               # the invented id is not a source
        msgs = w.client.get(f"/api/v1/conversations/{w.A['cid']}/messages", headers=w.h("admin")).json()["items"]
        assert msgs[-1]["sources"] == want and msgs[-2]["sources"] == [] and "sources_json" not in msgs[-1]

    def test_commands_are_proposals_only_and_need_dispatch(self, api_world):
        w = api_world
        r = self.ask(w, "admin", "cancel the run", execution_id=w.A["eid"]).json()
        assert r["action"]["command"] == "cancel" and r["answer"]["actor"] == "counsel:proposal"
        assert w.client.get(f"/api/v1/runs/{w.A['eid']}", headers=w.h("admin")).json()["state"] != "cancelled"
        r = self.ask(w, "reader", "cancel the run").json()          # readers may ask, not steer
        assert r["action"] is None and "needs dispatch permission" in r["answer"]["text"]

    def test_matter_isolation_and_validation(self, api_world):
        w = api_world
        assert self.ask(w, "outsider", "where are we?").status_code == 404
        assert self.ask(w, "admin", "where are we?", cid="cv-nope").status_code == 404
        assert self.ask(w, "admin", "   ").status_code == 422
        # a run id from another matter is ignored, never read across matters
        r = self.ask(w, "admin", "where are we?", execution_id=w.B["eid"]).json()
        assert w.B["eid"] not in r["answer"]["text"] and w.A["eid"] in r["answer"]["text"]
