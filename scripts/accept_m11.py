# scripts/accept_m11.py — M11 acceptance driver (reliability + deployment).
"""Three-valued, never overclaims:

  0  every check ran and passed AND the three fresh-OS records are filled
     (data/eval/M11-FRESHOS/<os>/RECORD.md with no blank fields left)
  2  static checks passed; the fresh-OS records are missing or still blank —
     due-for-owner, NO verdict is written (the S7g-W precedent: no verdict on a
     result not obtained)
  1  a check that CAN run on this host failed. Never means "owner-only step
     skipped" — that is exit 2.

  C1 migration: the legacy-store fixture migrates cleanly and idempotently;
                `harness migrate --root` exits 0 (patterns from test_migrate.py)
  C2 drill: restore_drill.py exits 0 on a fixture root (live-store run is the
            owner's cadence — accept_m11 stays static + fixture-only)
  C3 crashlog + no-telemetry: pytest tests/test_crashlog.py tests/test_no_telemetry.py
  C4 packaging: pytest tests/test_pack_windows.py (zip root, sha256 sidecar,
                bash -n, substrate exclusion)
  C5 docs: the five T7 docs + runbook exist; the legal three carry DRAFT +
           PENDING R-1; the runbook carries the unsigned+checksummed statement
  C6 Linux installer contract: bash -n on the three ops .sh; installer delegates
     the store to p07_setup_linux.sh, verifier to p07_verify_linux.sh; the packer
     stages both installers at zip root
  C7 versioning: pytest tests/test_prerequisites_doc.py (single-sourced version,
     CHANGELOG covers it)

  Fresh-OS legs (owner, per OS): install from the checksummed zip, first case,
  restart verify, restore drill evidence — recorded in the OS's RECORD.md. The
  driver writes the template when missing so the operator fills a sheet, not a
  blank page.

Usage: .venv/Scripts/python.exe scripts/accept_m11.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

PY = sys.executable
FRESHOS_DIR = ROOT / "data" / "eval" / "M11-FRESHOS"
CAPABILITY = "M11 reliability + deployment"
BLANK = "___________"  # any surviving blank field = the record is not a record

RECORD_HEADER = """# M11 fresh-OS record — {os}

> Owner leg of M11's done-when: install from the checksummed zip on a truly fresh
> {os_fresh} box, run the first case, restart-verify, and capture the restore drill's
> evidence block. Fill every field; replace nothing above the line.

- Date: ___________
- Box (what was actually fresh about it): ___________
- Version under test: ___________ (harness --version)

## 1. Install from the checksummed zip

- zip + .sha256 verified (`shasum -a 256 -c` / `Get-FileHash`), output tail:
  ```
  ___________________________
  ```
- installer command + exit: ___________
- installer output tail (pin enforced / autoupdate:false / store gate):
  ```
  ___________________________
  ```

## 2. First case

- command: `harness drive --matter-ref ___________ --task-class extraction`
- exit + one traced dispatch in trace.db: ___________

## 3. Restart verify

- verify command + exit: ___________
- output tail:
  ```
  ___________________________
  ```

## 4. Restore drill evidence

Paste the drill's evidence block verbatim:
```
___________________________
___________________________
```

Record filled by: ___________
"""

OS_MAP = {"windows": "Windows 11", "linux": "Linux", "macos": "macOS"}


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          cwd=str(ROOT), **kw)


def _pytest(spec: str, problems: list[str], label: str) -> None:
    r = _run([PY, "-m", "pytest", "-q", *spec.split()])
    if r.returncode != 0:
        tail = (r.stdout or r.stderr).strip().splitlines()[-6:]
        problems.append(f"{label}: pytest exit {r.returncode} — " + " | ".join(tail))


def check_c1_migration(problems: list[str]) -> None:
    """Legacy store gains columns, twice (idempotent); CLI exit 0."""
    import sqlite3

    from harness.cli import main as cli_main
    from harness.migrate import SCHEMA_VERSION, migrate
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db = root / "trace.db"
        con = sqlite3.connect(db)
        con.executescript("""
        CREATE TABLE dispatches(
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
          matter_ref TEXT, task_class TEXT, classification TEXT,
          provider TEXT, model TEXT, weights_revision TEXT, engine TEXT, verified INTEGER,
          tokens_in INTEGER, tokens_out INTEGER, tokens_cache INTEGER,
          latency_ms INTEGER, status TEXT, error TEXT);
        """)
        con.execute(
            "INSERT INTO dispatches(ts, matter_ref) VALUES('2026-01-01T00:00:00Z','m1')")
        con.commit()
        con.close()
        first = {r.path.name: r for r in migrate(root)}
        rep = first["trace.db"]
        if rep.status != "ok" or rep.to_version != SCHEMA_VERSION:
            problems.append("C1: legacy trace.db did not reach SCHEMA_VERSION")
        second = {r.path.name: r for r in migrate(root)}["trace.db"]
        if second.steps_applied != 0:
            problems.append("C1: migrate not idempotent (second run applied steps)")
        if cli_main(["migrate", "--root", str(root)]) != 0:
            problems.append("C1: harness migrate CLI did not exit 0")


def check_c2_drill(problems: list[str]) -> None:
    """The drill passes on a fixture root built with the real store classes."""
    from harness.trace import DispatchRecord, TraceStore
    from scripts.restore_drill import main as drill
    from harness.workflow.audit import append as audit_append
    from harness.workflow.db import connect
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "store"
        root.mkdir()
        con = connect(root / "platform.db")
        audit_append(con, matter_id="m1", actor="accept", action="test", target="x",
                     inputs_digest="i", outputs_digest="o")
        con.close()
        TraceStore(root / "trace.db").append(DispatchRecord(
            matter_ref="m1", task_class="extraction", classification="LOCAL_ONLY",
            provider="ollama", model="thomson1-chat:latest"))
        (root / "matters" / "m1").mkdir(parents=True)
        (root / "matters" / "m1" / "matter.json").write_text("{}", encoding="utf-8")
        rc = drill(["--root", str(root), "--backup-dir", str(Path(td) / "backup")])
        if rc != 0:
            problems.append(f"C2: drill exit {rc} on fixture root")


def check_c3_crashlog_notel(problems: list[str]) -> None:
    _pytest("tests/test_crashlog.py tests/test_no_telemetry.py", problems, "C3")


def check_c4_packaging(problems: list[str]) -> None:
    _pytest("tests/test_pack_windows.py", problems, "C4")


def check_c5_docs(problems: list[str]) -> None:
    must_exist = [
        "docs/help/firm-mode.md", "docs/help/selfrep-mode.md",
        "docs/legal/TERMS-DRAFT.md", "docs/legal/PRIVACY-DRAFT.md",
        "docs/legal/VERIFICATION-DISCLOSURE-DRAFT.md",
        "docs/enterprise/11-release-runbook.md",
    ]
    bodies: dict[str, str] = {}
    for rel in must_exist:
        p = ROOT / rel
        if not p.is_file():
            problems.append(f"C5: missing {rel}")
        else:
            bodies[rel] = p.read_text(encoding="utf-8")
    for rel in must_exist:
        if rel.startswith("docs/legal/") and rel in bodies:
            body = bodies[rel]
            if "DRAFT" not in body or "PENDING R-1" not in body:
                problems.append(f"C5: {rel} lost its DRAFT — PENDING R-1 banner")
    rb = bodies.get("docs/enterprise/11-release-runbook.md", "")
    if rb and ("unsigned" not in rb or "sha256" not in rb):
        problems.append("C5: runbook lacks the unsigned+checksummed statement")


def check_c6_linux_contract(problems: list[str]) -> None:
    bash = shutil.which("bash")
    if not bash:
        problems.append("C6: no bash on PATH — cannot prove the installer contracts")
        return
    ops = ROOT / "src" / "harness" / "ops"
    for name in ("install_linux.sh", "verify_linux_install.sh", "pack_macos.sh"):
        r = _run([bash, "-n", str(ops / name)])
        if r.returncode != 0:
            problems.append(f"C6: {name} fails bash -n: {r.stderr.strip()[:120]}")
    inst = (ops / "install_linux.sh").read_text(encoding="utf-8")
    ver = (ops / "verify_linux_install.sh").read_text(encoding="utf-8")
    pw = (ROOT / "scripts" / "pack_windows.py").read_text(encoding="utf-8")
    if "p07_setup_linux.sh" not in inst:
        problems.append("C6: installer does not delegate the store to p07_setup_linux.sh")
    if "p07_verify_linux.sh" not in ver:
        problems.append("C6: verifier does not delegate deep checks to p07_verify_linux.sh")
    if "install_linux.sh" not in pw or "verify_linux_install.sh" not in pw:
        problems.append("C6: pack_windows.py does not stage the Linux installers at zip root")


def check_c7_versioning(problems: list[str]) -> None:
    _pytest("tests/test_prerequisites_doc.py", problems, "C7")


def fresh_os_due() -> list[str]:
    """Write missing RECORD templates; return the due-for-owner list (a missing
    or blank-filled record is not a record)."""
    due: list[str] = []
    for os_name, os_fresh in OS_MAP.items():
        d = FRESHOS_DIR / os_name
        d.mkdir(parents=True, exist_ok=True)
        rec = d / "RECORD.md"
        if not rec.is_file():
            rec.write_text(RECORD_HEADER.format(os=os_name, os_fresh=os_fresh),
                           encoding="utf-8")
            print(f"  template written: {rec}")
            due.append(f"{rec} absent (template written)")
            continue
        if BLANK in rec.read_text(encoding="utf-8"):
            due.append(f"{rec} still has blank fields")
    return due


def main() -> int:
    problems: list[str] = []
    checks = [
        ("C1 migration", check_c1_migration),
        ("C2 drill", check_c2_drill),
        ("C3 crashlog+no-telemetry", check_c3_crashlog_notel),
        ("C4 packaging", check_c4_packaging),
        ("C5 docs", check_c5_docs),
        ("C6 linux installer contract", check_c6_linux_contract),
        ("C7 versioning", check_c7_versioning),
    ]
    print(f"== M11 acceptance — {CAPABILITY}")
    for label, fn in checks:
        sub: list[str] = []
        try:
            fn(sub)
        except Exception as ex:  # a driver bug is a check failure, never a pass
            sub.append(f"raised {type(ex).__name__}: {ex}")
        for p in sub:
            problems.append(f"{label}: {p}")
            print(f"  [{label}] FAIL {p}")
        if not sub:
            print(f"  [{label}] ok")
    due = fresh_os_due()
    if problems:
        print("M11 acceptance FAILED", file=sys.stderr)
        return 1
    if due:
        for d in due:
            print(f"  [fresh-OS] due-for-owner: {d}")
        print("M11 static checks pass; fresh-OS records outstanding — "
              "due-for-owner, no verdict written", file=sys.stderr)
        return 2
    print("M11 acceptance PASS (all checks + all three fresh-OS records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
