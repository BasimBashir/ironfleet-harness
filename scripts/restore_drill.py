# scripts/restore_drill.py — M11 T3: the backup/restore drill (cross-OS, stdlib+core).
"""Prove the restore path end-to-end, quarterly (RUNBOOK_P0_7) and before every
release (11-release-runbook). The LIVE store is never written: the drill

  1. SNAPSHOT — one consistent copy of every store file into --backup-dir
     (SQLite files via the backup API in read-only mode, so WAL content rides
     along; everything else copied byte-for-byte), with a sha256 manifest;
  2. TAMPER — on a SCRATCH copy, twice: byte-corrupt one database, and append
     a marker audit event (a divergence the restore must undo);
  3. RESTORE — wipe the scratch, copy the snapshot back;
  4. VERIFY — per-file sha256 match, per-DB integrity_check, the audit hash
     chain verifies, table counts match the manifest (the marker row is gone),
     and `harness migrate` upgrades the restored store cleanly (the upgrade
     drill on the copied store root, enterprise 06 Phase 10).

Exit 0 = PASS + an evidence block. Exit 1 = a named phase failed. Exit 2 =
usage (missing store, occupied backup dir). The live root is read-only by
construction; the tamper lives entirely under the scratch directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DB_SUFFIXES = (".db", ".sqlite3")
# sibling sidecar files the backup API already folds into the .db snapshot
SIDECARS = ("-wal", "-shm")
KNOWN_COUNTS = {"platform.db": ["audit_events", "matters", "cases"],
                "trace.db": ["dispatches"],
                "sessions/index.sqlite3": ["sessions", "jobs"]}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_sidecar(p: Path) -> bool:
    return any(p.name.endswith(s) for s in SIDECARS)


def under(p: Path, dir_: Path) -> bool:
    """True when p lives under dir_ (a drill output dir inside the store)."""
    try:
        p.relative_to(dir_)
        return True
    except ValueError:
        return False


def _iter_store_files(root: Path, skip: list[Path]):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not _is_sidecar(p) and not any(under(p, s) for s in skip):
            yield p


def snapshot(root: Path, backup_dir: Path) -> dict:
    import harness
    backup_dir.mkdir(parents=True)
    files: dict[str, dict] = {}
    for src in _iter_store_files(root, skip=[backup_dir]):
        rel = src.relative_to(root).as_posix()
        dst = backup_dir / Path(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix in DB_SUFFIXES:
            scon = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)
            try:
                # force a schema read: the backup API silently images a garbage
                # source as an empty DB; this is where "not a database" fails loud
                scon.execute("SELECT count(*) FROM sqlite_master").fetchone()
                dcon = sqlite3.connect(dst)
                scon.backup(dcon)
                dcon.close()
            finally:
                scon.close()
        else:
            shutil.copy2(src, dst)
        files[rel] = {"sha256": _sha256(dst), "bytes": dst.stat().st_size}
    manifest = {"ts": datetime.now(timezone.utc).isoformat(),
                "source": str(root), "harness_version": harness.__version__,
                "files": files}
    (backup_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def table_counts(db: Path, tables: list[str]) -> dict[str, int]:
    if not Path(db).is_file():
        return {}  # absent store: no counts, nothing to compare
    con = sqlite3.connect(db)
    counts = {}
    for t in tables:
        try:
            counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            pass  # table absent in this store
    con.close()
    return counts


def tamper(backup_dir: Path, scratch: Path) -> str:
    """Corrupt one DB and insert a marker audit event — on the COPY only."""
    shutil.copytree(backup_dir, scratch,
                    ignore=shutil.ignore_patterns("manifest.json"))
    notes = []
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    dbs = [rel for rel in manifest["files"] if Path(rel).suffix in DB_SUFFIXES]
    if dbs:
        # corrupt a NON-platform.db so the marker append below still has a live
        # target; platform.db alone → corrupt it and skip the marker honestly
        victim_rel = next((r for r in dbs if Path(r).name != "platform.db"), dbs[0])
        victim = scratch / victim_rel
        victim.write_bytes(b"drill: deliberate corruption " + bytes(64))
        notes.append(f"byte-corrupted {victim_rel}")
    plat = scratch / "platform.db"
    if plat.is_file():
        from harness.workflow.audit import append as audit_append
        from harness.workflow.db import connect
        con = connect(plat)
        audit_append(con, matter_id="restore-drill", actor="drill", action="marker",
                     target="tamper", inputs_digest="-", outputs_digest="-")
        con.close()
        notes.append("appended a marker audit event (divergence the restore must undo)")
    return "; ".join(notes) or "nothing to tamper (empty snapshot)"


def restore(backup_dir: Path, scratch: Path) -> None:
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir(parents=True)
    for src in backup_dir.rglob("*"):
        if (src.is_dir() or src.name == "manifest.json"
                or under(src, scratch)):
            continue
        dst = scratch / src.relative_to(backup_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def verify(backup_dir: Path, scratch: Path, failures: list[str]) -> str:
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    for rel, rec in manifest["files"].items():
        dst = scratch / rel
        if not dst.is_file():
            failures.append(f"restored file missing: {rel}")
        elif _sha256(dst) != rec["sha256"]:
            failures.append(f"sha256 mismatch after restore: {rel}")
        elif dst.suffix in DB_SUFFIXES:
            con = sqlite3.connect(dst)
            verdict = con.execute("PRAGMA integrity_check").fetchone()[0]
            con.close()
            if verdict != "ok":
                failures.append(f"integrity_check failed for {rel}: {verdict}")
    # the audit hash chain must still verify, and the tamper marker must be gone
    if (backup_dir / "platform.db").is_file():
        from harness.workflow.audit import verify as audit_verify
        from harness.workflow.db import connect
        con = connect(scratch / "platform.db")
        ok, why = audit_verify(con)
        con.close()
        if not ok:
            failures.append(f"audit hash chain broken after restore: {why}")
    for rel, tables in KNOWN_COUNTS.items():
        before = table_counts(backup_dir / Path(rel), tables)
        if not before:
            continue
        after = table_counts(scratch / Path(rel), tables)
        if before != after:
            failures.append(f"row-count divergence for {rel}: {before} -> {after}"
                            " (the restore did not fully undo the tamper)")
    # the upgrade drill: the restored store must migrate cleanly (06 Phase 10)
    from harness.migrate import migrate
    for r in migrate(scratch):
        if r.status != "absent" and r.to_version < 1:
            failures.append(f"migrate on restored store failed for {r.path}")
    return f"{len(manifest['files'])} files verified"


def main(argv: list[str] | None = None) -> int:
    from harness.paths import resolve_store_root
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None,
                    help="store root to drill (default: resolved store root)")
    ap.add_argument("--backup-dir", default=None,
                    help="snapshot destination (default: <store parent>/<store>-backup-<ts>)")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else Path(resolve_store_root()[0])
    if not root.is_dir():
        print(f"DRILL REFUSED: store root {root} does not exist", file=sys.stderr)
        return 2
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = (Path(args.backup_dir) if args.backup_dir
                  else root.parent / f"{root.name}-backup-{stamp}")
    if backup_dir.exists() and any(backup_dir.iterdir()):
        print(f"DRILL REFUSED: backup dir {backup_dir} exists and is not empty",
              file=sys.stderr)
        return 2
    scratch = backup_dir.with_name(backup_dir.name + "-restored")

    failures: list[str] = []
    try:
        manifest = snapshot(root, backup_dir)
    except sqlite3.DatabaseError as ex:
        print(f"DRILL FAILED at SNAPSHOT: {ex}", file=sys.stderr)
        return 1
    evidence = ""
    phases = [("TAMPER", lambda: tamper(backup_dir, scratch)),
              ("RESTORE", lambda: restore(backup_dir, scratch)),
              ("VERIFY", lambda: verify(backup_dir, scratch, failures))]
    notes = ""
    for phase, fn in phases:
        try:
            result = fn()
            if phase == "TAMPER":
                notes = result
            elif phase == "VERIFY":
                evidence = result
        except Exception as ex:  # the drill's contract: fail loud, name the phase
            print(f"DRILL FAILED at {phase}: {ex}", file=sys.stderr)
            return 1
    digest = _sha256(backup_dir / "manifest.json")

    print("=" * 64)
    print("RESTORE DRILL — evidence block")
    print(f"  when:        {manifest['ts']}")
    print(f"  live root:   {manifest['source']} (read-only throughout)")
    print(f"  snapshot:    {backup_dir} ({manifest['harness_version']})")
    print(f"  manifest:    sha256 {digest}")
    print(f"  tamper:      {notes}")
    print(f"  restored to: {scratch}")
    print(f"  verify:      {evidence}")
    if failures:
        for f in failures:
            print(f"  FAIL: {f}")
        print("=" * 64)
        print("DRILL FAILED", file=sys.stderr)
        return 1
    print("  verdict:     PASS — snapshot, tamper-detect, restore, verify, migrate all held")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
