"""R1 acceptance check C5 — the LIVE opencode toolpath session (spec 14 §3; plan Task 9).

Proves, on the real pinned binary + the real proxy + the real corpus store:
  C5-1  a real query drives a session through the gate (qwen via gate/toolpath — the
        S7j-W-ruled tool-calling leg; thomson1 makes no in-session tool call)
  C5-2  the model's ironfleet_corpus_search call EXECUTES through the mount's tools
        shim (module_e.dispatch) and the guard captures the authorities envelope
        (<ws>/passages.json — the D6 transport landed 2026-10-14)
  C5-3  the captured passages are VERBATIM store passages (provenance survives to the
        referee's allowance)
  C5-4  the agent answers from the session (final text present, names the section)
  C5-5  a FABRICATED quote in model output is flagged [UNQUOTED] by the D6 referee and
        an invented citation is flagged [UNGROUNDED] by the needle guard — on the live
        text.complete path (annotate = the enforcement; the throw surfaces are the tool
        hooks, and this driver runs annotate-only so the corpus envelope's JSON brackets
        cannot storm tool.execute.after — the S7c priced seam)
  C5-6  the fail-closed trio through the LIVE dispatch subprocess: no matter bound,
        unregistered matter, and the bound matter answering for real
  C5-7  the proxy's trace store records the session's dispatches

Three-valued exit (the house contract): 0 all checks; 2 = a live layer is due or
unavailable (binary missing, Ollama down, corpus not ingested, port held) — NO verdict
written; 1 = a required check failed.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.accept_s7c import (                                        # noqa: E402
    CASE_TIMEOUT_S, INJECT_ALIAS, build_gates, guard_log, run_opencode_retry,
    write_allowed)
from scripts import run_spike_opencode as spike                        # noqa: E402
from scripts import verify_opencode_mount as rig                       # noqa: E402
from scripts.stand_up_opencode import (                                # noqa: E402
    HOST, MOUNT, PORT, child_env, sync_mount)
from harness.egress_proxy import EgressProxy                           # noqa: E402

MATTER = "m-r1-c5"
STORE_FLOOR_DOCS, STORE_FLOOR_CHUNKS = 7300, 19000     # the C3 floors: C5 rides a real corpus

POSITIVE_PROMPT = (
    "Call the ironfleet_corpus_search tool to find the director's duty of care under "
    "section 131 of the Companies Act 1993 in this matter's corpus, then answer in one "
    "short paragraph: what does section 131 require of a director? Quote the exact "
    "statutory wording you were given and name the section number.")
FABRIC_PROMPT = (
    "Do NOT call any tools. Answer in one sentence, and include exactly this quotation "
    "in your answer: \"The director owes a duty of cosmic care beyond all earthly "
    "statutes\" citing [Imaginary Act 2026, s 9] as the authority.")
INVENTED_QUOTE = "duty of cosmic care beyond all earthly statutes"
INVENTED_CITE = "[Imaginary Act 2026, s 9]"


def _ollama_up() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
        return True
    except Exception:                                              # noqa: BLE001
        return False


def _store_ready() -> tuple[bool, int, int]:
    from harness.corpus import CorpusStore
    from harness.paths import resolve_store_root
    root, _ = resolve_store_root()
    store = CorpusStore(root / "corpus.sqlite3")
    docs, chunks = store.doc_count("m-r1-accept"), store.count("m-r1-accept")
    return docs >= STORE_FLOOR_DOCS and chunks >= STORE_FLOOR_CHUNKS, docs, chunks


def _passages_are_store_verbatim(ws: Path) -> tuple[bool, int, str]:
    """Every captured authority must be a VERBATIM stored chunk body (provenance from
    the store through the live tool envelope to the referee's allowance)."""
    from harness.corpus import CorpusStore
    from harness.paths import resolve_store_root
    root, _ = resolve_store_root()
    store = CorpusStore(root / "corpus.sqlite3")
    with store._c() as c:
        rows = c.execute("SELECT body FROM fts_m_r1_accept").fetchall()
    bodies = {r[0] for r in rows}
    try:
        captured = json.loads((ws / "passages.json").read_text(encoding="utf-8"))
    except Exception as ex:                                        # noqa: BLE001
        return False, 0, f"passages.json unreadable: {ex}"
    if not captured:
        return False, 0, "passages.json empty"
    misses = [p[:60] for p in captured if p not in bodies]
    return not misses, len(captured), f"{len(misses)} non-verbatim: {misses[:2]}"


def _dispatch_probe(env: dict, matter_env: str | None, out_file: Path) -> dict:
    """The EXACT subprocess the TS tools shim spawns, under a controlled matter env."""
    tools_yaml = REPO / "data" / "module-e" / "tools.yaml"
    in_file = out_file.with_suffix(".in.json")
    in_file.write_text(json.dumps({"query": "director duty of care", "k": 3,
                                   "rerank": False}), encoding="utf-8")
    child = {**env}
    if matter_env is None:
        child.pop("IRONFLEET_MATTER", None)
    else:
        child["IRONFLEET_MATTER"] = matter_env
    proc = subprocess.run(
        [sys.executable, "-m", "harness.module_e.dispatch", str(tools_yaml),
         "ironfleet_corpus_search", str(in_file), str(out_file)],
        capture_output=True, text=True, timeout=600, env=child, cwd=str(REPO))
    try:
        return json.loads(out_file.read_text(encoding="utf-8"))
    except Exception:                                              # noqa: BLE001
        return {"error": f"dispatch rc={proc.returncode}: {proc.stderr[-300:]}"}


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    out_dir = REPO / "data" / "eval" / f"R1-C5-{datetime.now():%Y%m%d-%H%M%S}"
    ws = out_dir / "ws"

    # -- prerequisites: any miss is DUE, not failed --------------------------------
    binary = rig.installed_version()
    ready, docs, chunks = _store_ready()
    due = []
    if not binary:
        due.append("opencode binary not found (install per the S7j-W pin)")
    if not _ollama_up():
        due.append("Ollama down on 127.0.0.1:11434")
    if not ready:
        due.append(f"corpus not ingested for m-r1-accept (docs={docs}, chunks={chunks}; "
                   f"run scripts/corpus_ingest.py first)")
    if due:
        for d in due:
            print(f"  - DUE: {d}")
        print("R1 C5: exit 2 — live layer due; no verdict written")
        return 2

    print(f"[setup] binary {binary}; store {docs} docs / {chunks} chunks; ws {ws}")
    sync_mount(ws, MOUNT, matter_ref=MATTER, classification="LOCAL_PREFERRED",
               port=PORT, matters_root=ws / "matters")
    (ws / "transcripts").mkdir(parents=True, exist_ok=True)
    write_allowed(ws, allowed=["Companies Act 1993"], block=False)   # annotate-only (priced seam)
    env = child_env(ws)
    env["IRONFLEET_MATTER"] = MATTER

    mount_gate, _house_gate, rt, aliases, model, honest = build_gates(ws)
    try:
        proxy = EgressProxy(HOST, PORT, mount_gate, rt, aliases, ws / "matters")
    except OSError as ex:
        print(f"  - DUE: port {PORT} held — {ex}")
        print("R1 C5: exit 2 — live layer due; no verdict written")
        return 2
    proxy.start()
    print(f"[gate] proxy on http://{HOST}:{PORT}/v1; injection model {model} "
          f"via gate-local/{INJECT_ALIAS} (admission honest={honest})", file=sys.stderr)

    problems: list[str] = []
    n_cap = 0
    try:
        trace_before = sqlite3.connect(ws / "trace-mount.db").execute(
            "SELECT COUNT(*) FROM dispatches").fetchone()[0]

        # -- session A: the real query through the real tool -----------------------
        print("[C5] session A: positive query (tool call + grounded quote)...", flush=True)
        code_a, raw_a = run_opencode_retry(
            ws, ["run", "--model", f"gate-local/{INJECT_ALIAS}", "--auto",
                 "--format", "json", spike.flatten_prompt(POSITIVE_PROMPT)],
            timeout=CASE_TIMEOUT_S, env=env, run_id="c5-positive")
        (ws / "transcripts" / "c5-positive.jsonl").write_text(raw_a, encoding="utf-8",
                                                              newline="")
        events_a = spike.parse_events(raw_a)
        final_a = spike.extract_final_text(events_a)
        if not events_a:
            problems.append("C5-1: session A produced no parsed events")
        decisions = guard_log(ws)
        tool_lines = [d for d in decisions
                      if str(d.get("tag", "")).startswith(
                          "tool.execute.after:ironfleet_corpus_search")]
        if not tool_lines:
            problems.append("C5-2: no ironfleet_corpus_search execution reached the "
                            "guard (the model made no tool call, or the shim lost it)")
        ok_cap, n_cap, cap_note = _passages_are_store_verbatim(ws)
        if not ok_cap:
            problems.append(f"C5-3: authorities envelope not verbatim store passages "
                            f"({n_cap} captured) — {cap_note}")
        else:
            print(f"[C5] C5-2/C5-3 PASS: tool executed live, {n_cap} verbatim passages "
                  f"captured to the referee allowance", flush=True)
        if not final_a or "131" not in final_a:
            problems.append("C5-4: session A answer missing or does not name s 131")
        else:
            print(f"[C5] C5-4 PASS: agent answered from the session "
                  f"({len(final_a)} chars)", flush=True)

        # -- session B: the fabrication -------------------------------------------
        print("[C5] session B: fabricated quote + invented citation...", flush=True)
        before_b = len(guard_log(ws))
        code_b, raw_b = run_opencode_retry(
            ws, ["run", "--model", f"gate-local/{INJECT_ALIAS}", "--auto",
                 "--format", "json", spike.flatten_prompt(FABRIC_PROMPT)],
            timeout=CASE_TIMEOUT_S, env=env, run_id="c5-fabricated")
        (ws / "transcripts" / "c5-fabricated.jsonl").write_text(raw_b, encoding="utf-8",
                                                                newline="")
        events_b = spike.parse_events(raw_b)
        final_b = spike.extract_final_text(events_b)
        blob = final_b + "\n" + json.dumps(guard_log(ws)[before_b:])
        if "UNQUOTED" not in blob:
            problems.append("C5-5: fabricated quote was NOT flagged [UNQUOTED] by the "
                            "live D6 referee")
        else:
            print("[C5] C5-5 PASS: invented quote flagged by the live referee", flush=True)
        if "UNGROUNDED" not in blob:
            problems.append("C5-5b: invented citation was NOT flagged [UNGROUNDED] by "
                            "the live needle guard")
        else:
            print("[C5] C5-5b PASS: invented citation flagged by the live needle guard",
                  flush=True)

        # -- fail-closed trio through the LIVE dispatch subprocess -----------------
        print("[C5] fail-closed trio via module_e.dispatch...", flush=True)
        trio = _dispatch_probe(env, None, out_dir / "trio-unbound.json")
        if trio != {"passages": [], "authorities": [], "error": "no matter bound"}:
            problems.append(f"C5-6a: unbound matter did not fail closed: {trio}")
        trio = _dispatch_probe(env, "m-unregistered-xyz", out_dir / "trio-unreg.json")
        if trio.get("passages"):
            problems.append("C5-6b: unregistered matter returned passages")
        trio = _dispatch_probe(env, "m-r1-accept", out_dir / "trio-bound.json")
        if not trio.get("passages"):
            problems.append(f"C5-6c: bound matter returned nothing: "
                            f"{str(trio)[:200]}")
        if not problems or all(p.startswith(("C5-1", "C5-2", "C5-3", "C5-4", "C5-5"))
                               for p in problems):
            print("[C5] C5-6 PASS: unbound refuses, unregistered empty, bound answers",
                  flush=True)

        trace_after = sqlite3.connect(ws / "trace-mount.db").execute(
            "SELECT COUNT(*) FROM dispatches").fetchone()[0]
        if trace_after <= trace_before:
            problems.append("C5-7: the proxy trace recorded no dispatches")
        else:
            print(f"[C5] C5-7 PASS: trace +{trace_after - trace_before} dispatch rows",
                  flush=True)
    finally:
        proxy.stop()

    verdict = {"generated": datetime.now().isoformat(timespec="seconds"),
               "binary": binary, "model": model, "matter": MATTER,
               "passages_captured": n_cap, "store": {"docs": docs, "chunks": chunks},
               "problems": problems, "exit_zero": not problems}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "c5-verdict.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    if problems:
        for p in problems:
            print(f"  - {p}")
        print(f"R1 C5: FAIL ({len(problems)} problems) — evidence in {out_dir}")
        return 1
    print(f"R1 C5: EXIT 0 — live toolpath, envelope transport, referee block, "
          f"fail-closed trio, trace. Evidence in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
