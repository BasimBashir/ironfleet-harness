"""The user-facing entry point (S7j-W step 2): version, serve, drive.

The distribution tree IS the repo tree (editable install), so the packaged data
resolves from this file's own path — the launcher keeps its no-CWD-default rule;
this module is the layer that knows where the packaged data lives and hands it over
explicitly.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import harness


def default_routing() -> Path:
    """The packaged routing YAML. FileNotFoundError here means a non-editable install
    stranded the data — reinstall editable, per the install script."""
    p = Path(__file__).resolve().parents[2] / "data" / "routing-a1.yaml"
    if not p.is_file():
        raise FileNotFoundError(
            f"packaged routing not found at {p} — the distribution tree ships data/ at "
            f"its repo paths; install editable (pip install -e .) per the install script")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="harness", description=__doc__)
    ap.add_argument("--version", action="version", version=f"harness {harness.__version__}")
    sub = ap.add_subparsers(dest="cmd")
    serve = sub.add_parser("serve", help="stand up the egress proxy against the privileged store")
    serve.add_argument("--routing", default=None, help="routing YAML (default: the packaged one)")
    serve.add_argument("--port", type=int, default=7373)
    drive = sub.add_parser("drive", help="one live opencode session through the gate (smoke)")
    drive.add_argument("--matter-ref", required=True)
    drive.add_argument("--task-class", default="extraction")
    drive.add_argument("--workspace", default=None)
    drive.add_argument("--prompt", default=None)
    drive.add_argument("--timeout", type=int, default=600)
    # store CRUD (2026-10-14): a matter's corpus + vectors are fully manageable from the
    # harness — create/update via corpus_ingest, read/delete here. Deletes are gated.
    vectors = sub.add_parser("vectors", help="manage the local vector index (CRUD)")
    vsub = vectors.add_subparsers(dest="vcmd")
    vc = vsub.add_parser("count", help="stored vector rows for a matter")
    vc.add_argument("--matter", required=True)
    vl = vsub.add_parser("list", help="row-level read (id, model, text head)")
    vl.add_argument("--matter", required=True)
    vl.add_argument("--limit", type=int, default=20)
    vd = vsub.add_parser("delete", help="delete texts, or the WHOLE matter (destructive)")
    vd.add_argument("--matter", required=True)
    vd.add_argument("--texts", nargs="*", default=None,
                    help="omit to purge every row of the matter")
    vd.add_argument("--yes", action="store_true", help="required: deletes are irreversible")
    corpus = sub.add_parser("corpus", help="manage a matter's corpus store (CRUD)")
    csub = corpus.add_subparsers(dest="ccmd")
    cd = csub.add_parser("drop", help="drop the matter's docs/fts/cites tables (destructive)")
    cd.add_argument("--matter", required=True)
    cd.add_argument("--yes", action="store_true", help="required: deletes are irreversible")
    # R3 (2026-10-19): provider/key management from the CLI — the operator surface the
    # "change provider/model at any time" directive needs. Keys land in the OS keychain
    # only (keyring; never on disk, S7h convention); model/URL swaps ride the routing
    # YAML (data/routing-a1.yaml) or the IRONFLEET_NIM_* env vars.
    prov = sub.add_parser("providers", help="list providers or set a cloud API key (keychain)")
    psub = prov.add_subparsers(dest="pcmd")
    pl = psub.add_parser("list", help="probe every configured provider and print its honest verdict")
    ps = psub.add_parser("set-key", help="store a cloud API key in the OS keychain")
    ps.add_argument("--provider", required=True, help="registry name, e.g. nvidia-nim")
    ps.add_argument("--key", required=True, help="the API key (never echoed, never written to disk)")
    # R3 (spec 17 s5.1): the session driver's non-TUI entry point. Same shape as the
    # other subcommands — argparse here, the real work in scripts/session_cli.py, so the
    # CLI and the TUI drive ONE SessionDriver, never two.
    sess = sub.add_parser("session", help="session store CRUD + one agent turn (R3)")
    sg = sess.add_mutually_exclusive_group(required=True)
    sg.add_argument("--new", action="store_true", help="start a new session")
    sg.add_argument("--list", action="store_true", help="list sessions (newest first)")
    sg.add_argument("--resume", metavar="ID", help="resume <id|last> and print its state")
    sg.add_argument("--turn", action="store_true", help="run one agent turn")
    sg.add_argument("--errors", action="store_true",
                    help="print the recorded error log (where/why/which line)")
    sess.add_argument("--matter", default=None, help="matter ref (with --new)")
    sess.add_argument("--display", default="", help="human label (with --new)")
    sess.add_argument("--session", metavar="ID", default=None,
                      help="session id for --turn/--resume (default: last)")
    sess.add_argument("--agent", default=None, help="agent/persona name (with --turn)")
    sess.add_argument("--prompt", default=None, help="the turn prompt (required with --turn)")
    sess.add_argument("--model", default="gate-local/gate/extraction", help="routing model")
    # M11 T2: the upgrade surface. Brings every known SQLite store under the
    # privileged root to the current schema — versioned, additive-only (02 §15).
    mig = sub.add_parser("migrate",
                         help="upgrade the store databases to the current schema"
                              " (run after extracting a new version, before first use)")
    mig.add_argument("--root", default=None,
                     help="store root (default: resolve_store_root())")
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from harness.ops.ironfleet_launcher import main as serve_main
        routing = args.routing or os.environ.get("IRONFLEET_ROUTING") or str(default_routing())
        return serve_main(["--routing", routing, "--port", str(args.port)])
    if args.cmd == "drive":
        # the drive driver lives in the installed package now (M3)
        from harness.substrate.mount import main as drive_main
        argv2 = ["--matter-ref", args.matter_ref, "--task-class", args.task_class,
                 "--timeout", str(args.timeout)]
        if args.workspace:
            argv2 += ["--workspace", args.workspace]
        if args.prompt:
            argv2 += ["--prompt", args.prompt]
        return drive_main(argv2)
    if args.cmd == "vectors":
        from harness.paths import resolve_store_root
        from harness.vectors import VectorStore
        root, _src = resolve_store_root()
        store = VectorStore(Path(root) / "vectors.sqlite3")
        if args.vcmd == "count":
            print(store.count(args.matter))
            return 0
        if args.vcmd == "list":
            for row in store.list_texts(args.matter, limit=args.limit):
                print(f"{row['id']}\t{row['model']}\t{row['text'][:100]}")
            return 0
        if args.vcmd == "delete":
            if not args.yes:
                print("refusing: vector deletes are irreversible — pass --yes",
                      file=sys.stderr)
                return 2
            n = store.delete(args.matter, texts=args.texts or None)
            scope = "specified texts" if args.texts else "THE WHOLE MATTER"
            print(f"deleted {n} vector rows ({scope}) for {args.matter}")
            return 0
        vectors.print_help()
        return 2
    if args.cmd == "corpus":
        if args.ccmd != "drop":
            corpus.print_help()
            return 2
        if not args.yes:
            print("refusing: dropping a matter's corpus is irreversible — pass --yes",
                  file=sys.stderr)
            return 2
        from harness.corpus import CorpusStore
        from harness.paths import resolve_store_root
        root, _src = resolve_store_root()
        store = CorpusStore(Path(root) / "corpus.sqlite3")
        store.drop_matter(args.matter)
        print(f"dropped corpus tables for {args.matter}")
        return 0
    if args.cmd == "providers":
        if args.pcmd == "set-key":
            from harness.keychain import set_key
            set_key(args.provider, args.key)
            print(f"key stored for {args.provider} (OS keychain; never on disk)")
            return 0
        if args.pcmd == "list":
            # The honest verdict per provider: the same probe build_gate runs, so what
            # this prints IS what the gate will admit (no separate code path to drift).
            from harness.bootstrap import _probe_ollama
            _probe_ollama()
            return 0
        prov.print_help()
        return 2
    if args.cmd == "migrate":
        from harness.migrate import MigrationError, migrate
        root = Path(args.root) if args.root else None
        if root is None:
            from harness.paths import resolve_store_root
            root, src = resolve_store_root()
            print(f"store {root} (source: {src})")
        try:
            reports = migrate(root)
        except MigrationError as ex:
            print(f"MIGRATION FAILED: {ex}", file=sys.stderr)
            return 1
        for r in reports:
            if r.status == "absent":
                print(f"  absent  {r.path} (created on first use)")
            elif r.steps_applied:
                print(f"  migrated {r.path}: v{r.from_version} -> v{r.to_version}"
                      f" ({r.steps_applied} step{'s' if r.steps_applied != 1 else ''})")
            else:
                print(f"  current  {r.path} (v{r.to_version})")
        return 0
    if args.cmd == "session":
        # the session CLI lives in the installed package now (M3)
        from harness.session.cli import main_with_args
        # One parsed namespace, no re-derivation: session_cli's mode flags are the same
        # flags cli.py already validated (argparse enforces the exactly-one rule twice,
        # but the namespace passes through untouched instead of being rebuilt as argv).
        return main_with_args(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
