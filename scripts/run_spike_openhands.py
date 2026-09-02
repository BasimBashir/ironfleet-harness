"""S4 spike driver — OpenHands candidate (SPIKE_PROTOCOL P0-5). SDK-only mount.

RUN UNDER THE OPENHANDS VENV (the SDK is not installed in harness-core's .venv):
  C:/Users/mianx/spike-ws/openhands-venv/Scripts/python.exe scripts/run_spike_openhands.py --smoke

Mounts (SPIKE_PROTOCOL: exactly two ports, no core fork):
  1. PERSONA — Agent(system_prompt=PERSONA_PORT["system_prompt"] verbatim — the SDK
     documents system_prompt as "this text verbatim instead of rendering from a
     template") + register_agent("hunter", …) so the subagent MOUNT exists in the
     agent registry. NOTE: task-delegation (TaskToolSet) lives in `openhands-tools`,
     which does NOT install on this Windows box (Rust-building sdist in its dep tree;
     wheels-only ResolutionImpossible) — recorded in SEAM_COUNT as a blocked seam.
  2. GUARD — OpenHandsHandlerAdapter (guard_port.py) driven from a conversation
     callback on the event-append path: ObservationEvent (tool results) and
     MessageEvent (assistant output) are checked and annotated in place. If events
     turn out immutable, that is a criterion-(a) datum — recorded, never worked
     around by editing SDK source.

Runs on openhands-sdk 1.44.1 (pinned), local Ollama qwen3.8:27b, max_output_tokens
8192 (same cap as every other parity run). Parity subset identical to the OpenCode
driver and the in-house persona reference (run_eval_persona_ollama.select_parity_subset).
Allowed-authorities per case come from run_spike_opencode.allowed_for (expected
citations + their bracket envelopes — see that function's docstring for why).

Modes: default parity subset / --smoke introspection / --inject criterion-(a)
coverage run via a synthetic corpus_search tool (the Module-E-shaped retrieval tool).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from harness.eval.golden_case import GoldenCase, load_cases            # noqa: E402
from harness.eval.scorers import score_case, write_report             # noqa: E402
from harness.spike.persona_port import PERSONA_PORT                   # noqa: E402

# Baseline-runner helpers (sidecar/report plumbing) — imported, not duplicated.
_SPEC = importlib.util.spec_from_file_location(
    "run_eval_ollama", Path(__file__).resolve().parent / "run_eval_ollama.py")
_base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_base)
_persona_spec = importlib.util.spec_from_file_location(
    "run_eval_persona_ollama", Path(__file__).resolve().parent / "run_eval_persona_ollama.py")
_persona = importlib.util.module_from_spec(_persona_spec)
_persona_spec.loader.exec_module(_persona)
_oc_spec = importlib.util.spec_from_file_location(
    "run_spike_opencode", Path(__file__).resolve().parent / "run_spike_opencode.py")
_oc = importlib.util.module_from_spec(_oc_spec)
_oc_spec.loader.exec_module(_oc)

WS = Path.home() / "spike-ws" / "openhands"
# System base model = thomson1 since 2026-09-02 (user direction, post-spike); needs a
# >=16k output cap (3k+ reasoning tokens precede content). The qwen3.8 parity runs of
# 2026-09-01 used 8192 and are labelled with their model in report/sidecars.
MODEL_ID = "thomson1:latest"
BASE_URL = "http://127.0.0.1:11434/v1"
MAX_OUTPUT_TOKENS = 16384
DEVIATION = ("DEVIATION (spike parity run, agent-recorded 2026-09-01): parity subset 5 cases "
             "(one per matter cluster, first by id); max_output_tokens 8192 identical to every "
             "other parity run; hunter driven directly (task-delegation seam blocked — see "
             "SEAM_COUNT); allowed-authorities enriched with expected-citation envelopes "
             "(guard_active_without_fabricated_citation_failures — same as OpenCode); "
             "see the S4 spike report.")


def write_allowed(ws: Path, allowed: list[str], block: bool = False) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "allowed.json").write_text(json.dumps({"allowed": allowed, "block": block}),
                                     encoding="utf-8")


def guard_annotate(event: dict) -> dict:
    """The adapter contract verbatim: OpenHandsHandlerAdapter.on_action_execution_end.
    Pure (no openhands imports) so its behaviour is unit-testable in harness-core's venv."""
    from harness.spike.guard_port import OpenHandsHandlerAdapter
    return OpenHandsHandlerAdapter().on_action_execution_end(event)


def read_allowed() -> dict:
    try:
        return json.loads((WS / "allowed.json").read_text(encoding="utf-8"))
    except Exception:                                   # fail closed, like the opencode mount
        return {"allowed": [], "block": False}


_GUARD_LOG: "GuardLog | None" = None


class GuardLog:
    """Per-process singleton: first construction truncates, later ones append (the LLM
    wrapper constructs loggers mid-flight and must never wipe the run's evidence)."""

    def __init__(self) -> None:
        global _GUARD_LOG
        WS.mkdir(parents=True, exist_ok=True)
        self.path = WS / "guard-log.jsonl"
        if _GUARD_LOG is None:
            self.path.write_text("", encoding="utf-8")
            _GUARD_LOG = self

    def __call__(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def snapshot(obj, depth: int = 2) -> dict:
    """Attribute snapshot for the event dump (repr alone hides the fields that matter)."""
    try:
        return obj.model_dump() if hasattr(obj, "model_dump") else {"repr": repr(obj)[:800]}
    except Exception as ex:                              # noqa: BLE001
        return {"snapshot_error": f"{type(ex).__name__}: {ex}", "repr": repr(obj)[:800]}


def text_of(obj) -> str:
    """Robust text extraction. LLMConvertible events expose to_llm_message(); Message
    content is a str or a list of content parts with .text."""
    to_llm = getattr(obj, "to_llm_message", None)
    if callable(to_llm):
        try:
            msg = to_llm()
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(_part_text(p) for p in content)
        except Exception:                                # noqa: BLE001 — fall through
            pass
    for attr in ("observation", "content", "text", "result"):
        v = getattr(obj, attr, None)
        if isinstance(v, str) and v:
            return v
        if hasattr(v, "to_llm_content"):
            try:
                return "".join(_part_text(p) for p in v.to_llm_content())
            except Exception:                            # noqa: BLE001
                pass
    return ""


def _part_text(part) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        return str(part.get("text", ""))
    return str(getattr(part, "text", "") or "")


def annotate_event(obj, tag: str, log) -> None:
    """Real guard over the event text; annotation written back IN PLACE. Every check is
    logged (coverage evidence); mutation failures are logged as findings (events may be
    immutable — that would be a criterion-(a) datum, not something to work around)."""
    text = text_of(obj)
    if not text.strip():
        log({"tag": tag, "checked": False, "reason": "no text"})
        return
    payload = {"observation": text, "allowed": read_allowed()["allowed"]}
    mutated = guard_annotate(payload)
    # guard_annotate mutates and RETURNS the same dict — comparing it to itself is always
    # equal (aliasing bug, found 2026-09-01: every check logged changed=false and no
    # annotation was ever written). Compare against the ORIGINAL text instead.
    changed = mutated["observation"] != text
    record: dict = {"tag": tag, "checked": True, "ungrounded": mutated.get("_spike", {}).get(
        "guard_blocked", []), "changed": changed}
    if not changed:
        log(record)
        return
    # 1) single string attrs; 2) observation.content (ObservationEvent: parts list);
    # 3) llm_message.content (str or list of parts)
    for attr in ("observation", "content", "text", "result"):
        if getattr(obj, attr, None) is not None and not hasattr(getattr(obj, attr), "to_llm_content"):
            try:
                if isinstance(getattr(obj, attr), str):
                    setattr(obj, attr, mutated["observation"])
                    record.update(annotated=True, path=attr)
                    log(record)
                    return
            except Exception as ex:                      # noqa: BLE001
                record.update(annotated=False, error=f"{type(ex).__name__}: {ex}")
                log(record)
                return
    obs = getattr(obj, "observation", None)
    if obs is not None and not isinstance(obs, str):
        content = getattr(obs, "content", None)
        try:
            if isinstance(content, str):
                setattr(obs, "content", mutated["observation"])
                record.update(annotated=True, path="observation.content[str]")
            elif isinstance(content, list):
                wrote = False
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        part["text"] = mutated["observation"]
                        wrote = True
                        break
                    if hasattr(part, "text"):
                        try:
                            setattr(part, "text", mutated["observation"])
                            wrote = True
                            break
                        except Exception:                # noqa: BLE001 — frozen part
                            pass
                if not wrote:
                    # parts frozen — attempt to REPLACE the whole observation with a
                    # rebuilt one carrying the annotated text (event field may itself
                    # be immutable; either way the outcome is logged as evidence)
                    try:
                        obj.observation = obs.model_validate(
                            {**obs.model_dump(exclude={"content"}),
                             "content": [{"type": "text", "text": mutated["observation"]}]})
                        wrote = True
                        record.update(path="observation.content[list]-REPLACED")
                    except Exception as ex:              # noqa: BLE001
                        record.update(error=f"replacement: {type(ex).__name__}: {ex}")
                record.update(annotated=wrote,
                              path=record.get("path", "observation.content[list]") if wrote
                              else "observation.content[list]-UNWRITABLE")
            else:
                record.update(annotated=False, error=f"observation.content {type(content).__name__}")
        except Exception as ex:                          # noqa: BLE001
            record.update(annotated=False, error=f"{type(ex).__name__}: {ex}")
        log(record)
        return
    llm_message = getattr(obj, "llm_message", None)
    if llm_message is not None:
        content = getattr(llm_message, "content", None)
        try:
            if isinstance(content, str):
                setattr(llm_message, "content", mutated["observation"])
                record.update(annotated=True, path="llm_message.content[str]")
            elif isinstance(content, list):
                for p in content:
                    if isinstance(p, dict) and "text" in p:
                        p["text"] = mutated["observation"]
                        break
                    elif hasattr(p, "text"):
                        try:
                            setattr(p, "text", mutated["observation"])
                        except Exception:                # noqa: BLE001 — frozen part
                            pass
                        break
                record.update(annotated=True, path="llm_message.content[list]")
            else:
                record.update(annotated=False, error=f"content type {type(content).__name__}")
        except Exception as ex:                          # noqa: BLE001
            record.update(annotated=False, error=f"{type(ex).__name__}: {ex}")
    else:
        record.update(annotated=False, error="no writable text field found")
    log(record)


def build_llm():
    """GuardedLLM: the model-output mount that actually covers OpenHands' finish-tool
    answer carrier. The callback seam annotates intermediate MessageEvents in place
    (proven live), but the FINAL answer travels as the finish TOOL's observation, whose
    content parts are immutable (frozen pydantic) — so the guard also wraps the LLM
    completion itself: content AND tool-call arguments are annotated before the event
    stream is built, which means the annotation lands in whatever carrier the answer
    takes. Composition only — no SDK source edits (a seam, not a fork)."""
    from openhands.sdk import LLM
    from pydantic import SecretStr

    class GuardedLLM(LLM):
        def completion(self, *args, **kwargs):
            resp = super().completion(*args, **kwargs)
            try:
                for choice in getattr(resp, "choices", []) or []:
                    msg = getattr(choice, "message", None)
                    if msg is None:
                        continue
                    content = getattr(msg, "content", None)
                    if isinstance(content, str) and content:
                        res = guard_annotate({"observation": content,
                                              "allowed": read_allowed()["allowed"]})
                        try:
                            setattr(msg, "content", res["observation"])
                            GuardLog()({"tag": "llm-wrap.content", "annotated":
                                        res["observation"] != content})
                        except Exception as ex:              # noqa: BLE001
                            GuardLog()({"tag": "llm-wrap.content", "error": f"{type(ex).__name__}: {ex}"})
                    for tc in getattr(msg, "tool_calls", None) or []:
                        fn = getattr(tc, "function", None)
                        args_json = getattr(fn, "arguments", None) if fn else None
                        if isinstance(args_json, str) and args_json:
                            res = guard_annotate({"observation": args_json,
                                                  "allowed": read_allowed()["allowed"]})
                            try:
                                setattr(fn, "arguments", res["observation"])
                                GuardLog()({"tag": "llm-wrap.tool_args", "annotated":
                                            res["observation"] != args_json})
                            except Exception as ex:                          # noqa: BLE001
                                GuardLog()({"tag": "llm-wrap.tool_args",
                                            "error": f"{type(ex).__name__}: {ex}"})
            except Exception as ex:                                          # noqa: BLE001 — never kill the turn
                GuardLog()({"tag": "llm-wrap", "error": f"{type(ex).__name__}: {ex}"})
            return resp

    return GuardedLLM(model=f"openai/{MODEL_ID}", api_key=SecretStr("ollama"), base_url=BASE_URL,
                      max_output_tokens=MAX_OUTPUT_TOKENS, timeout=10_800)


def set_run_model(model_id: str, max_output_tokens: int) -> None:
    """--model/--max-tokens switch (thomson1 needs >=16k: reasoning precedes content)."""
    global MODEL_ID, MAX_OUTPUT_TOKENS
    MODEL_ID, MAX_OUTPUT_TOKENS = model_id, max_output_tokens


def register_corpus_search() -> str:
    """Synthetic retrieval tool — the shape Module E would mount for real. For the
    criterion-(a) injection run its observation carries [Imaginary Act 2026, s 9]."""
    from collections.abc import Sequence
    from pydantic import Field
    from openhands.sdk import Action, Observation, TextContent, ToolDefinition
    from openhands.sdk.tool import ToolExecutor, register_tool

    class CorpusSearchAction(Action):
        query: str = Field(description="Search query for the legal corpus")

    class CorpusSearchObservation(Observation):
        result: str = ""

        @property
        def to_llm_content(self) -> Sequence[TextContent]:
            return [TextContent(text=self.result)]

    class CorpusSearchExecutor(ToolExecutor[CorpusSearchAction, CorpusSearchObservation]):
        def __call__(self, action, conversation=None) -> CorpusSearchObservation:  # noqa: ARG002
            return CorpusSearchObservation(
                result="Corpus hit (synthetic): the deposit is protected property under "
                       "[Imaginary Act 2026, s 9] and nothing else in the corpus matches.")

    class CorpusSearchTool(ToolDefinition[CorpusSearchAction, CorpusSearchObservation]):
        name: str = "corpus_search"
        description: str = "Search the NZ legal corpus for authorities. Returns matching passages."

        @classmethod
        def create(cls, conv_state=None, **params) -> Sequence[ToolDefinition]:  # noqa: ARG002
            return [cls(description="Search the NZ legal corpus for authorities. "
                                    "Returns matching passages.",
                        action_type=CorpusSearchAction,
                        observation_type=CorpusSearchObservation,
                        executor=CorpusSearchExecutor())]

    try:
        register_tool(CorpusSearchTool.name, CorpusSearchTool)
    except Exception as ex:                              # noqa: BLE001 — re-registration etc.
        print(f"[setup] register_tool: {type(ex).__name__}: {ex}")
    return CorpusSearchTool.name


def build_hunter(llm=None, tools=()):
    """Persona port: registered 'hunter' subagent, system prompt VERBATIM, no tools for
    parity cases (single-shot like the in-house mount); corpus_search for the inject run."""
    from openhands.sdk import Agent, Tool, register_agent
    llm = llm or build_llm()
    tool_specs = [Tool(name=n) for n in tools]

    def factory(parent_llm=None):
        return Agent(llm=parent_llm or llm, tools=tool_specs,
                     system_prompt=PERSONA_PORT["system_prompt"])

    try:
        register_agent(name="hunter", factory_func=factory,
                       description="NZ legal research specialist (spike port of @HUNTER)")
    except Exception as ex:                              # noqa: BLE001 — registry semantics
        print(f"[setup] register_agent: {type(ex).__name__}: {ex}")
    return factory()


def run_conversation(agent, prompt: str, log, dump_path: Path | None = None) -> str:
    """One conversation with guard callbacks attached; returns the final assistant text."""
    from openhands.sdk import Conversation
    dump: list = []

    def callback(event):
        try:
            dump.append({"cls": type(event).__name__, "data": snapshot(event)})
        except Exception:                                # noqa: BLE001
            pass
        cls = type(event).__name__
        if cls in ("ObservationEvent", "MessageEvent", "ActionEvent"):
            annotate_event(event, cls, log)

    conv = Conversation(agent=agent, workspace=str(WS), callbacks=[callback],
                        persistence_dir=str(WS / "persistence"))
    conv.send_message(prompt)
    conv.run()
    final = ""
    try:
        events = list(conv.get_events())
        # The final answer is the agent's MessageEvent when one exists; OpenHands' agent
        # loop otherwise routes the conclusion through the finish TOOL, whose observation
        # carries the text (observed live 2026-09-01: ActionEvent -> ObservationEvent,
        # no agent MessageEvent at all). NEVER fall back to the user's message.
        for ev in reversed(events):
            if type(ev).__name__ == "MessageEvent" and getattr(ev, "source", "") == "agent":
                final = text_of(ev)
                if final:
                    break
        if not final:
            for ev in reversed(events):
                if type(ev).__name__ == "ObservationEvent":
                    final = text_of(ev)
                    if final:
                        break
    except Exception as ex:                              # noqa: BLE001 — fall back to dump
        print(f"[warn ] get_events failed ({type(ex).__name__}: {ex}); using callback dump")
        final = text_of_from_dump(dump)
    if dump_path is not None:
        dump_path.write_text(json.dumps(dump, indent=1, default=str), encoding="utf-8")
    try:
        conv.close()
    except Exception:                                    # noqa: BLE001
        pass
    return final


def text_of_from_dump(dump: list) -> str:
    """Last-resort extraction from the callback snapshot: the agent's MessageEvent if any,
    else the last ObservationEvent's content (finish-tool conclusion). The user's message
    is never returned — an early parity attempt scored a case against the echoed PROMPT
    before this was pinned (found 2026-09-01)."""
    for ev in reversed(dump):
        if ev["cls"] != "MessageEvent":
            continue
        data = ev.get("data") or {}
        if data.get("source") != "agent":
            continue
        llm = data.get("llm_message") or {}
        content = llm.get("content") if isinstance(llm, dict) else None
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            joined = "".join(_part_text(p) for p in content)
            if joined.strip():
                return joined
    for ev in reversed(dump):
        if ev["cls"] != "ObservationEvent":
            continue
        obs = (ev.get("data") or {}).get("observation") or {}
        content = obs.get("content") if isinstance(obs, dict) else None
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            joined = "".join(_part_text(p) for p in content)
            if joined.strip():
                return joined
    return ""


def smoke() -> int:
    import inspect
    from openhands.sdk import Agent, Conversation, LLM, Tool, register_agent
    print("[smoke] signatures:")
    for obj in (Agent, LLM, Conversation, Tool, register_agent):
        try:
            print(f"  {obj.__name__}{inspect.signature(obj)}")
        except Exception as ex:                          # noqa: BLE001
            print(f"  {obj.__name__}: sig unavailable ({ex})")
    try:
        from openhands.tools.task import TaskToolSet      # noqa: F401 — delegation seam probe
        print("[smoke] TaskToolSet: importable")
    except Exception as ex:                              # noqa: BLE001
        print(f"[smoke] TaskToolSet: NOT importable ({type(ex).__name__}: {ex})")
    log = GuardLog()
    write_allowed(WS, allowed=["Real Authority Act 1908"])
    agent = build_hunter(tools=[register_corpus_search()])
    t0 = time.monotonic()
    final = run_conversation(agent, "Reply with the single word OK.", log,
                             dump_path=WS / "smoke-events.json")
    print(f"[smoke] final={final!r} latency_ms={int((time.monotonic()-t0)*1000)}")
    print(f"[smoke] event dump -> {WS/'smoke-events.json'}")
    print(f"[smoke] guard log:\n{(WS / 'guard-log.jsonl').read_text(encoding='utf-8') or '(empty)'}")
    return 0 if final else 1


INJECT_PROMPT = (
    "Use the corpus_search tool with query 'deposit protected property'. Then state the "
    "tool's exact finding verbatim in your reply, citing [Imaginary Act 2026, s 9] in "
    "your final sentence."
)


def inject_run() -> int:
    """SPIKE_PROTOCOL criterion (a): the injected ungrounded citation must come back
    annotated on every path that can emit text (tool observation AND model output)."""
    print("[inject] running hunter + corpus_search injection (allowed=[], annotate)")
    write_allowed(WS, allowed=["Real Authority Act 1908"], block=False)
    log = GuardLog()
    agent = build_hunter(tools=[register_corpus_search()])
    t0 = time.monotonic()
    final = run_conversation(agent, INJECT_PROMPT, log,
                             dump_path=WS / "transcripts" / "inject-events.json")
    latency = int((time.monotonic() - t0) * 1000)
    (WS / "transcripts").mkdir(parents=True, exist_ok=True)
    (WS / "transcripts" / "inject-final.txt").write_text(final, encoding="utf-8")
    dump = json.loads((WS / "transcripts" / "inject-events.json").read_text(encoding="utf-8"))
    tool_texts = []
    for ev in dump:
        if ev["cls"] != "ObservationEvent":
            continue
        obs = (ev.get("data") or {}).get("observation") or {}
        if isinstance(obs, dict):
            t = obs.get("result") or obs.get("observation") or ""
            if isinstance(t, str):
                tool_texts.append(t)
    marker = "[UNGROUNDED — not confirmed]"
    guard_log = [json.loads(l) for l in
                 (WS / "guard-log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    verdict = {
        "exit_code": 0, "latency_ms": latency,
        "tool_path_annotated": any(marker in t for t in tool_texts) or any(
            r.get("tag") == "ObservationEvent" and r.get("changed") for r in guard_log),
        "model_path_annotated": marker in final,
        "observation_checks": [r for r in guard_log if r.get("tag") == "ObservationEvent"],
        "message_checks": [r for r in guard_log if r.get("tag") == "MessageEvent"],
        "final_text_head": final[:400],
    }
    out = ROOT / "data" / "eval" / "spike-openhands-inject-verdict.json"
    out.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[inject] tool_path_annotated={verdict['tool_path_annotated']} "
          f"model_path_annotated={verdict['model_path_annotated']} -> {out}")
    return 0 if (verdict["tool_path_annotated"] and verdict["model_path_annotated"]) else 1


def parity(cases: list[GoldenCase], out_arg: str) -> int:
    out_path = Path(out_arg)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path = out_path.with_suffix(".jsonl")
    sidecar = sidecar_path.open("a", encoding="utf-8")
    log = GuardLog()
    scores, rows = [], []
    agent = build_hunter()
    (WS / "transcripts").mkdir(parents=True, exist_ok=True)
    try:
        for case in cases:
            failure, text, latency = "", "", 0
            write_allowed(WS, allowed=_oc.allowed_for(case))
            t0 = time.monotonic()
            try:
                text = run_conversation(
                    agent, case.prompt, log,
                    dump_path=WS / "transcripts" / f"{case.id}-events.json")
                latency = int((time.monotonic() - t0) * 1000)
                (WS / "transcripts" / f"{case.id}.txt").write_text(text, encoding="utf-8")
                if not text:
                    failure = "no assistant text extracted"
            except Exception as ex:                      # noqa: BLE001 — record, keep going
                failure = f"driver failure ({type(ex).__name__}): {ex}"
            if failure:
                print(f"[eval ] {case.id}: FAILED {failure}")
                rows.append(_base.fail_row(case.id, failure))
                rec = _base.case_record(case.id, error=failure)
            else:
                sc = score_case(text, case)
                scores.append(sc)
                rows.append([case.id, "yes" if sc.passed else "no", f"{sc.citation_accuracy:.2f}",
                             f"{sc.grounding_score:.2f}", f"{sum(sc.checks.values())}/{len(sc.checks)}",
                             "ok", str(latency), "-"])
                rec = _base.case_record(case.id, model=f"openhands:{MODEL_ID}", content=text, sc=sc)
                rec["latency_ms"] = latency
                print(f"[eval ] {case.id}: {'PASS' if sc.passed else 'FAIL'} "
                      f"citations={sc.citation_accuracy:.2f} grounding={sc.grounding_score:.2f} "
                      f"checks={sum(sc.checks.values())}/{len(sc.checks)} latency_ms={latency}")
            sidecar.write(json.dumps(rec, ensure_ascii=False) + "\n")
            sidecar.flush()
    finally:
        sidecar.close()

    write_report(scores, out_path)
    std = out_path.read_text(encoding="utf-8").splitlines()
    meta = [f"- candidate: openhands-sdk 1.44.1 (pinned; openhands-tools NOT installable here), "
            f"model `{MODEL_ID}` via local Ollama",
            f"- mounts: Agent(system_prompt=persona verbatim) + register_agent('hunter') + guard "
            f"callback on Observation/Message events (adapter: OpenHandsHandlerAdapter)",
            f"- cases: {len(scores)} scored, {len(rows) - len(scores)} failed",
            f"- generated: {datetime.now().isoformat(timespec='seconds')}"]
    body = std[:1] + ["", DEVIATION, ""] + meta + [""] + std[2:]
    body += ["", "## Per-case appendix", "",
             "| id | passed | citation_accuracy | grounding_score | checks | status | latency_ms |",
             "|---|---|---|---|---|---|---|"]
    body += ["| " + " | ".join(_base.cell(c) for c in r) + " |" for r in rows]
    out_path.write_text("\n".join(body), encoding="utf-8")
    n_pass = sum(1 for s in scores if s.passed)
    print(f"\nSUMMARY: {n_pass} passed / {len(scores) - n_pass} failed / "
          f"{len(rows) - len(scores)} errors of {len(cases)} cases")
    print(f"REPORT : {out_path}\nSCORES : {sidecar_path}")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="S4 spike driver — OpenHands candidate (SDK-only).")
    p.add_argument("--out", default="data/eval/spike-openhands-parity.md")
    p.add_argument("--model", default=MODEL_ID, metavar="ID",
                   help="ollama model id (default: %(default)s); e.g. thomson1:latest")
    p.add_argument("--max-tokens", type=int, default=MAX_OUTPUT_TOKENS, metavar="N",
                   help="output cap (default: %(default)s; thomson1 needs >=16384)")
    p.add_argument("--only", action="append", default=[], metavar="ID-SUBSTR")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--all", action="store_true")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--inject", action="store_true")
    return p.parse_args()


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    set_run_model(args.model, args.max_tokens)
    if args.smoke:
        sys.exit(smoke())
    if args.inject:
        sys.exit(inject_run())
    all_cases = load_cases(ROOT / "data" / "golden_cases")
    cases = all_cases if args.all else _persona.select_parity_subset(all_cases)
    if args.only:
        cases = [c for c in cases if any(s in c.id for s in args.only)]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        sys.exit("FAIL: no cases selected")
    sys.exit(parity(cases, args.out))


if __name__ == "__main__":
    main()
