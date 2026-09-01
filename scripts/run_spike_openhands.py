"""S4 spike driver — OpenHands candidate (SPIKE_PROTOCOL P0-5). SDK-only mount.

RUN UNDER THE OPENHANDS VENV (the SDK is not installed in harness-core's .venv):
  C:/Users/mianx/spike-ws/openhands-venv/Scripts/python.exe scripts/run_spike_openhands.py --smoke

Mounts (SPIKE_PROTOCOL: exactly two ports, no core fork):
  1. PERSONA — Agent(system_prompt=PERSONA_PORT["system_prompt"] verbatim — the SDK
     documents system_prompt as "this text verbatim instead of rendering from a
     template") + register_agent("hunter", ...) so the subagent MOUNT exists in the
     agent registry. NOTE: task-delegation (TaskToolSet) lives in `openhands-tools`,
     which does NOT install on this Windows box (Rust-building sdist; wheels-only
     ResolutionImpossible) — recorded in SEAM_COUNT as a blocked seam.
  2. GUARD — OpenHandsHandlerAdapter (guard_port.py) driven from a conversation
     callback on the event-append path: ObservationEvent (tool results) and
     MessageEvent (assistant output) get annotated in place. If events are immutable,
     that is a criterion-(a) FAIL datum for this candidate — recorded, not worked
     around by editing SDK source.

Runs on openhands-sdk 1.44.1 (pinned), local Ollama qwen3.8:27b, max_output_tokens 8192
(same cap as every other parity run). Modes mirror run_spike_opencode.py:
  default parity subset / --smoke introspection / --inject criterion-(a) coverage /
  --only/--limit/--all selection.

OpenHands LLM wiring is litellm-based: model "openai/<id>" + base_url routes to the
OpenAI-compatible endpoint (Ollama /v1)."""
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

WS = Path.home() / "spike-ws" / "openhands"
MODEL_ID = "qwen3.8:27b"
BASE_URL = "http://127.0.0.1:11434/v1"
MAX_OUTPUT_TOKENS = 8192
DEVIATION = ("DEVIATION (spike parity run, agent-recorded 2026-09-01): parity subset 5 cases "
             "(one per matter cluster, first by id); max_output_tokens 8192 identical to every "
             "other parity run; hunter driven directly (task-delegation seam blocked — see "
             "SEAM_COUNT); see the S4 spike report.")


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


def text_of(obj) -> str:
    """Best-effort text extraction from an event-ish object (attributes vary by event
    class; smoke mode dumps the real shapes and this is adjusted to observed reality)."""
    for attr in ("observation", "content", "text"):
        v = getattr(obj, attr, None)
        if isinstance(v, str):
            return v
    llm_message = getattr(obj, "llm_message", None)
    if llm_message is not None:
        content = getattr(llm_message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def annotate_event(obj, tag: str, log) -> None:
    """Run the real guard over the event's text and write the annotation back IN PLACE.
    Returns nothing; failures are logged (events may be immutable — that is a finding)."""
    payload = {"observation": text_of(obj), "allowed": read_allowed()["allowed"]}
    mutated = guard_annotate(payload)
    if mutated["observation"] != payload["observation"]:
        for attr in ("observation", "content", "text"):
            if isinstance(getattr(obj, attr, None), str):
                try:
                    setattr(obj, attr, mutated["observation"])
                    log({"tag": tag, "annotated": True, "path": attr})
                    return
                except Exception as ex:                  # noqa: BLE001 — immutable event = finding
                    log({"tag": tag, "annotated": False, "error": f"{type(ex).__name__}: {ex}"})
                    return
    llm_message = getattr(obj, "llm_message", None)
    if llm_message is not None:                          # MessageEvent: text lives in llm_message
        content = getattr(llm_message, "content", None)
        try:
            if isinstance(content, str):
                setattr(llm_message, "content", mutated["observation"])
                log({"tag": tag, "annotated": True, "path": "llm_message.content(str)"})
            elif isinstance(content, list):
                joined = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                if joined == payload["observation"] and mutated["observation"] != joined:
                    for p in content:
                        if isinstance(p, dict) and "text" in p:
                            p["text"] = mutated["observation"]
                            break
                    log({"tag": tag, "annotated": True, "path": "llm_message.content(list)"})
        except Exception as ex:                          # noqa: BLE001
            log({"tag": tag, "annotated": False, "error": f"{type(ex).__name__}: {ex}"})


class GuardLog:
    def __init__(self) -> None:
        WS.mkdir(parents=True, exist_ok=True)
        self.path = WS / "guard-log.jsonl"
        self.path.write_text("", encoding="utf-8")

    def __call__(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def build_llm():
    from openhands.sdk import LLM
    from pydantic import SecretStr
    kwargs = dict(model=f"openai/{MODEL_ID}", api_key=SecretStr("ollama"), base_url=BASE_URL,
                  max_output_tokens=MAX_OUTPUT_TOKENS, timeout=10_800)
    try:
        return LLM(**kwargs)
    except Exception:                                    # timeout unit/name may differ — retry bare
        kwargs.pop("timeout", None)
        return LLM(**kwargs)


def build_hunter(llm=None):
    """Persona port: registered 'hunter' subagent, system prompt VERBATIM, tools=[] so
    parity cases single-shot exactly like the in-house mount."""
    from openhands.sdk import Agent, Tool, register_agent
    llm = llm or build_llm()

    def factory(parent_llm=None):
        return Agent(llm=parent_llm or llm, tools=[], system_prompt=PERSONA_PORT["system_prompt"])

    try:
        register_agent(name="hunter", factory_func=factory,
                       description="NZ legal research specialist (spike port of @HUNTER)")
    except Exception as ex:                              # noqa: BLE001 — registry semantics may differ
        GuardLog()({"tag": "register_agent", "error": f"{type(ex).__name__}: {ex}"})
    return factory()


def run_conversation(agent, prompt: str, log) -> tuple[str, list]:
    """One conversation, guard callbacks attached. Returns (final assistant text, event dump)."""
    from openhands.sdk import Conversation
    dump: list = []

    def callback(event, *args):
        try:
            dump.append({"cls": type(event).__name__, "repr": repr(event)[:1200]})
        except Exception:                                # noqa: BLE001
            pass
        cls = type(event).__name__
        if cls in ("ObservationEvent", "MessageEvent"):
            annotate_event(event, cls, log)

    conv = Conversation(agent=agent, workspace=str(WS), callbacks=[callback])
    conv.send_message(prompt)
    conv.run()
    events = list(conv.get_events()) if hasattr(conv, "get_events") else []
    final = ""
    for ev in reversed(events):
        if type(ev).__name__ == "MessageEvent":
            final = text_of(ev)
            if final:
                break
    try:
        conv.close()
    except Exception:                                    # noqa: BLE001
        pass
    return final, dump


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
        import openhands
        print(f"[smoke] openhands sdk version: {getattr(openhands, '__version__', '?')}")
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from openhands.tools.task import TaskToolSet      # noqa: F401 — delegation seam probe
        print("[smoke] TaskToolSet: importable")
    except Exception as ex:                              # noqa: BLE001
        print(f"[smoke] TaskToolSet: NOT importable ({type(ex).__name__}: {ex})")
    log = GuardLog()
    write_allowed(WS, allowed=["Real Authority Act 1908"])
    agent = build_hunter()
    t0 = time.monotonic()
    final, dump = run_conversation(agent, "Reply with the single word OK.", log)
    (WS / "smoke-events.json").write_text(json.dumps(dump, indent=1, default=str),
                                          encoding="utf-8")
    print(f"[smoke] final={final!r} latency_ms={int((time.monotonic()-t0)*1000)}")
    print(f"[smoke] event dump -> {WS/'smoke-events.json'}")
    print(f"[smoke] guard log:\n{(WS / 'guard-log.jsonl').read_text(encoding='utf-8') or '(empty)'}")
    return 0 if final else 1


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
    try:
        for case in cases:
            failure, text, latency = "", "", 0
            write_allowed(WS, allowed=case.expected_citations)
            t0 = time.monotonic()
            try:
                text, _dump = run_conversation(agent, case.prompt, log)
                latency = int((time.monotonic() - t0) * 1000)
                (WS / "transcripts").mkdir(parents=True, exist_ok=True)
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
    p.add_argument("--only", action="append", default=[], metavar="ID-SUBSTR")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--all", action="store_true")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--inject", action="store_true")
    return p.parse_args()


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    if args.smoke:
        sys.exit(smoke())
    if args.inject:
        sys.exit("TODO after smoke reveals event/tool shapes: criterion-(a) injection run")
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
