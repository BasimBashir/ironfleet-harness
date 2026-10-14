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
    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from harness.ops.ironfleet_launcher import main as serve_main
        routing = args.routing or os.environ.get("IRONFLEET_ROUTING") or str(default_routing())
        return serve_main(["--routing", routing, "--port", str(args.port)])
    if args.cmd == "drive":
        # scripts/ is a namespace package at the repo root, not installed — the drivers
        # resolve it the same way (stand_up_opencode inserts ROOT into sys.path).
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from scripts.stand_up_opencode import main as drive_main
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
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
