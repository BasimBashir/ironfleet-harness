"""S7d acceptance — A-3 gate + trace integration (spec specs/07, section 3).

Five strict checks; exit 0 ONLY if all pass; a failure names the check. No partial mode
(S7c user decision 4: keep docs). The store the whole run uses is SEEDED LEGACY (C5), so
the live dispatch itself proves a real migration, not a fresh DB.

  C1 mount statics — on the SYNCED copy, not the source (proves what will actually run)
  C2 positive exclusivity — `opencode models` resolves EXACTLY gate-local/* under an
     adversarial credential env (finding S1: the trace store can never prove a negative)
  C3 one live dispatch traced completely — incl. backend per the S7d rule
     (mechanical class, honestly admitted (MECHANICAL_TASKS) — summarization would
     refuse under CR-3 mechanical-only admission)
  C4 fail-closed still traced — proxy-direct, because opencode cannot request an alias
     absent from its catalog, and adding one to the mount would break C2's exact-9
  C5 legacy migration live — the seeded pre-S7d row survives with backend=''

The binary version is PRINTED, never asserted: the pin decision is S7c's pending user
decision, not S7d's claim.

Usage: .venv/Scripts/python.exe scripts/accept_s7d.py [--keep-ws]
"""
from __future__ import annotations

import argparse, json, os, shutil, sqlite3, sys, urllib.error, urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))   # scripts.* imports (stand_up_opencode.py:33-38 lesson)

from harness.alias import load_aliases
from harness.egress_proxy import EgressProxy
from harness.policy import RoutingTable
from scripts.stand_up_opencode import (HOST, MOUNT, PORT, ROUTING, build_gate, child_env,
                                       run_opencode_session, sync_mount)
from scripts.verify_opencode_mount import installed_version, verify_child_env, verify_models

WS = Path.home() / "spike-ws-a1" / "opencode-a1-s7d-accept"
MATTER_REF = "m-s7d-accept"
LEGACY_MATTER_REF = "m-s7d-legacy"
REFUSAL_ALIAS = "gate/refusal_probe"

# Synthetic, obviously-fake credentials in the families the rig's negative controls proved
# activate builtin providers (live 2026-10-01: 178 bedrock / 19 anthropic / 61 openai
# models resolved). Never real values.
ADVERSARIAL = {
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_REGION": "us-east-1",
    "ANTHROPIC_API_KEY": "sk-ant-s7d-acceptance-fake",
    "OPENAI_API_KEY": "sk-s7d-acceptance-fake",
}

# The dispatches table EXACTLY as it existed before S7d (trace.py at b9590b9).
LEGACY_DDL = """CREATE TABLE IF NOT EXISTS dispatches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
  matter_ref TEXT, task_class TEXT, classification TEXT,
  provider TEXT, model TEXT, weights_revision TEXT, engine TEXT, verified INTEGER,
  tokens_in INTEGER, tokens_out INTEGER, tokens_cache INTEGER,
  latency_ms INTEGER, status TEXT, error TEXT);"""


def seed_legacy_db(db: Path) -> None:
    """Create the pre-S7d schema and one legacy row. TraceStore.__init__ (inside
    build_gate) then migrates THIS file in place — C5 is the live run's own migration."""
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    try:
        con.executescript(LEGACY_DDL)
        con.execute(
            "INSERT INTO dispatches(ts,matter_ref,task_class,classification,provider,model,"
            "weights_revision,engine,verified,tokens_in,tokens_out,tokens_cache,latency_ms,status,error)"
            " VALUES('2026-09-22T00:00:00+00:00',?, 'drafting','LOCAL_PREFERRED',"
            "'ollama-local','thomson1-chat:latest','','',0,1,1,0,5,'ok','')",
            (LEGACY_MATTER_REF,))
        con.commit()
    finally:
        con.close()


def check_mount_statics(cfg: dict, port: int) -> list[str]:
    """C1. Deliberately duplicates test_mount_a1.py's pins: the acceptance stands alone
    as evidence, as S7b's did. Reads the SYNCED workspace copy."""
    problems: list[str] = []
    providers = cfg.get("provider", {})
    if list(providers) != ["gate-local"]:
        problems.append(f"C1: expected exactly one provider gate-local, found {list(providers)}")
    p = providers.get("gate-local", {})
    # The template carries bare /v1; a synced workspace carries its M1/S3 matter token.
    base = p.get("options", {}).get("baseURL") or ""
    if base != f"http://127.0.0.1:{port}/v1" and not base.startswith(
            f"http://127.0.0.1:{port}/v1/t/"):
        problems.append("C1: gate-local options.baseURL is not the loopback proxy")
    if "baseURL" in p:
        problems.append("C1: top-level baseURL is silently ignored at runtime")
    if cfg.get("disabled_providers") != ["opencode"]:
        problems.append("C1: disabled_providers must be exactly ['opencode'] (keyless catalog)")
    if cfg.get("share") != "disabled" or cfg.get("autoupdate") is not False:
        problems.append("C1: share/autoupdate hardening lost")
    if cfg.get("agent", {}).get("title", {}).get("disable") is not True:
        problems.append("C1: agent.title.disable lost — title generation is a second dispatch")
    for name, spec in p.get("models", {}).items():
        if not {"context", "output"} <= set(spec.get("limit", {})):
            problems.append(f"C1: model {name} missing limit.context/output — the binary "
                            f"exits 1 at config validation")
        if spec.get("limit", {}).get("output", 0) < 16384:
            problems.append(f"C1: model {name} below the thomson1 16k output floor (D12)")
    return problems


def adversarial_child_env(ws: Path) -> dict[str, str]:
    """C2's env: the REAL child_env under injected credentials — os.environ is temporarily
    extended and restored, so the actual scrub path runs (reimplementing its body would let
    the check and the scrub drift apart). Restores the parent exactly, failure or not."""
    injected: dict[str, str | None] = {}
    for k, v in ADVERSARIAL.items():
        injected[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        return child_env(ws)
    finally:
        for k, old in injected.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _refusal_routing(ws: Path) -> Path:
    """Routing + aliases for the proxy only: one extra alias whose rule names only an
    UNREGISTERED provider. opencode never sees it (not in its catalog); C2's exact-9 is
    untouched. Mirrors test_refusal_returns_403_and_traces without private-attr poking."""
    doc = yaml.safe_load(ROUTING.read_text(encoding="utf-8"))
    doc["aliases"][REFUSAL_ALIAS] = {"task_class": "refusal_probe"}
    doc["rules"].append({"task_class": "refusal_probe",
                         "local_only": ["mini1-mlx"], "local_preferred": ["mini1-mlx"],
                         "cloud_permitted": ["mini1-mlx"]})
    out = ws / "routing-s7d.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-ws", action="store_true", help="keep the workspace for inspection")
    args = ap.parse_args(argv)

    ws = WS
    if ws.exists():
        shutil.rmtree(ws)        # a stale workspace's trace.db would break C3's row counts

    trace_db = ws / "trace.db"
    seed_legacy_db(trace_db)                                   # C5's legacy shape, seeded first
    gate, _rt, _aliases = build_gate(trace_db)                 # probes real Ollama; migrates
    if not gate.registry.list():
        print("[accept-s7d] Ollama not reachable/admitted — acceptance cannot run",
              file=sys.stderr)
        return 1

    sync_mount(ws, MOUNT, MATTER_REF, "LOCAL_PREFERRED", PORT)
    cfg = json.loads((ws / "opencode.json").read_text(encoding="utf-8"))
    routing_s7d = _refusal_routing(ws)
    gate.routing = RoutingTable.from_yaml(routing_s7d)
    # ThreadingHTTPServer binds in its CONSTRUCTOR (start() only spawns the serve_forever
    # thread), so the guard wraps construction, not start(): a 7373 collision would otherwise
    # abort with a traceback, unnamed by any check, and leave the seeded workspace on disk.
    # Mirrors the proven guard in stand_up_opencode.main.
    try:
        proxy = EgressProxy(HOST, PORT, gate, gate.routing, load_aliases(routing_s7d),
                            ws.parent / "matters")   # sync_mount's default registry
    except OSError as ex:
        print(f"[accept-s7d] C0: cannot bind {HOST}:{PORT} — a collision would point the "
              f"mount elsewhere: {ex}", file=sys.stderr)
        shutil.rmtree(ws, ignore_errors=True)   # the run never started; no seeded tree left
        return 1
    proxy.start()
    problems: list[str] = []
    try:
        problems += check_mount_statics(cfg, PORT)             # C1

        env = adversarial_child_env(ws)                        # C2
        problems += [f"C2: {p}" for p in verify_child_env(env)]
        model_problems, _evidence = verify_models(ws, env)
        problems += [f"C2: {p}" for p in model_problems]

        prior = len(gate.trace.by_matter(MATTER_REF))          # C3
        code, text = run_opencode_session(
            ws, "gate/extraction",
            "Extract the party names as bullets. Text: 'ACME Ltd and Beta Corp "
            "entered into an agreement on 3 March 2026.'", 600, env=child_env(ws))
        rows = gate.trace.by_matter(MATTER_REF)
        if code != 0:
            problems.append(f"C3: opencode exited {code}; tail: {text[-200:]!r}")
        if len(rows) != prior + 1:
            problems.append(f"C3: expected exactly 1 new trace row, got {len(rows) - prior}")
        else:
            row = rows[-1]
            if row.provider != "ollama-local" or row.status != "ok":
                problems.append(f"C3: provider={row.provider} status={row.status}")
            if row.model != "thomson1-chat:latest":
                problems.append(f"C3: model {row.model!r}")
            if row.backend != "":
                problems.append(f"C3: backend must read '' on Ollama (CR-3 honest), "
                                f"got {row.backend!r}")
            if row.verified != 0:
                problems.append(f"C3: verified must be 0 on Ollama, got {row.verified}")
            if not text.strip():
                problems.append("C3: empty assistant text")

        req = urllib.request.Request(                          # C4 — proxy-direct
            cfg["provider"]["gate-local"]["options"]["baseURL"] + "/chat/completions",
            data=json.dumps({"model": REFUSAL_ALIAS,
                             "messages": [{"role": "user",
                                           "content": "must never dispatch"}]}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=30)
            problems.append("C4: refusal probe did NOT 403 — a refusal passed through")
        except urllib.error.HTTPError as ex:
            if ex.code != 403:
                problems.append(f"C4: expected 403, got {ex.code}")
        refusals = [r for r in gate.trace.by_matter(MATTER_REF) if r.status == "refused"]
        if not refusals or refusals[-1].provider != "-":
            problems.append("C4: no refused row with provider '-' traced")

        legacy = gate.trace.by_matter(LEGACY_MATTER_REF)       # C5
        if len(legacy) != 1 or legacy[0].backend != "":
            problems.append("C5: legacy row did not survive migration with backend=''")
        con = sqlite3.connect(trace_db)
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(dispatches)").fetchall()]
        finally:
            con.close()
        if cols.count("backend") != 1:
            problems.append(f"C5: backend column count {cols.count('backend')}")
    finally:
        proxy.stop()

    if not args.keep_ws:
        shutil.rmtree(ws, ignore_errors=True)

    if problems:
        for p in problems:
            print(f"[accept-s7d] FAIL {p}", file=sys.stderr)
        print(f"[accept-s7d] {len(problems)} check failure(s) — S7d NOT accepted "
              f"(opencode binary: {installed_version()!r})", file=sys.stderr)
        return 1
    print(f"[accept-s7d] ACCEPTED: C1 mount statics; C2 gate-local-only under adversarial "
          f"env; C3 live dispatch traced (backend per rule); C4 fail-closed traced; "
          f"C5 legacy migration live. opencode binary: {installed_version()!r}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
