"""S4 spike driver — OpenCode candidate (SPIKE_PROTOCOL P0-5).

Mounts (source of truth committed in src/harness/spike/candidates/opencode/, synced by
this driver into an ISOLATED workspace outside the repo so OpenCode's project detection
cannot see harness-core):
  1. GUARD  — .opencode/plugins/ironfleet-guard.ts calling the REAL guard through
     src/harness/module_e/guard_cli.py (OpenCodeHookAdapter; annotate mode for parity runs,
     block demonstrable on the tool path). Zero commits to opencode's own repo.
  2. PERSONA — .opencode/agent/hunter.md, body = PERSONA_PORT["system_prompt"] VERBATIM
     (generated from the module, never hand-copied), mode: subagent per the port fragment.

Modes:
  default        run the 5-case parity subset through `opencode run --agent hunter`,
                 score with the production scorer (score_case), sidecar like the baseline
  --smoke        one trivial run to inspect raw event shapes / plugin load behaviour
  --inject       criterion (a): ungrounded citation must be annotated on every emitting
                 path (tool result + model output); writes a verdict JSON
  --delegate     one case via the primary agent TASKING the hunter subagent (seam evidence
                 for the subagent-invocation path)

Usage:
  .venv/Scripts/python.exe scripts/run_spike_opencode.py --smoke
  .venv/Scripts/python.exe scripts/run_spike_opencode.py
  .venv/Scripts/python.exe scripts/run_spike_opencode.py --inject
  .venv/Scripts/python.exe scripts/run_spike_opencode.py --delegate --only gc-ppsa-001
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.eval.golden_case import GoldenCase, load_cases            # noqa: E402
from harness.eval.scorers import score_case, write_report             # noqa: E402
from harness.module_e.guard import guard_dir                           # noqa: E402
from harness.spike.persona_port import PERSONA_PORT                    # noqa: E402
# M3: the run primitives moved to harness.substrate.run (production home); re-exported
# here so the ~20 scripts/tests that import them from this module keep working.
from harness.substrate.run import (                                   # noqa: E402,F401
    RUN_TIMEOUT_S, opencode_cmd, run_opencode, flatten_prompt,
    parse_events, extract_final_text, extract_tool_texts)

# Baseline-runner helpers (sidecar/report plumbing) — imported, not duplicated.
_SPEC = importlib.util.spec_from_file_location(
    "run_eval_ollama", Path(__file__).resolve().parent / "run_eval_ollama.py")
_base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_base)
_persona_spec = importlib.util.spec_from_file_location(
    "run_eval_persona_ollama", Path(__file__).resolve().parent / "run_eval_persona_ollama.py")
_persona = importlib.util.module_from_spec(_persona_spec)
_persona_spec.loader.exec_module(_persona)

ROOT = Path(__file__).resolve().parents[1]
MOUNTS = ROOT / "src" / "harness" / "spike" / "candidates" / "opencode"
# Workspace OUTSIDE the IronFleet tree: opencode groups sibling git repos under one parent
# into a multi-instance "project" and the run session can attach the WRONG instance
# (observed 2026-09-01: session directory=harness-core despite cwd=spike-ws). Under
# ~ there are no sibling repos to adopt; ws is its own git repo regardless (isolation seam).
DEFAULT_WS = Path.home() / "spike-ws" / "opencode"
# NOT "ollama/..." as provider prefix — collides with opencode's builtin cloud provider.
# System base model = thomson1 since 2026-09-02 (user direction, post-spike); the qwen3.8
# parity runs of 2026-09-01 predate the switch and are labelled with their model in report/sidecars.
DEFAULT_MODEL_ID = "thomson1:latest"
MODEL = f"ollama-local/{DEFAULT_MODEL_ID}"          # re-derived when --model is passed
DEVIATION = ("DEVIATION (spike parity run, agent-recorded 2026-09-01): parity subset 5 cases "
             "(one per matter cluster, first by id); in-house cap 8192, opencode limit.output "
             "RAISED to 16384 after live measurement showed opencode injects ~8k tokens of "
             "request scaffolding regardless of the custom agent prompt (input 9279 vs 1104 "
             "in-house), inflating the model's thinking past the shared 8192 cap so cases "
             "ended reason=length with NO content emitted; temperature NOT pinned — see the "
             "S4 spike report for both the scaffolding tax and the cap accommodation.")


def render_guard_plugin(template: str, ws: str, python: str, guard_cli: str) -> str:
    gd = str(guard_dir(Path(ws))).replace("\\", "/")
    return (template.replace("__SPIKE_WS__", ws.replace("\\", "/"))
                    .replace("__PYTHON__", python.replace("\\", "/"))
                    .replace("__GUARD_CLI__", guard_cli.replace("\\", "/"))
                    .replace("__GUARD_DIR__", gd))


def hunter_agent_md(persona: str, model: str, mode: str = "subagent") -> str:
    """hunter agent file per PERSONA_PORT['configs']['opencode']: frontmatter + persona verbatim.
    ZERO tools for parity cases: the in-house comparator mounts the persona on a plain chat
    call, and any enabled tool (read/glob/grep/task/…) makes the model behave agentively
    instead of answering — observed live 2026-09-01 ('let me pull the exact statutory
    text', 131-char non-answer). The persona fragment's corpus tools are exercised by the
    injection/delegate runs instead. Temperature deliberately NOT pinned: the in-house
    gate sends no temperature field (server default applies).

    mode=subagent is the protocol's MOUNT (delegate run drives it via the task tool);
    mode=primary is the parity DRIVE twin — `opencode run --agent <subagent>` wraps a
    default primary around the subagent which then flails with its own tools (observed
    live: 'Web results are being garbled…'), so parity cases drive a primary-mode agent
    carrying the IDENTICAL verbatim persona."""
    return ( "---\n"
             f"description: NZ legal research specialist (spike port of @HUNTER)\n"
             f"mode: {mode}\n"
             f"model: {model}\n"
             "tools:\n"
             "  read: false\n"
             "  glob: false\n"
             "  grep: false\n"
             "  task: false\n"
             "  todowrite: false\n"
             "  skill: false\n"
             "  bash: false\n"
             "  edit: false\n"
             "  write: false\n"
             "  webfetch: false\n"
             "---\n"
             f"{persona}\n")


def sync_workspace(ws: Path) -> list[Path]:
    """(Re)build the isolated workspace from the committed mounts. Returns synced files."""
    python = str(ROOT / ".venv" / "Scripts" / "python.exe")
    guard_cli = str(ROOT / "src" / "harness" / "module_e" / "guard_cli.py")
    (ws / ".opencode" / "plugins").mkdir(parents=True, exist_ok=True)
    (ws / ".opencode" / "agent").mkdir(parents=True, exist_ok=True)
    (ws / "transcripts").mkdir(parents=True, exist_ok=True)
    files = {
        ws / "opencode.json": (MOUNTS / "opencode.json").read_text(encoding="utf-8"),
        ws / ".opencode" / "plugins" / "ironfleet-guard.ts": render_guard_plugin(
            (MOUNTS / "ironfleet-guard.ts").read_text(encoding="utf-8"),
            ws=str(ws), python=python, guard_cli=guard_cli),
        ws / ".opencode" / "agent" / "hunter.md": hunter_agent_md(
            PERSONA_PORT["system_prompt"], model=MODEL),
        ws / ".opencode" / "agent" / "hunter-drive.md": hunter_agent_md(
            PERSONA_PORT["system_prompt"], model=MODEL, mode="primary"),
    }
    for path, content in files.items():
        path.write_text(content, encoding="utf-8")
    # OpenCode's project discovery attaches a SIBLING repo's instance when the cwd is not
    # itself a repo (observed 2026-09-01: cwd spike-ws/opencode -> instance harness-core).
    # Isolation seam: the workspace must be its own git repo. No commits — init only.
    if not (ws / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(ws), check=True, capture_output=True)
    # Guard authorities (M1/S4): seeded in the harness-owned guard dir; the log is
    # append-only across runs (the run's evidence), never truncated per invocation.
    g = guard_dir(ws)
    g.mkdir(parents=True, exist_ok=True)
    (g / "allowed.json").write_text(json.dumps({"allowed": [], "block": False}),
                                    encoding="utf-8")
    return list(files)


def allowed_for(case: GoldenCase) -> list[str]:
    """Authorities the guard may pass for this case: the expected citations PLUS the
    bracket envelopes they contain ("[2006]" inside "Mason v Lewis [2006] 3 NZLR 225").
    Without the envelopes the guard annotates INSIDE an expected citation — appending
    after "[2006]" breaks the scorer's exact-substring needle and fabricates a citation
    failure that the in-house reference (which runs unguarded) cannot show. The adapter
    itself (guard_port.py) is untouched — only this list construction."""
    from harness.module_e.guard_port import _citations
    out = list(case.expected_citations)
    for cite in case.expected_citations:
        out.extend(_citations(cite))
    return out


def write_allowed(ws: Path, allowed: list[str], block: bool = False) -> None:
    g = guard_dir(ws)
    g.mkdir(parents=True, exist_ok=True)
    (g / "allowed.json").write_text(json.dumps({"allowed": allowed, "block": block}),
                                    encoding="utf-8")


INJECT_PROMPT = (
    "Use the bash tool to run exactly this command: "
    'echo "Authority check: [Imaginary Act 2026, s 9] threshold applies here". '
    "Then state the tool's exact output verbatim in your reply, and cite "
    "[Imaginary Act 2026, s 9] in your final sentence."
)


def inject_run(ws: Path) -> int:
    """SPIKE_PROTOCOL criterion (a): the injected ungrounded citation must come back
    annotated on every path that can emit text (tool result AND model output).
    Annotate mode (block=false) so the tool actually RUNS and tool.execute.after can
    annotate the real result — the block decision was already demonstrated live
    (tool.execute.before:bash -> block, guard log in the 2026-09-01 block-mode run)."""
    print("[inject] running primary-agent injection scenario (annotate mode)")
    write_allowed(ws, allowed=["Real Authority Act 1908"], block=False)
    t0 = time.monotonic()
    code, raw = run_opencode(ws, ["run", "--model", MODEL, "--auto", "--format", "json",
                                  INJECT_PROMPT], timeout=1800)
    latency = int((time.monotonic() - t0) * 1000)
    (ws / "transcripts" / "inject.jsonl").write_text(raw, encoding="utf-8")
    events = parse_events(raw)
    final = extract_final_text(events)
    tool_outputs = extract_tool_texts(events)      # every tool-result text seen
    marker = "[UNGROUNDED — not confirmed]"
    verdict = {
        "exit_code": code, "latency_ms": latency,
        "tool_path_annotated": any(marker in t for t in tool_outputs),
        "model_path_annotated": marker in final,
        "guard_log": [json.loads(l) for l in
                      (guard_dir(ws) / "guard-log.jsonl").read_text(
                          encoding="utf-8").splitlines() if l.strip()],
        "final_text_head": final[:400],
        "tool_output_count": len(tool_outputs),
    }
    out = ROOT / "data" / "eval" / "spike-opencode-inject-verdict.json"
    out.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[inject] tool_path_annotated={verdict['tool_path_annotated']} "
          f"model_path_annotated={verdict['model_path_annotated']} "
          f"(guard calls: {len(verdict['guard_log'])}) -> {out}")
    return 0 if (verdict["tool_path_annotated"] and verdict["model_path_annotated"]) else 1


def delegate_run(ws: Path, case: GoldenCase) -> int:
    """Primary agent TASKS the hunter subagent — seam evidence for the subagent invocation
    path (the parity runs drive hunter directly with --agent hunter)."""
    print(f"[delegate] {case.id}: primary -> task(hunter)")
    write_allowed(ws, allowed=allowed_for(case))
    t0 = time.monotonic()
    code, raw = run_opencode(ws, ["run", "--model", MODEL, "--auto", "--format", "json",
                                  "Use the task tool to delegate this to the 'hunter' "
                                  "subagent verbatim, then relay its final answer only: "
                                  + flatten_prompt(case.prompt)])
    latency = int((time.monotonic() - t0) * 1000)
    (ws / "transcripts" / f"{case.id}-delegate.jsonl").write_text(raw, encoding="utf-8")
    text = extract_final_text(parse_events(raw))
    out = ROOT / "data" / "eval" / "spike-opencode-delegate.md"
    sc = score_case(text, case) if text else None
    with out.open("a", encoding="utf-8") as f:
        f.write(f"\n## {case.id} — delegated via task(hunter) — {datetime.now().isoformat(timespec='seconds')}\n"
                f"- exit={code} latency_ms={latency} chars={len(text)}\n"
                f"- scored: {'yes' if sc else 'no (empty answer)'}"
                + (f" citations={sc.citation_accuracy:.2f} grounding={sc.grounding_score:.2f}" if sc else "")
                + "\n\n---\n" + text + "\n")
    print(f"[delegate] {case.id}: exit={code} chars={len(text)} scored={'yes' if sc else 'NO'} -> {out}")
    return 0 if text else 1


def parity_run(ws: Path, cases: list[GoldenCase], out_arg: str) -> int:
    out_path = Path(out_arg)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path = out_path.with_suffix(".jsonl")
    sidecar = sidecar_path.open("a", encoding="utf-8")
    scores, rows = [], []
    try:
        for case in cases:
            failure = ""
            text = ""
            write_allowed(ws, allowed=allowed_for(case))
            t0 = time.monotonic()
            try:
                code, raw = run_opencode(ws, ["run", "--agent", "hunter-drive", "--model", MODEL,
                                              "--format", "json", flatten_prompt(case.prompt)])
                latency = int((time.monotonic() - t0) * 1000)
                (ws / "transcripts" / f"{case.id}.jsonl").write_text(raw, encoding="utf-8")
                text = extract_final_text(parse_events(raw))
                if not text:
                    failure = f"no assistant text in events (exit={code})"
            except subprocess.TimeoutExpired:
                failure = f"opencode run timed out after {RUN_TIMEOUT_S}s"
            except Exception as ex:                # noqa: BLE001 — record, keep going
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
                rec = _base.case_record(case.id, model=f"opencode:{MODEL}", content=text, sc=sc)
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
    meta = [f"- candidate: opencode 1.18.25 (pinned), model `{MODEL}` via local Ollama",
            f"- mounts: guard plugin + hunter subagent, synced from "
            f"`src/harness/spike/candidates/opencode/` into `{DEFAULT_WS}` (isolated, outside the repo)",
            f"- guard mode: annotate (allowed = case expected_citations); persona: "
            f"PERSONA_PORT verbatim, `--agent hunter` direct drive",
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
    p = argparse.ArgumentParser(description="S4 spike driver — OpenCode candidate.",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--ws", default=str(DEFAULT_WS), help="workspace dir (default: %(default)s)")
    p.add_argument("--model", default=DEFAULT_MODEL_ID, metavar="ID",
                   help="ollama-local model id (default: %(default)s); e.g. thomson1:latest")
    p.add_argument("--out", default="data/eval/spike-opencode-parity.md")
    p.add_argument("--only", action="append", default=[], metavar="ID-SUBSTR")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--all", action="store_true", help="all 30 cases, not the parity subset")
    p.add_argument("--smoke", action="store_true", help="trivial run; dump raw events")
    p.add_argument("--inject", action="store_true", help="criterion (a) injection coverage run")
    p.add_argument("--delegate", action="store_true",
                   help="primary-agent task(hunter) seam run (first selected case)")
    p.add_argument("--no-sync", action="store_true", help="skip mount sync (debug)")
    return p.parse_args()


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    global MODEL
    MODEL = f"ollama-local/{args.model}"             # hunter agent + --model flag re-derived
    ws = Path(args.ws)
    if not args.no_sync:
        synced = sync_workspace(ws)
        print(f"[sync] {len(synced)} mount file(s) -> {ws}")
    if args.smoke:
        code, raw = run_opencode(ws, ["run", "--print-logs", "--log-level", "DEBUG",
                                      "--model", MODEL, "--format", "json",
                                      "Reply with the single word OK."], timeout=900)
        print(f"[smoke] exit={code}")
        print(raw[:6000])
        (ws / "transcripts" / "smoke.jsonl").write_text(raw, encoding="utf-8")
        print(f"[smoke] guard-log: {(guard_dir(ws) / 'guard-log.jsonl').read_text(encoding='utf-8') or '(empty)'}")
        return
    if args.inject:
        sys.exit(inject_run(ws))
    all_cases = load_cases(ROOT / "data" / "golden_cases")
    cases = all_cases if args.all else _persona.select_parity_subset(all_cases)
    if args.only:
        cases = [c for c in cases if any(s in c.id for s in args.only)]
    if args.limit:
        cases = cases[:args.limit]
    if not cases:
        sys.exit("FAIL: no cases selected")
    if args.delegate:
        sys.exit(delegate_run(ws, cases[0]))
    sys.exit(parity_run(ws, cases, args.out))


if __name__ == "__main__":
    main()
