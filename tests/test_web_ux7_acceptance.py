"""UX-7 (NEXT_STEPS §9B.7) end-to-end acceptance on the real application code path: create_app
serving the built web/dist, driven in Chromium, over a deterministic SYNTHETIC store (seed()).
No worker runs, so every run and stage stays exactly in the state seed() persisted.

Features that do not exist are asserted as their honest UI, never as present:
- a run-level "queued" state: an execution is `executing` from creation; only stages are Queued;
- tool-call / finding events: the server emits none (UX-4 gap E-1), so the stage drawer says so;
- planner-made parallel stages: create_execution numbers stages 1..n. claim() does run equal-seq
  stages concurrently (test_claim_runs_equal_seq_peers_concurrently), so the fixture writes two
  stages at one seq, the storage shape claim() honours, to exercise the hybrid graph.
`scripts/accept_ux7.py` runs journey() + capture() and writes a dated evidence directory."""
from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name, file):   # by file path: a site-packages `tests` package shadows ours
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


e2e = _load("ux7_e2e", "test_web_e2e.py")
a11y = _load("ux7_a11y", "test_web_a11y.py")

PW = "ux7-check-pass"
TITLE = "Kauri Logistics v Totara Freight (synthetic)"
CANARY = "kauri"           # in every name/text of the matter; an outsider must never receive it
DOC_NAME = "kauri-supply-agreement.md"
QUOTE = "the carrier bears demurrage for every pallet held beyond seventy two hours"
T0 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def doc_text() -> str:
    fill = lambda t: " ".join(f"Clause {t} sentence {i} records an ordinary synthetic term of the "  # noqa: E731
                              f"kauri supply arrangement." for i in range(12))
    return (f"1. PARTIES\n\nKauri Logistics Limited supplies freight services to Totara Freight Limited. {fill('a')}\n\n"
            f"2. DEMURRAGE\n\nThe parties agree that {QUOTE}. {fill('b')}\n\n"
            f"3. TERMINATION\n\nEither party may end the arrangement on ninety days written notice. {fill('c')}\n")


# (seq, stage, agent, state, summary, approval) — a seq shared by two stages = peers
RUNS = {
    "main": ("Advise Kauri Logistics on the demurrage dispute", "waiting_human", [
        (1, "intake", "clerk", "completed", "Facts gathered from the kauri supply agreement.", None),
        (2, "research-cases", "researcher", "completed", "Three demurrage authorities located (synthetic).", None),
        (2, "research-statute", "analyst", "completed", "Statutory research summary (synthetic).", None),
        (3, "draft", "drafter", "completed", "Kauri advice memo drafted for review.", "review"),
        (4, "review", "reviewer", "pending", None, None)]),
    "queued": ("Prepare the kauri chronology", "executing", [
        (1, "intake", "clerk", "pending", None, None), (2, "chronology", "researcher", "pending", None, None),
        (3, "draft", "drafter", "pending", None, None)]),
    "running": ("Check the kauri invoices", "executing", [
        (1, "intake", "clerk", "completed", "Invoices listed.", None),
        (2, "reconcile", "analyst", "running", None, None), (3, "draft", "drafter", "pending", None, None)]),
    "failed": ("Research kauri limitation defences", "failed", [
        (1, "intake", "clerk", "completed", "Limitation question framed.", None),
        (2, "research", "researcher", "failed", "TimeoutError: the model did not answer within 480s (synthetic)", None),
        (3, "draft", "drafter", "pending", None, None)]),
    "done": ("Index the kauri correspondence", "completed", [
        (1, "intake", "clerk", "completed", "Correspondence folder read.", None),
        (2, "index", "analyst", "completed", None, None),             # partial data: no summary recorded
        (3, "report", "drafter", "completed", "Index of 14 letters (synthetic).", None)]),
    "empty": ("Kauri run cancelled before any stage was planned", "cancelled", []),
}


def seed(con, root: Path, op: dict) -> dict:
    """Synthetic matters, users, document, runs, approval, next action and deliverable. Writes the
    same rows the services/orchestrator write; returns every id the checks need."""
    from harness.lifecycle import dossier
    from harness.service import auth, documents, lifecycle_api, matters
    from harness.workflow import approvals
    users = {n: {"user_id": auth.create_user(con, n, PW, role_id=r), "username": n, "role_id": r}
             for n, r in (("ux7-reader", "reader"), ("ux7-outsider", "editor"))}
    m1 = matters.create(con, op, {"title": TITLE, "client_ref": "KAURI-001", "jurisdiction": "NZ"})["matter_id"]
    m2 = matters.create(con, op, {"title": "Rimu Holdings estate (synthetic)"})["matter_id"]
    matters.put_member(con, op, m1, users["ux7-reader"]["user_id"], {"role_id": "reader"})
    matters.put_member(con, op, m2, users["ux7-outsider"]["user_id"], {"role_id": "editor"})
    for to in ("INTAKE", "ASSESS"):
        lifecycle_api.transition(con, op, m1, {"to": to})
    dossier.append(con, m1, "proposals", {"proposal_id": "na-ux7", "what": "Approve the kauri advice memo draft",
                                          "why": "The draft stage is parked at its review checkpoint."},
                   actor=op["username"])
    doc = documents.upload(con, op, m1, doc_text().encode(), filename=DOC_NAME, store_root=root)
    sfx, runs, tasks = m1[-6:], {}, {}
    for n, (key, (text, state, stages)) in enumerate(RUNS.items()):
        eid = f"exec-ux7{key}-{sfx}"
        start = T0 - timedelta(days=8) if key == "done" else T0 + timedelta(hours=n)
        at = lambda m: (start + timedelta(minutes=m)).isoformat()  # noqa: E731
        ev = lambda typ, m, tid=None: con.execute(  # noqa: E731
            "INSERT INTO workflow_events(matter_id, type, payload_json, ts) VALUES(?,?,?,?)",
            (m1, typ, json.dumps({"execution_id": eid, **({"task_id": tid} if tid else {})}), at(m)))
        plan = [{"stage": s, "agent": a, "instruction": f"{s} for: {text}"} for _, s, a, *_ in stages]
        con.execute("INSERT INTO executions(execution_id, matter_id, session_id, state, compiled_plan_json,"
                    " input_task_text, started_at) VALUES(?,?,?,?,?,?,?)",
                    (eid, m1, "ux7", "executing", json.dumps(plan), text, None if key == "empty" else at(0)))
        m = 0
        if key != "empty":
            ev("execution.created", m)
        for i, (seq, s, agent, st, summary, appr) in enumerate(stages, 1):
            tid = f"{eid}-t{i}"
            live = st == "running"
            con.execute("INSERT INTO tasks(task_id, execution_id, seq, key, agent_id, instruction, approval_kind,"
                        " state, lease_owner, lease_expires_at, attempts, max_attempts, result_summary)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (tid, eid, seq, s, agent, f"{s} for: {text}", appr, st, "w1" if live else None,
                         1e10 if live else None, 3 if st == "failed" else 0 if st == "pending" else 1, 3, summary))
            if st != "pending":
                ev("task.running", m, tid)
                m += 6
                if st in ("completed", "failed"):
                    ev(f"task.{st}", m, tid)
        tasks[key] = [f"{eid}-t{i}" for i in range(1, len(stages) + 1)]
        if state in ("failed", "completed", "cancelled"):
            if key != "empty":
                ev(f"execution.{state}", m, tasks[key][1] if state == "failed" else None)
            con.execute("UPDATE executions SET state=?, ended_at=? WHERE execution_id=?",
                        (state, None if key == "empty" else at(m), eid))
        runs[key] = eid
    main = runs["main"]
    approval = approvals.request(con, matter_id=m1, execution_id=main, task_id=tasks["main"][3], kind="review",
                                 payload={"result_summary": "Kauri advice memo ready for your approval."})
    art = f"art-ux7-{sfx}"
    con.execute("INSERT INTO artifacts(artifact_id, matter_id, execution_id, kind, title, content, review_state,"
                " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (art, m1, main, "memo", "Kauri advice memo (synthetic)",
                 f"# Advice memo (synthetic)\n\nThe agreement says \"{QUOTE}\".\n\n"
                 "It also says \"the customer may withhold every invoice for any reason at all\".\n",
                 "pending_review", T0.isoformat(), T0.isoformat()))
    return {"m1": m1, "m2": m2, "doc": doc["doc_id"], "doc_path": doc["path"], "art": art, "runs": runs,
            "tasks": tasks, "approval": approval, "users": users}


def fake_ingest(con, root: Path, m1: str, doc_id: str, path: str) -> int:
    """The corpus rows a real ingest writes for the upload (named by its stored file name, as ingest
    names sources), with zero vectors: no embedder runs in tests. Returns the chunk count."""
    from harness.corpus import CorpusStore, DocRecord, split_structure
    name, text = Path(path).name, doc_text()
    n = len(split_structure(name, text))
    CorpusStore(root / "corpus.sqlite3").ingest(m1, DocRecord(doc_id=name, text=text, source_name=name),
                                                [[0.0]] * n, "test", "test")
    con.execute("UPDATE documents SET ingest_status='ingested' WHERE doc_id=?", (doc_id,))
    return n


# -- browser helpers -------------------------------------------------------------------------------
def sign_in(pg, base, user, pw):
    pg.goto(base + "/#/")
    pg.wait_for_selector("#u", timeout=15000)
    pg.fill("#u", user)
    pg.fill("#p", pw)
    pg.click("button[type=submit]")
    pg.wait_for_selector(".top", timeout=15000)


def watch(pg) -> list[str]:
    errors: list[str] = []
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("dialog", lambda d: d.accept())
    return errors


RUN = "section[aria-label='Run overview']"
DRAWER = "aside[aria-label='Stage inspection']"


def open_run(pg, base, rid, node=None):
    pg.goto(f"{base}/#/runs/{rid}" + (f"/{node}" if node else ""))
    pg.wait_for_selector(RUN, timeout=15000)


def journey(live, ids, pg, shot=lambda name: None) -> None:
    """§9B.7 item 2: sign in → matter → next action → run → progress → agent → stage events →
    cited source passage → back to the run and the matter. Asserts as it goes."""
    B, m1, main = live.base, ids["m1"], ids["runs"]["main"]
    errors = watch(pg)
    sign_in(pg, B, "operator", e2e.PASSWORD)                                   # 1
    pg.wait_for_selector(f"table[aria-label=Matters] a:text('{TITLE}')", timeout=15000)
    shot("01-board")
    pg.click(f"table[aria-label=Matters] a:text('{TITLE}')")                    # 2
    pg.wait_for_selector("#ws-h")
    assert pg.inner_text("#ws-h") == TITLE
    pg.wait_for_selector("section[aria-labelledby=ov-next] >> text=Approve the kauri advice memo draft")
    wait = pg.inner_text("section[aria-labelledby=ov-wait]")                  # 3
    assert "Review draft" in wait and "Kauri advice memo ready for your approval." in wait, wait
    shot("02-matter-overview")
    pg.click("text=Decide in Decisions →")
    card = f"article.approval:has(a:text('{main}'))"
    pg.wait_for_selector(card)
    pg.click(f"{card} a:text('{main}')")                                         # 4
    pg.wait_for_selector(RUN)
    assert pg.url.endswith(f"#/runs/{main}")
    stages = pg.inner_text(f"{RUN} .runsec .sub")                                # 5
    assert stages.startswith("3 of 5 complete") and "1 awaiting approval" in stages and "1 queued" in stages, stages
    assert "Your approval is needed" in pg.inner_text(".nextact")
    assert "Hybrid" in pg.inner_text("section[aria-label='Stage map']")
    assert pg.locator("svg path[data-edge]").count() == 5    # t1→t2, t1→t3, t2→t4, t3→t4, t4→t5
    shot("03-run-overview")
    pg.click("button.node[aria-label^='Analyst']")                               # 6
    pg.wait_for_function("(t) => location.hash.endsWith(t)", arg=ids["tasks"]["main"][2])
    pg.wait_for_selector(f"{DRAWER} >> text=Analyst · stage 3 of 5")   # the hash moves before the re-render
    d = pg.inner_text(DRAWER)
    assert "Analyst · stage 3 of 5" in d and "intake · Completed" in d and "Needed by" in d, d
    assert "Stage research-statute completed" in d                                 # 7 nearest real event
    assert "Tool activity, findings and evidence references are not recorded per stage" in d  # E-1 honest
    shot("04-agent-drawer")
    pg.click(f"{RUN} a[href*='/drafts/']:text('Kauri advice memo')")              # 8
    pg.wait_for_selector("#dsrc-h")
    pg.wait_for_selector("section[aria-labelledby=dsrc-h] >> text=Not in corpus")   # sources load after the heading
    src = pg.locator("a", has_text=re.compile(rf"View source · {DOC_NAME}, passage \d"))
    assert src.count() == 1, "exactly the verified quote links a source; the invented one must not"
    assert "Not in corpus" in pg.inner_text("section[aria-labelledby=dsrc-h]")
    src.click()
    pg.wait_for_selector("li.passage[aria-current=true]")
    assert QUOTE in pg.inner_text("li.passage[aria-current=true]")
    assert pg.locator("nav.docrail button[aria-current=true]").count() == 1
    shot("05-source-passage")
    pg.go_back()                                                                 # 9
    pg.wait_for_selector("#dsrc-h")
    pg.click(f"a:text('run {main}')")
    pg.wait_for_selector(RUN)
    pg.click(f".runfacts a:text('{TITLE}')")
    pg.wait_for_selector("#ws-h")
    assert pg.url.split("#")[1] in (f"/m/{m1}", f"/m/{m1}/overview")
    assert not errors, errors[:3]


def capture(live, ids, pg, shot) -> None:
    """Principal screens at the agreed desktop viewport, light then dark (screens already signed in)."""
    B, m1, main = live.base, ids["m1"], ids["runs"]["main"]
    pg.set_viewport_size({"width": 1440, "height": 900})
    views = [("board", "#/board", "#board-h"), ("matter-overview", f"#/m/{m1}", "#ws-h"),
             ("run-waiting", f"#/runs/{main}", RUN), ("run-agent", f"#/runs/{main}/{ids['tasks']['main'][2]}", DRAWER),
             ("run-failed", f"#/runs/{ids['runs']['failed']}", RUN), ("run-historical", f"#/runs/{ids['runs']['done']}", RUN),
             ("draft-sources", f"#/m/{m1}/drafts/{ids['art']}", "#dsrc-h"),
             ("document-passage", f"#/m/{m1}/documents/{ids['doc']}/{ids['chunks'][1]}", "li.passage[aria-current=true]"),
             ("decisions", f"#/m/{m1}/decisions", "article.approval")]
    for theme in ("light", "dark"):
        a11y.set_prefs(pg, "firm", theme)
        for name, h, ready in views:
            pg.goto(f"{B}/{h}")
            pg.reload()
            pg.wait_for_selector(ready, timeout=15000)
            pg.wait_for_function("() => !document.querySelector('[aria-busy=true]')", timeout=15000)
            pg.evaluate("document.activeElement?.blur()")   # no focus ring in the evidence
            shot(f"{name}-{theme}")
    a11y.set_prefs(pg, "firm", "light")


def token_drift(pg) -> list[str]:
    """Every Chambers token (design/system/tokens.css) resolves on the running app unchanged, in
    both themes: the app is styled by the approved system, not a local copy."""
    css = (HERE.parent / "design" / "system" / "tokens.css").read_text(encoding="utf-8")
    blocks = {"light": css.split("[data-theme=")[0], "dark": css.split('[data-theme="dark"]')[1].split("}")[0]}
    out = []
    light = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", blocks["light"]))
    for theme, block in blocks.items():
        want = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))
        scope = {**light, **want}   # computed custom properties carry var() already substituted
        want = {k: re.sub(r"var\((--[\w-]+)\)", lambda m: scope[m.group(1)], v) for k, v in want.items()}
        pg.evaluate("(t) => { document.documentElement.dataset.theme = t; }", theme)
        got = pg.evaluate("(ks) => ks.map((k) => getComputedStyle(document.documentElement).getPropertyValue(k))",
                          list(want))
        out += [f"{theme} {k}: app {g!r} != tokens.css {w!r}" for (k, w), g in zip(want.items(), got)
                if _canon(g) != _canon(w)]
    return out


def _rgba(m: re.Match) -> str:
    """One colour as rgba with 2-dp alpha: the build minifies #ffffff→#fff and rgba(…)→#rrggbbaa."""
    s = m.group(0)
    if s.startswith("#"):
        h = s[1:]
        h = "".join(c * 2 for c in h) if len(h) in (3, 4) else h
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8] or "ff", 16) / 255
    else:
        r, g, b, *a = (float(x) for x in s[s.index("(") + 1:-1].split(","))
        a = a[0] if a else 1.0
    return f"rgba({int(r)},{int(g)},{int(b)},{a:.2f})"


def _canon(v: str) -> str:
    v = re.sub(r"\s+", "", v).lower()
    v = re.sub(r"(?<![\w.])(\d*\.?\d+)s\b", lambda m: f"{float(m.group(1)) * 1000:g}ms", v)  # .15s → 150ms
    return re.sub(r"#[0-9a-f]{3,8}\b|rgba?\([^)]*\)", _rgba, v)


# -- fixtures ------------------------------------------------------------------------------------
def build_world(root: Path):
    """A served, seeded, ingested scratch store; shared by the tests and scripts/accept_ux7.py."""
    from harness.service import system
    live = e2e.Live(root, worker=None)
    con = system.open_db(root)
    op = dict(con.execute("SELECT user_id, username, role_id FROM users WHERE username='operator'").fetchone())
    ids = seed(con, root, op)
    fake_ingest(con, root, ids["m1"], ids["doc"], ids["doc_path"])
    ids["chunks"] = [c["i"] for c in live.api("GET", f"/documents/{ids['doc']}/chunks")["chunks"]]
    return live, con, ids


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    reason = e2e.skip_reason()
    if reason:
        pytest.skip(reason)
    from playwright.sync_api import sync_playwright

    from harness.service import auth
    old, auth._ITER = auth._ITER, 1000
    root = tmp_path_factory.mktemp("ux7") / "store"
    root.mkdir()
    live, con, ids = build_world(root)
    p = sync_playwright().start()
    b = p.chromium.launch()
    try:
        yield live, ids, b, con
    finally:
        b.close()
        p.stop()
        con.close()
        live.stop()
        auth._ITER = old


def page(b):
    return b.new_context(viewport={"width": 1440, "height": 900}).new_page()


# -- tests (file order matters: the last one decides the approval) --------------------------------
def test_claim_runs_equal_seq_peers_concurrently(world):
    """The parallel shape the graph draws is one the orchestrator really executes: two pending
    stages at one seq are both claimable once every lower seq completed (scratch execution)."""
    _, ids, _, con = world
    from harness.workflow import orchestrator
    eid = orchestrator.create_execution(con, ids["m2"], session_id="ux7p", task_text="peers (synthetic)",
                                        stages=[{"stage": s, "agent": "a", "instruction": "i"} for s in "abc"])
    con.execute("UPDATE tasks SET seq=2 WHERE task_id=?", (f"{eid}-t3",))
    con.execute("UPDATE tasks SET state='completed' WHERE task_id=?", (f"{eid}-t1",))
    got = {orchestrator.claim(con, "w1")["task_id"], orchestrator.claim(con, "w2")["task_id"]}
    assert got == {f"{eid}-t2", f"{eid}-t3"}
    con.execute("UPDATE executions SET state='cancelled' WHERE execution_id=?", (eid,))


def test_fixture_has_the_required_shape(world):
    live, ids, _, _ = world
    assert len(ids["chunks"]) >= 3, ids["chunks"]
    agents = {t["agent_id"]: t["state"] for t in live.api("GET", f"/executions/{ids['runs']['main']}/tasks")}
    assert len(agents) == 5 and {"completed", "pending"} <= set(agents.values())
    assert live.api("GET", f"/runs/{ids['runs']['main']}")["state"] == "waiting_human"
    assert [a["approval_id"] for a in live.api("GET", f"/matters/{ids['m1']}/approvals?state=pending")] == [ids["approval"]]


def test_primary_journey(world):
    live, ids, b, _ = world
    journey(live, ids, page(b))


def test_run_states_and_partial_data(world):
    live, ids, b, _ = world
    pg, r = page(b), ids["runs"]
    errors = watch(pg)
    sign_in(pg, live.base, "operator", e2e.PASSWORD)
    text = lambda: pg.inner_text(RUN)  # noqa: E731
    nodes = lambda: pg.locator("button.node .s").all_inner_texts()  # noqa: E731

    open_run(pg, live.base, r["queued"])           # queued: no run-level state exists; stages say Queued
    assert pg.inner_text(f"{RUN} .runsec .sub") == "0 of 3 complete · 3 queued"
    assert "No action needed from you right now" in text()
    assert [s.strip("◌ ") for s in nodes()] == ["Queued"] * 3

    open_run(pg, live.base, r["running"])
    pg.wait_for_selector(".health[data-state=live]", timeout=15000)
    assert pg.inner_text(f"{RUN} .runsec .sub") == "1 of 3 complete · 1 running · 1 queued"
    assert any("Running" in s for s in nodes()) and "Live — new activity appears" in text()

    open_run(pg, live.base, r["main"])             # waiting on a person
    assert "Your approval is needed" in text() and pg.locator(f"{RUN} article.approval").count() == 1

    open_run(pg, live.base, r["failed"])
    t = text()
    assert "Stopped: stage research failed" in t and "Later stages did not run" in t
    assert pg.inner_text(".runhead .chip") == "Failed"
    assert any("Not run" in s for s in nodes()) and "TimeoutError" in pg.inner_text(DRAWER)

    open_run(pg, live.base, r["done"])             # historical, finished 8 days before T0
    t = text()
    assert "Completed — ready for your review" in t and "recorded history; no further activity is expected" in t
    assert "Duration" in t and "This run recorded no deliverables." in t
    pg.click("button.node[aria-label^='Analyst']")   # the stage with no recorded summary
    pg.wait_for_selector(f"{DRAWER} >> text=/^Analyst · stage/")
    assert pg.locator(f"{DRAWER} pre.log").count() == 0, "a missing summary must not be filled in"

    open_run(pg, live.base, r["empty"])            # partial: no stages, no events, no start time
    t = text()
    assert "No stage details were recorded for this run." in t and "No events recorded for this run." in t
    assert "Not available" in t and pg.locator("button.node").count() == 0
    assert "a per-run total is not recorded" in t      # tokens are matter-scoped, never shown per run

    pg.goto(f"{live.base}/#/runs/exec-does-not-exist")
    pg.wait_for_selector("[role=alert]")
    assert pg.locator(RUN).count() == 0
    assert all("404" in e for e in errors), errors[:3]   # only the expected not-found read


def test_disconnect_is_not_failure_and_reconnect_replays(world):
    live, ids, b, con = world
    rid, tid = ids["runs"]["running"], ids["tasks"]["running"][1]
    pg = page(b)
    sign_in(pg, live.base, "operator", e2e.PASSWORD)
    open_run(pg, live.base, rid)
    pg.wait_for_selector(".health[data-state=live]", timeout=15000)
    pg.context.set_offline(True)
    # offline emulation leaves an open fetch stream alone; end it server-side so the browser's
    # reconnect meets the dead network, as a real drop would
    sse = live.server.config.app.state.sse
    sse["max_s"] = 0
    pg.wait_for_selector(".health[data-state=reconnecting]", timeout=15000)
    sse["max_s"] = None
    assert "Live updates are disconnected" in pg.inner_text(RUN)
    assert pg.inner_text(".runhead .chip") == "Running", "a dropped browser connection is not a run failure"
    # the server carries on while this browser is away: the stage completes
    con.execute("UPDATE tasks SET state='completed', result_summary='Reconciled (synthetic).' WHERE task_id=?", (tid,))
    con.execute("INSERT INTO workflow_events(matter_id, type, payload_json, ts) VALUES(?,?,?,?)",
                (ids["m1"], "task.completed", json.dumps({"execution_id": rid, "task_id": tid}),
                 datetime.now(timezone.utc).isoformat()))
    pg.context.set_offline(False)
    pg.wait_for_selector("text=/Reconnected .* the server replayed every event/", timeout=20000)
    pg.wait_for_function("() => document.querySelector('section[aria-label=\"Run overview\"] .runsec .sub')"
                         "?.textContent.startsWith('2 of 3 complete')", timeout=15000)
    acts = pg.locator("ol.activity li").all_inner_texts()
    assert sum("Stage reconcile completed" in a for a in acts) == 1, acts   # replayed once, not duplicated


def test_permissions_isolate_matter_and_documents(world):
    """An outsider (editor of another matter) gets nothing of the matter by deep link, network
    response, DOM, storage or search — including in a tab where a member was signed in before.
    A reader member sees the checkpoint but cannot decide it or run anything."""
    import urllib.error
    import urllib.request
    live, ids, b, _ = world
    m1, main = ids["m1"], ids["runs"]["main"]
    pg = page(b)
    leaked: list[str] = []
    ui_token = [None]

    def inspect(route):   # every API body the outsider's session receives, read before it is used
        if "/events" in route.request.url:
            return route.continue_()    # a stream; the direct-API check below covers the channel
        resp = route.fetch()
        if ui_token[0] and route.request.headers.get("authorization") == f"Bearer {ui_token[0]}" \
                and CANARY in resp.text().lower():
            leaked.append(route.request.url)
        route.fulfill(response=resp)
    pg.route("**/api/**", inspect)
    sign_in(pg, live.base, "operator", e2e.PASSWORD)          # a member first, in the SAME tab
    open_run(pg, live.base, main, ids["tasks"]["main"][2])
    pg.click("button:text('Sign out')")
    sign_in(pg, live.base, "ux7-outsider", PW)
    ui_token[0] = pg.evaluate("sessionStorage.getItem('ironfleet.token')")
    assert ui_token[0], "the outsider's session token was not found"
    links = [(f"#/m/{m1}", "Matter not available"),
             (f"#/m/{m1}/documents/{ids['doc']}/{ids['chunks'][1]}", "Matter not available"),
             (f"#/m/{m1}/drafts/{ids['art']}", "Matter not available"), (f"#/runs/{main}", "Couldn't load this"),
             (f"#/runs/{main}/{ids['tasks']['main'][2]}", "Couldn't load this"), (f"#/case/{m1}/home", None),
             ("self-rep", None), (f"#/case/{m1}/home", None), (f"#/case/{m1}/intake", None), (f"#/runs/{main}", None)]
    for h, says in links:
        if h == "self-rep":                     # the guided screens read the same matter routes
            a11y.set_prefs(pg, "self-rep", "light")
            continue
        pg.goto(f"{live.base}/{h}")
        pg.reload()
        pg.wait_for_function("() => !document.querySelector('[aria-busy=true]') && document.querySelector('main > *')")
        pg.wait_for_timeout(400)
        if says:
            assert says in pg.inner_text("main"), (h, pg.inner_text("main")[:200])
        dom = pg.evaluate("() => document.documentElement.outerHTML + JSON.stringify(sessionStorage)"
                          " + JSON.stringify(localStorage)")
        assert CANARY not in dom.lower(), f"{h}: matter content in the DOM or storage"
    a11y.set_prefs(pg, "firm", "light")
    pg.goto(f"{live.base}/#/board")
    pg.reload()
    pg.wait_for_selector("#board-h")
    pg.keyboard.press("Control+k")
    pg.keyboard.type("Kauri")
    pg.wait_for_timeout(600)
    assert CANARY not in pg.inner_text("[role=dialog]").lower()
    pg.keyboard.press("Escape")
    assert "Rimu Holdings estate (synthetic)" in pg.inner_text("main")      # positive control
    assert not leaked, f"responses to the outsider carried matter content: {leaked}"
    # direct API reads, including the event channel and passages, fail closed with 404 and no name
    tok = live.api("POST", "/auth/login", {"username": "ux7-outsider", "password": PW})["token"]
    for path in (f"/matters/{m1}", f"/documents/{ids['doc']}/chunks", f"/documents/{ids['doc']}/text",
                 f"/documents/{ids['doc']}/meta", f"/artifacts/{ids['art']}/sources", f"/runs/{main}",
                 f"/executions/{main}/tasks", f"/events?channels=matter:{m1}"):
        req = urllib.request.Request(f"{live.base}/api/v1{path}", headers={"Authorization": f"Bearer {tok}"})
        with pytest.raises(urllib.error.HTTPError) as ex:
            urllib.request.urlopen(req, timeout=10)
        body = ex.value.read().decode()
        assert ex.value.code == 404 and CANARY not in body.lower(), (path, ex.value.code, body)

    rd = page(b)                                                # reader member: sees, cannot act
    sign_in(rd, live.base, "ux7-reader", PW)
    rd.goto(f"{live.base}/#/m/{m1}/decisions")
    rd.wait_for_selector("article.approval")
    btn = rd.locator("article.approval button:text('Approve')")
    assert btn.get_attribute("aria-disabled") == "true" and "requires approval.decide" in rd.inner_text("article.approval")
    btn.click(force=True)                                      # a click past the guard still decides nothing
    rd.wait_for_timeout(500)
    assert live.api("GET", f"/matters/{m1}/approvals?state=pending")[0]["approval_id"] == ids["approval"]
    rd.goto(f"{live.base}/#/m/{m1}")
    rd.wait_for_selector("#ws-h")
    assert rd.locator("#disp-t").count() == 0, "a reader must not see Dispatch"
    open_run(rd, live.base, ids["runs"]["running"])
    assert rd.locator(".runhead button:text('Pause'), .runhead button:text('Cancel')").count() == 0


def test_visual_tokens_match_chambers(world):
    live, _, b, _ = world
    pg = page(b)
    sign_in(pg, live.base, "operator", e2e.PASSWORD)
    assert not token_drift(pg)


def test_keyboard_and_accessibility_on_ux7_screens(world):
    """Keyboard smoke (graph/list fallback, agent drawer, passage rail, approval controls) and the
    D-6 audit (names, contrast, target size, status words) on the UX-7 screens, both themes."""
    live, ids, b, _ = world
    B, m1, main = live.base, ids["m1"], ids["runs"]["main"]
    pg = page(b)
    watch(pg)                                   # accepts the Approve confirmation
    sign_in(pg, B, "operator", e2e.PASSWORD)
    fails: list[str] = []
    want = lambda ok, msg: ok or fails.append(msg)  # noqa: E731
    open_run(pg, B, main)
    want(a11y.tab_to(pg, "button:text('List')"), "List toggle not reachable by Tab")
    pg.keyboard.press("Enter")
    pg.wait_for_selector("ol.stagemap")
    want(a11y.tab_to(pg, "ol.stagemap button[aria-label^='Researcher']"), "list node not reachable by Tab")
    pg.keyboard.press("Enter")
    pg.wait_for_function("(t) => location.hash.endsWith(t)", arg=ids["tasks"]["main"][1])
    try:
        pg.wait_for_selector(f"{DRAWER} >> text=Researcher · stage 2 of 5", timeout=5000)
    except Exception:  # noqa: BLE001 — recorded as a failure, the rest of the audit still runs
        fails.append("Enter on a list node did not inspect it")
    pg.keyboard.press("Escape")
    pg.wait_for_selector(DRAWER, state="detached")
    want(a11y.tab_to(pg, "button:text('Graph')"), "Graph toggle not reachable by Tab")
    pg.keyboard.press("Enter")
    want(a11y.tab_to(pg, ".graph button.node[aria-label^='Drafter']"), "graph node not reachable by Tab")
    pg.keyboard.press("Enter")
    pg.wait_for_function("(t) => location.hash.endsWith(t)", arg=ids["tasks"]["main"][3])

    pg.goto(f"{B}/#/m/{m1}/documents/{ids['doc']}")
    pg.wait_for_selector("nav.docrail")
    want(a11y.tab_to(pg, "nav.docrail li:nth-child(3) button"), "passage rail not reachable by Tab")
    pg.keyboard.press("Enter")
    pg.wait_for_function("(c) => location.hash.endsWith('/' + c)", arg=str(ids["chunks"][2]))
    want(pg.get_attribute(f"#chunk-{ids['chunks'][2]}", "aria-current") == "true", "Enter on a passage did not select it")

    views = [("run graph", f"#/runs/{main}"), ("run drawer", f"#/runs/{main}/{ids['tasks']['main'][2]}"),
             ("run failed", f"#/runs/{ids['runs']['failed']}"), ("run empty", f"#/runs/{ids['runs']['empty']}"),
             ("draft sources", f"#/m/{m1}/drafts/{ids['art']}"), ("decisions", f"#/m/{m1}/decisions"),
             ("document passage", f"#/m/{m1}/documents/{ids['doc']}/{ids['chunks'][1]}")]
    for theme in ("light", "dark"):
        for label, h in views:
            a11y.set_prefs(pg, "firm", theme)
            pg.goto(f"{B}/{h}")
            pg.reload()
            pg.wait_for_selector("main > *")
            pg.wait_for_function("() => !document.querySelector('[aria-busy=true]')")
            pg.wait_for_timeout(300)
            fails += [f"{theme} · {label} · {k}: {w}" for k, w in pg.evaluate(a11y.AUDIT_JS)]
    a11y.set_prefs(pg, "firm", "light")

    # approval controls, keyboard only — last, because it decides the checkpoint
    pg.goto(f"{B}/#/m/{m1}/decisions")
    card = "article.approval"
    pg.wait_for_selector(card)
    want(a11y.tab_to(pg, f"{card} input[type=text]"), "approval note not reachable by Tab")
    pg.keyboard.type("Approved from the keyboard (UX-7).")
    want(a11y.tab_to(pg, f"{card} button.btn--primary"), "Approve not reachable by Tab")
    pg.keyboard.press("Enter")
    pg.wait_for_selector(card, state="detached", timeout=15000)
    want(live.api("GET", f"/runs/{main}")["state"] == "executing", "approval did not release the run")
    fails += [f"focus-visible: no focus indicator on {w}" for w in sorted(a11y.NO_FOCUS_RING)]
    assert not fails, "\n".join(fails)
