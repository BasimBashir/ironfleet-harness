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

import re
from dataclasses import dataclass, field
from pathlib import Path

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


def fallback_plan(intent: str, complexity: str, task: str) -> StagePlan:
    """SupervisorRoutes.resolve() (hybrid's fallback). Each resolved persona
    becomes a stage; the instruction names the task and the previous stage's
    artifact, so the chain has somewhere to stand even when no model planned it."""
    data = Path(__file__).resolve().parents[3] / "data" / "module-e" / "supervisor.yaml"
    agents = load_routes(data).resolve(intent, complexity)
    stages = []
    for i, agent in enumerate(agents, start=1):
        stages.append({"stage": f"stage-{i}", "agent": agent,
                       "instruction": f"Contribute to: {task}",
                       "prompt": _stage_prompt(stage=f"stage-{i}", instruction=task,
                                               agent=agent, index=i, total=len(agents))})
    return StagePlan(stages=stages, source="routes")


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
                       classification: str = "LOCAL_PREFERRED") -> list[TurnRow]:
        """Resolve the plan, then run its stages IN ORDER, each in its own
        workspace, handing the previous stage's summary forward in the prompt."""
        plan = self.plan(task, plan_text, intent=intent, complexity=complexity)
        rows: list[TurnRow] = []
        prev_stage = prev_summary = ""
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
        sync (F5/P7), then one turn whose prompt carries the previous summary."""
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
        (ws / ".opencode" / "agent").mkdir(parents=True, exist_ok=True)
        (ws / ".opencode" / "agent" / f"{fname}.md").write_text(
            stage_agent_md(stage["stage"], instruction), encoding="utf-8")
        prompt = _stage_prompt(stage=stage["stage"], instruction=instruction, agent=agent,
                               index=1, total=1, task=task, previous_stage=prev_stage,
                               previous_summary=prev_summary)
        row = await self.driver.run_turn(session_id, matter_ref, fname, prompt,
                                         classification=classification,
                                         model=STAGE_MODEL)
        # The row records WHO ran (the persona), not the generated stage-file stem
        # the spawn needed: the JSONL row and the acceptance checks read `agent`
        # by name, and "hunter-stage-gather" is an implementation detail.
        row.agent = agent
        for text in self._drain_injections(agent):
            # P7's interjection: continue the stage's OWN opencode session by id
            # when we have it, else a fresh turn in the same workspace.
            row = await self.driver.run_turn(session_id, matter_ref, fname,
                                             f"User interjection: {text}",
                                             model=STAGE_MODEL)
            row.agent = agent
        return row
