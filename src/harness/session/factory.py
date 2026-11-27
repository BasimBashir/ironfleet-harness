# src/harness/session/factory.py
"""The factory (spec 17 §5.2): task -> stage plan -> stages executed in order.

Three orchestration modes share this one module (D-T2):
  - shell-drives: the manager's TEXT plan is the plan (parse_plan);
  - hybrid:      the same, with SupervisorRoutes.resolve() as the FALLBACK when
                  the text will not parse;
  - agent-os:    the manager's spawn_agent calls produce the same StagePlan
                  (Task 8 lands the tool schema; the plan shape is already shared).

Design rules the research gate bought:
  - F5/P7: a stage's instruction rides in the agent FILE's body, not only the
    turn prompt. The probe proved the body wins — a stage agent file that
    contradicts its task makes the model answer the file. The stage file is
    therefore written into the workspace AFTER the sync (generate_all writes only
    persona files, so it never clobbers ours).
  - P7: a stage hands its summary to the next stage in the PROMPT, and its
    artifact FILE rides the workspace. Both proven live.
  - The jobs table (S7f, deferred to this step) gets one row per stage, so the
    global view reads the stage ledger without a new seam.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from harness.module_e.guard import guard_dir
from harness.module_e.supervisor import load_routes
from harness.session.driver import SessionDriver
from harness.session.errors import record_error
from harness.session.store import SessionStore, TurnRow

# The stage agent file is a PRIMARY (zero-tool) twin's sibling: mode primary, the
# tools we need true and every other false (tools: is an override, so an unlisted
# name keeps its default ENABLED state — the same rule _frontmatter documents).
# spawn_agent rides here so an agent-os MANAGER stage file can enable it (F3).
_STAGE_TOOLS = ("read", "glob", "grep", "task", "todowrite", "skill",
                "bash", "edit", "write", "webfetch", "spawn_agent",
                "ironfleet_corpus_search")

# The stage turn's task class — ONE constant for the agent md and the spawn's
# --model flag, which OVERRIDES agent frontmatter in opencode. The 2026-10-21
# live crew: the md pinned drafting but the flag still said extraction, so
# thomson1 served every stage no matter what the routing table promised.
STAGE_MODEL = "gate-local/gate/drafting"


@dataclass
class StagePlan:
    """stages in order + where they came from (`model` or `routes`)."""
    stages: list[dict] = field(default_factory=list)
    source: str = "routes"


_PLAN_FENCE = re.compile(r"```plan\s*\n(.*?)```", re.DOTALL)


def parse_plan(text: str) -> StagePlan | None:
    """The manager's TEXT plan: a fenced ```plan block of `stage|agent|instruction`
    lines. Anything unparseable returns None — the caller falls back (hybrid's
    contract; a raised exception here would make a rambling manager crash the
    shell instead of degrading to routes)."""
    if not text:
        return None
    m = _PLAN_FENCE.search(text)
    if not m:
        return None
    stages: list[dict] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3 or not all(parts):
            return None                      # one bad line makes it unparseable
        stage, agent, instruction = parts
        if ":" in agent or ":" in stage:
            return None                      # F9: colon-free ids at the source
        stages.append({"stage": stage, "agent": agent, "instruction": instruction,
                       "prompt": instruction})
    return StagePlan(stages=stages, source="model") if stages else None


def load_legal_pipeline(name: str = "legal_pipeline") -> list[dict]:
    """The one-prompt crew, as data (data/module-e/<name>.yaml): the stages
    a typed case goal runs when the user supplies no ```plan block. Lazy + cached
    by the loader's caller; a missing/broken file is a loud error, not a silent
    two-stage fallback. M6: `name` picks a workflow file — legal_pipeline is the
    case crew, workflows/hearing_pack.yaml and workflows/mock_hearing.yaml are
    the hearing workflows (a `/hearing-pack` | `/mock-hearing` goal picks them)."""
    import yaml
    data = Path(__file__).resolve().parents[3] / "data" / "module-e"
    data = data / f"{name}.yaml" if name == "legal_pipeline" else data / "workflows" / f"{name}.yaml"
    doc = yaml.safe_load(data.read_text(encoding="utf-8"))
    stages = doc.get("pipeline")
    if not stages:
        raise ValueError(f"legal pipeline {data}: no 'pipeline' stages — refusing to plan")
    return stages


def legal_plan(task: str, name: str = "legal_pipeline") -> StagePlan:
    """The one-prompt plan: every pipeline stage becomes a real stage with the
    user's ask interpolated ({task} — .replace, never .format: instructions carry
    braces of their own)."""
    stages = []
    specs = load_legal_pipeline(name)
    total = len(specs)
    for i, spec in enumerate(specs, start=1):
        instruction = spec["instruction"].replace("{task}", task)
        stages.append({"stage": spec["stage"], "agent": spec["agent"],
                       "instruction": instruction,
                       "approval": spec.get("approval"),
                       "gate": spec.get("gate"),
                       "prompt": _stage_prompt(stage=spec["stage"], instruction=task,
                                               agent=spec["agent"], index=i, total=total,
                                               task=task)})
    return StagePlan(stages=stages,
                     source="legal-pipeline" if name == "legal_pipeline"
                     else f"legal-pipeline:{name}")


def fallback_plan(intent: str, complexity: str, task: str) -> StagePlan:
    """The default crew for a typed goal. The product is legal work and the user's
    ruling (2026-10-21) is one prompt -> the whole pipeline, so the legal pipeline
    IS the fallback; SupervisorRoutes.resolve() stays available for hybrid intents
    (load_routes is unchanged). Each stage's instruction names the task, so the
    chain has somewhere to stand even when no model planned it.
    M6 (2026-11-08): a goal starting `/hearing-pack` or `/mock-hearing` picks the
    named workflow file instead (data/module-e/workflows/*.yaml)."""
    for prefix, name in (("/hearing-pack", "hearing_pack"), ("/mock-hearing", "mock_hearing")):
        if task.lstrip().lower().startswith(prefix):
            return legal_plan(task, name)
    return legal_plan(task)


def stage_agent_md(stage: str, instruction: str, tools: dict[str, bool] | None = None) -> str:
    """The per-stage agent file (F5). P7's lesson, live-proven: the BODY carries
    the standing instruction, and the tools map is an override — the stage's tool
    set is written true/false for every name so an unlisted tool cannot stay
    enabled by default. Never the canary body (it answers "unused")."""
    wanted = tools or {"read": True, "write": True,
                       # the ingested corpus is the stage's evidence base — a stage
                       # without it "found no case documents" while the corpus sat
                       # full (the 2026-10-20 live session)
                       "ironfleet_corpus_search": True}
    lines = {t: (t in wanted and bool(wanted[t])) for t in _STAGE_TOOLS}
    tool_yaml = "\n".join(f"  {t}: {str(v).lower()}" for t, v in lines.items())
    return ("---\n"
            f"description: factory stage {stage}\n"
            "mode: primary\n"
            # The stage's chat class: DRAFTING (the personas.yaml law — clerk IS
            # drafting), not extraction. Extraction is mechanical, so ollama-local
            # served every stage on this box and the crew ran on the 1k-output
            # local model no matter the classification; drafting is non-mechanical,
            # so the routing table promotes stages to the full-tier provider.
            f"model: {STAGE_MODEL}\n"
            "tools:\n"
            f"{tool_yaml}\n"
            "---\n"
            f"Stage {stage}: {instruction}\n"
            "\n"
            "Follow the user's instructions exactly. Write the requested files into "
            "the current workspace with the write tool — a reply that CONTAINS the "
            "document instead of writing the file is a failed stage (six stages of "
            "the 2026-10-21 live crew echoed their deliverables and wrote nothing). "
            "After writing, reply with only: the file path and a two-line summary. "
            "Ground every legal statement in ironfleet_corpus_search results; an "
            "authority not found in the corpus must be flagged [NOT IN CORPUS].\n")


def _stage_prompt(*, stage: str, instruction: str, agent: str, index: int, total: int,
                  task: str = "", previous_stage: str = "",
                  previous_summary: str = "", artifact: str = "") -> str:
    """One stage's turn prompt. The previous stage's SUMMARY rides in the prompt
    (P7's prompt carry) and its ARTIFACT rides the workspace file (P7's file
    carry) — both were proven live in the P7 probe, so the handoff needs no
    new seam."""
    parts = [f"Stage {index}/{total} ({stage}) of the task: {task or instruction}",
             f"Standing instruction: {instruction}"]
    if previous_stage and previous_summary:
        parts.append(f"The previous stage ({previous_stage}) reported: {previous_summary}")
    if artifact:
        parts.append(f"Its artifact is the workspace file {artifact} — use it as your input.")
    parts.append("Reply with exactly the requested text; the harness checks verbatim.")
    return "\n".join(parts)


def stage_prompt(stage: str, instruction: str, *, task: str = "",
                 previous_stage: str = "", previous_summary: str = "",
                 artifact: str = "") -> str:
    """The public handoff builder (tested directly; the runner uses the same shape)."""
    return _stage_prompt(stage=stage, instruction=instruction, agent="", index=1, total=1,
                         task=task, previous_stage=previous_stage,
                         previous_summary=previous_summary, artifact=artifact)


# -- the M6 moot stage helpers --------------------------------------------------

_ATTACK_ROW = re.compile(
    r"\[(CRITICAL|MAJOR|MINOR)\]\s*([A-Za-z_]+)\s*:\s*(.+)", re.IGNORECASE)


def _parse_attack_rows(text: str) -> list[dict]:
    """Parse the moot attack rows an agent turn writes: `[CRITICAL|MAJOR|MINOR]
    <class>: <detail>`. MAJOR maps to material (the keep-if-better vocabulary);
    anything unparseable is dropped — a malformed row is not an attack."""
    out = []
    for m in _ATTACK_ROW.finditer(text or ""):
        sev = m.group(1).upper()
        out.append({"severity": "material" if sev == "MAJOR" else sev.lower(),
                    "class": m.group(2).lower(), "detail": m.group(3).strip()[:400]})
    return out


def _sev_counts(result: dict) -> dict:
    """critical/material/minor counts over one moot_check result (compare()'s legs)."""
    counts = {s: 0 for s in ("critical", "material", "minor")}
    for f in result.get("flaws", []):
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1
    return counts


def _open_rows(con, matter_ref: str) -> list[dict]:
    from harness.lifecycle import dossier
    return dossier.read(con, matter_ref, "flaws")["open"]


def _supersede(con, matter_ref: str, prefix: str, why: str) -> None:
    """Mark open moot rows whose flaw_id starts with `prefix` fixed (same flaw_id,
    status fixed — dossier.read keeps the latest event). Without this a flaw
    filed once stayed open forever and no later round could ever be clean."""
    from harness.lifecycle import dossier
    for r in _open_rows(con, matter_ref):
        if str(r.get("flaw_id", "")).startswith(prefix):
            dossier.append(con, matter_ref, "flaws", {
                **{k: r.get(k) for k in ("flaw_id", "matter_id", "class", "severity",
                                         "doc", "detector")},
                "status": "fixed", "detail": f"superseded: {why}"}, actor="moot-gate")


def _ledger_append(con, matter_ref: str, result: dict, run_id: str, *,
                   round_no: int) -> None:
    """Every mechanical flaw row lands in the flaws register (the ledger), with
    its round and run so the cap report can reconstruct them."""
    from harness.lifecycle import dossier
    for i, f in enumerate(result.get("flaws", [])):
        dossier.append(con, matter_ref, "flaws", {
            "flaw_id": f"F-{run_id}-r{round_no}-{i}",
            "class": f.get("class", "other"), "severity": f.get("severity", "minor"),
            "doc": result.get("path", ""), "status": "open",
            "detector": f.get("detector", "moot-check"),
            "detail": (f.get("detail") or "")[:400]})


def register_deliverables(con, matter_id: str, execution_id: str, stage: dict, ws) -> int:
    """The files a stage's instruction names ("Write X.md") become reviewable
    drafts: one `artifacts` row each, review_state pending. A re-run of the stage
    replaces its row (new content goes back to pending review)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for name in re.findall(r"\bWrite ([\w.-]+\.md)", stage.get("instruction", "")):
        p = Path(ws) / name
        if not p.is_file():
            continue
        con.execute(
            "INSERT OR REPLACE INTO artifacts(artifact_id, matter_id, execution_id, kind,"
            " title, content, review_state, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?,'pending',?,?)",
            (f"art-{execution_id}-{stage['stage']}-{p.stem}", matter_id, execution_id,
             stage["stage"], name, p.read_text(encoding="utf-8", errors="replace"), now, now))
        n += 1
    return n


class FactoryRunner:
    """Executes a StagePlan against one session, stage by stage.

    The driver is the SessionDriver (the same one the CLI and the TUI drive) —
    the factory orchestrates, it never spawns anything itself."""

    def __init__(self, driver: SessionDriver, *, store: SessionStore | None = None,
                 mode: str = "shell-drives") -> None:
        if mode not in ("agent-os", "shell-drives", "hybrid"):
            raise ValueError(f"unknown mode: {mode!r}")
        self.driver = driver
        self.store = store
        self.mode = mode
        self._pending: dict[str, list[str]] = {}       # agent -> queued interjections

    # -- the plan -------------------------------------------------------------

    def plan(self, task: str, plan_text: str = "", intent: str = "",
             complexity: str = "LOW") -> StagePlan:
        """Model plan first (shell-drives), routes as the fallback (hybrid). With
        no declared intent the routes resolve their default_route — the factory
        must not invent one ("drafting" was a fabrication: it silently picked a
        two-stage plan nobody chose)."""
        if self.mode in ("shell-drives", "hybrid"):
            parsed = parse_plan(plan_text)
            if parsed:
                return parsed
        return fallback_plan(intent, complexity, task)

    # -- interjection (P7: the user steers one agent mid-flight) ---------------

    async def inject(self, session_id: str, agent: str, text: str) -> None:
        """The user's prompt to a specific agent becomes that agent's next turn at
        a stage boundary. P7 proved the continuation drive (`--session <id>`) is
        the seam that works; dequeueing happens in _drain_injections()."""
        self._pending.setdefault(agent, []).append(text)

    def _drain_injections(self, agent: str) -> list[str]:
        return self._pending.pop(agent, [])

    # -- execution ------------------------------------------------------------

    async def run_task(self, session_id: str, matter_ref: str, task: str,
                       plan_text: str = "", intent: str = "",
                       complexity: str = "LOW",
                       classification: str = "LOCAL_PREFERRED",
                       session_digest: str = "") -> list[TurnRow]:
        """Resolve the plan, then run its stages IN ORDER, each in its own
        workspace, handing the previous stage's summary forward in the prompt.
        `session_digest` is run-2+'s memory: the caller's summary of the last
        checkpoint/turns, seeded as stage 1's "previous stage" so a follow-up
        prompt continues from where the session left off (files hand forward
        separately, via the from-* copies)."""
        plan = self.plan(task, plan_text, intent=intent, complexity=complexity)
        if os.environ.get("HARNESS_DURABLE") == "1" and self.store:
            return await self._run_task_durable(session_id, matter_ref, task, plan,
                                                classification=classification,
                                                session_digest=session_digest)
        rows: list[TurnRow] = []
        prev_stage: str = "prior session" if session_digest else ""
        prev_summary: str = session_digest
        for stage in plan.stages:
            agent, instruction = stage["agent"], stage["instruction"]
            if self.store:
                self.store.add_job(session_id, stage["stage"], agent, "running",
                                   f"{plan.source} plan")
            try:
                row = await self._run_stage(session_id, matter_ref, task, stage,
                                            prev_stage, prev_summary,
                                            classification=classification)
            except Exception as exc:                              # noqa: BLE001
                # A dead stage is recorded and the run CONTINUES: one failed stage
                # must not take the session's remaining stages with it.
                record_error(exc, where="session.factory.run_task", root=self.store.root,
                             context={"session": session_id, "stage": stage["stage"],
                                      "agent": agent})
                if self.store:
                    self.store.add_job(session_id, stage["stage"], agent, "failed",
                                       f"{type(exc).__name__}: {exc}")
                continue
            rows.append(row)
            if self.store:
                self.store.add_job(session_id, stage["stage"], agent, "done",
                                   row.output_summary[:200])
            prev_stage, prev_summary = stage["stage"], row.output_summary
        return rows

    async def _run_stage(self, session_id: str, matter_ref: str, task: str, stage: dict,
                         prev_stage: str, prev_summary: str,
                         classification: str = "LOCAL_PREFERRED") -> TurnRow:
        """One stage: sync the workspace, write the stage agent file AFTER the
        sync (F5/P7), then one turn whose prompt carries the previous summary.
        A stage with `gate: moot` (M6) runs the moot round loop instead of one
        turn — the gate needs the platform registers, so it opens platform.db
        in both the durable and the legacy path."""
        if stage.get("gate") == "moot":
            return await self._run_moot_stage(session_id, matter_ref, task, stage,
                                               prev_stage, prev_summary,
                                               classification=classification)
        agent, instruction = stage["agent"], stage["instruction"]
        # P7's interjection rides an existing opencode session; a stage's first
        # turn opens one. The +1 keeps the two concerns from sharing one name.
        fname = f"{agent}-stage-{stage['stage']}"
        # The stage persona must live in the workspace run_turn will SPAWN in —
        # named after fname, not the bare agent. The old split (md in <agent>\,
        # spawn in <fname>\) left --agent pointing at a persona opencode could
        # not see, and every stage silently fell back to the default agent on
        # the extraction class (thomson1) — since Task 7 (2026-10-20 live crew).
        ws = self.driver.workspace_for(session_id, fname, matter_ref, classification)
        # M1/S4: the stage run owns the guard's authority file — block on the enforcement
        # stages (verify, filings) unless the served matter record's guard_block_stages
        # replaces the list. The `allowed` list itself is preserved; only `block` moves.
        record: dict = {}
        for anc in ws.parents[:4]:
            rec_p = anc / "matters" / matter_ref / "matter.json"
            if rec_p.exists():
                try:
                    record = json.loads(rec_p.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    record = {}
                break
        block_stages = record.get("guard_block_stages") or ("verify", "filings")
        g = guard_dir(ws)
        g.mkdir(parents=True, exist_ok=True)
        allowed_p = g / "allowed.json"
        prev: dict = {}
        if allowed_p.exists():
            try:
                prev = json.loads(allowed_p.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                prev = {}
        prev.update({"block": stage["stage"] in block_stages})
        allowed_p.write_text(json.dumps(prev), encoding="utf-8")
        (ws / ".opencode" / "agent").mkdir(parents=True, exist_ok=True)
        (ws / ".opencode" / "agent" / f"{fname}.md").write_text(
            stage_agent_md(stage["stage"], instruction), encoding="utf-8")
        # Hand the WORK forward, not just the summary: prior stages' deliverables
        # are copied into this stage's workspace under visible names. A stage's
        # cwd is its own directory, and reads across sibling workspaces hit
        # opencode's permission wall (the phase-2/3 crews' "source files aren't
        # at that path" + denied reads) — in-cwd reads are the path that works.
        if self.store:
            # ws.parent: the session dir the driver's matter guard checked, not a rebuilt path
            for src in ws.parent.glob("*/*.md"):
                # from-* are earlier forwards: re-forwarding them nests the names past MAX_PATH
                if ".opencode" in src.parts or src.parent == ws or src.name.startswith("from-"):
                    continue
                dest = ws / f"from-{src.parent.name}--{src.name}"
                if not dest.exists():
                    shutil.copy2(src, dest)
        prompt = _stage_prompt(stage=stage["stage"], instruction=instruction, agent=agent,
                               index=1, total=1, task=task, previous_stage=prev_stage,
                               previous_summary=prev_summary)
        fwd = sorted(p.name for p in ws.glob("from-*.md"))
        if fwd:
            # without the names the model reaches for the sibling path its summary
            # mentions, which opencode refuses (2026-11-17 Win11 test)
            prompt += ("\nEarlier stages' files are already in your workspace — read them "
                       "here, never from another directory: " + ", ".join(fwd))
        row = await self.driver.run_turn(session_id, matter_ref, fname, prompt,
                                         classification=classification,
                                         model=STAGE_MODEL)
        # The row records WHO ran (the persona), not the generated stage-file stem
        # the spawn needed: the JSONL row and the acceptance checks read `agent`
        # by name, and "hunter-stage-gather" is an implementation detail.
        row.agent = agent
        # A turn that ends on "Now let me read…" with the named deliverable unwritten
        # is not done: one nudge turn, then the summary says so instead of looking done.
        want = re.findall(r"\bWrite ([\w.-]+\.md)", instruction)
        if want and not any((ws / f).exists() for f in want):
            row = await self.driver.run_turn(
                session_id, matter_ref, fname,
                f"Your last turn ended before you wrote {want[0]}. Do the work and write "
                f"it now.\n\n{prompt}", classification=classification, model=STAGE_MODEL)
            row.agent = agent
            if not any((ws / f).exists() for f in want):
                row.output_summary = (
                    f"[NO DELIVERABLE: {want[0]} not written] The model ended its turn twice "
                    "without writing the file. If the Agents log shows failed model calls "
                    "(no or invalid API key, rate limit), fix the provider in Model settings "
                    "(Test must pass); if the calls succeeded, assign a stronger cloud LLM to "
                    f"the drafting class (Model settings → Stage assignment). Then re-run. "
                    f"{row.output_summary}")
        for text in self._drain_injections(agent):
            # P7's interjection: continue the stage's OWN opencode session by id
            # when we have it, else a fresh turn in the same workspace.
            row = await self.driver.run_turn(session_id, matter_ref, fname,
                                             f"User interjection: {text}",
                                             model=STAGE_MODEL)
            row.agent = agent
        return row

    # -- the M6 moot stage ------------------------------------------------------

    _MOOT_ATTACKERS = ("opposing-counsel", "procedural-examiner", "evidence-examiner")
    _MOOT_MAX_ROUNDS = 4
    _MOOT_CLEAN_ROUNDS = 2
    _MOOT_DOC = "filings-roadmap.md"

    async def _run_moot_stage(self, session_id: str, matter_ref: str, task: str,
                              stage: dict, prev_stage: str, prev_summary: str,
                              classification: str = "LOCAL_PREFERRED") -> TurnRow:
        """M6: the moot gate as a workflow stage (NEXT_STEPS §9 M6). Pre-pass the
        drafted deliverable with the mechanical moot_check, then run up to 4
        adversarial rounds — opposing-counsel, then procedural-examiner and
        evidence-examiner attack turns, the clerk revises against the open rows,
        re-check, keep-if-better compare. Two consecutive clean rounds -> a PASSED
        moot.verdict audit record; else CAPPED and the stage raises, so the D3
        halt fails the execution and no approval is ever requested. Works in
        both orchestration paths: it opens platform.db itself (the durable path
        reuses the same file the orchestrator parked against)."""
        import uuid as _uuid
        from harness.lifecycle import dossier
        from harness.moot import gate as moot_gate
        from harness.workflow import orchestrator
        from harness.workflow.db import connect

        store_root = Path(self.store.root) if self.store else Path(
            orchestrator.platform_db(Path(".")).parent)
        con = connect(orchestrator.platform_db(store_root))
        eid = None
        if self.store:
            row = con.execute(
                "SELECT execution_id FROM executions WHERE matter_id=? AND session_id=?"
                " ORDER BY started_at DESC LIMIT 1", (matter_ref, session_id)).fetchone()
            eid = row["execution_id"] if row else None
        run_id = f"moot-{matter_ref}-{_uuid.uuid4().hex[:8]}"
        try:
            ws = self.driver.workspace_for(
                session_id, f"{stage['agent']}-stage-{stage['stage']}", matter_ref,
                classification)
            doc = ws / self._MOOT_DOC
            store = None
            try:
                from harness.corpus import CorpusStore
                store = CorpusStore(Path(store_root) / "corpus.sqlite3")
            except Exception:                                  # noqa: BLE001
                store = None
            # pre-pass: the mechanical floor over the drafted document
            result = moot_gate.moot_check(con, matter_ref, str(doc), store=store)
            baseline = _sev_counts(result)
            # this run re-checks the document: earlier runs' rows are stale
            _supersede(con, matter_ref, f"F-moot-{matter_ref}-", f"re-checked by {run_id}")
            _ledger_append(con, matter_ref, result, run_id, round_no=0)
            clean = 0
            rounds = 0
            for rounds in range(1, self._MOOT_MAX_ROUNDS + 1):
                attacks: list[dict] = []
                for attacker in self._MOOT_ATTACKERS:
                    # the attacker's cwd is its own workspace; a read of the clerk's is
                    # refused (1.0.1 Windows test: most refused reads were moot's) — give
                    # it this round's draft in place
                    aws = self.driver.workspace_for(session_id, f"{attacker}-stage-moot",
                                                    matter_ref, classification)
                    if doc.is_file():
                        shutil.copy2(doc, aws / self._MOOT_DOC)
                    prompt = _stage_prompt(
                        stage=f"moot-{attacker}", agent=attacker,
                        instruction=(f"Attack {self._MOOT_DOC} (already in your workspace — "
                                     f"read it there, never from another directory) for "
                                     f"this ask: {task}. "
                                     f"Open flaw rows from the pre-pass and prior rounds: "
                                     f"{json.dumps(_open_rows(con, matter_ref))}. Write "
                                     f"your attacks as rows '[CRITICAL|MAJOR|MINOR] "
                                     f"<class>: <detail>' and reply with them."),
                        index=1, total=1, task=task,
                        previous_stage=prev_stage, previous_summary=prev_summary)
                    arow = await self.driver.run_turn(session_id, matter_ref,
                                                      f"{attacker}-stage-moot", prompt,
                                                      classification=classification,
                                                      model=STAGE_MODEL)
                    attacks.extend(_parse_attack_rows(arow.output_summary))
                # attackers saw the open rows and re-raise what still stands
                _supersede(con, matter_ref, f"F-{run_id}-a", f"not re-raised in round {rounds}")
                for j, a in enumerate(attacks):
                    dossier.append(con, matter_ref, "flaws", {
                        "flaw_id": f"F-{run_id}-a{rounds}-{j}", "class": a["class"],
                        "severity": a["severity"], "doc": self._MOOT_DOC,
                        "status": "open", "detector": "moot-round",
                        "detail": a["detail"]}, actor=attacker)
                # the clerk revises against the open rows
                revise_prompt = _stage_prompt(
                    stage="moot-revise", agent=stage["agent"],
                    instruction=(f"Revise {self._MOOT_DOC} for this ask: {task}, fixing "
                                 f"or answering every open CRITICAL/MAJOR row: "
                                 f"{json.dumps(_open_rows(con, matter_ref))}. Write the "
                                 f"revised file, then reply with its path and a two-line "
                                 f"summary."),
                    index=1, total=1, task=task, previous_stage=prev_stage,
                    previous_summary=prev_summary)
                rrow = await self.driver.run_turn(
                    session_id, matter_ref,
                    f"{stage['agent']}-stage-{stage['stage']}",
                    revise_prompt, classification=classification, model=STAGE_MODEL)
                result = moot_gate.moot_check(con, matter_ref, str(doc), store=store)
                cand = _sev_counts(result)
                _supersede(con, matter_ref, f"F-{run_id}-r", f"re-checked in round {rounds}")
                _ledger_append(con, matter_ref, result, run_id, round_no=rounds)
                cmp = moot_gate.compare(baseline, cand)
                if cmp["keep"]:
                    baseline = cand          # keep-if-better: the revision stands
                # a clean round = mechanical clean AND no open blocking agent row
                open_blocking = [r for r in _open_rows(con, matter_ref)
                                 if r["severity"] in ("critical", "material")]
                if result["ok"] and not open_blocking:
                    clean += 1
                else:
                    clean = 0
                if clean >= self._MOOT_CLEAN_ROUNDS:
                    break
            verdict = "PASSED" if clean >= self._MOOT_CLEAN_ROUNDS else "CAPPED"
            con.execute("BEGIN IMMEDIATE")
            moot_gate.record_verdict(con, matter_id=matter_ref,
                                     execution_id=eid or f"legacy-{session_id}",
                                     verdict=verdict, rounds=rounds, run_id=run_id,
                                     docs=[self._MOOT_DOC])
            con.execute("COMMIT")
            if verdict != "PASSED":
                raise RuntimeError(
                    f"moot gate CAPPED after {rounds} rounds — open blocking flaws "
                    f"remain ({json.dumps(_open_rows(con, matter_ref))}); a CAPPED "
                    f"draft never reaches approval")
            rrow.agent = stage["agent"]
            return rrow
        finally:
            con.close()

    async def _run_task_durable(self, session_id: str, matter_ref: str, task: str,
                                plan: StagePlan, *, classification: str,
                                session_digest: str) -> list[TurnRow]:
        """M4: the same run through the SQLite-lease orchestrator (D4). The
        stage body is the EXISTING _run_stage, unchanged; the orchestrator owns
        claiming, leases, crash recovery and approval parking. Returns the same
        list[TurnRow]; a parked run returns the rows completed so far."""
        from harness.workflow import orchestrator
        from harness.workflow.db import connect
        con = connect(orchestrator.platform_db(self.store.root))
        try:
            eid = orchestrator.create_execution(
                con, matter_id=matter_ref, session_id=session_id, task_text=task,
                stages=plan.stages)
            rows: list[TurnRow] = []

            async def body(task_row, prev_summary):
                stage = next(s for s in plan.stages if s["stage"] == task_row["key"])
                prev = con.execute(
                    "SELECT key FROM tasks WHERE execution_id=? AND seq<?"
                    " ORDER BY seq DESC LIMIT 1", (eid, task_row["seq"])).fetchone()
                if task_row["seq"] == 1:
                    prev_stage, prev_summary = "prior session", (session_digest or prev_summary)
                else:
                    prev_stage = prev["key"] if prev else ""
                row = await self._run_stage(session_id, matter_ref, task, stage,
                                            prev_stage, prev_summary,
                                            classification=classification)
                rows.append(row)
                register_deliverables(con, matter_ref, eid, stage, self.driver.workspace_for(
                    session_id, f"{stage['agent']}-stage-{stage['stage']}", matter_ref,
                    classification))
                return row.output_summary

            await orchestrator.run(con, eid, body, owner=orchestrator.new_owner())
            from harness.lifecycle import statemachine
            statemachine.advance_after_run(con, eid)
            return rows
        finally:
            con.close()
