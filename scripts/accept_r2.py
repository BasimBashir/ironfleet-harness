"""R2 acceptance -- the Windows installer (spec 15 section 4).

Every check runs on this Windows box; exit 0 requires all five.

  C1 the zip builds: install/verify/PREREQUISITES at the root, posix arcnames,
     no duplicate entries, no data/eval, no dev *.sqlite3 trace stores
  C2 fresh extract -> installer exit 0 -> harness --version from the FRESH venv;
     the store-encryption branch taken is RECORDED (this box: -AcceptUnencryptedStore,
     the CR-7 deviation, printed -- never silent). Negative control: a fresh
     HARNESS_HOME with NO flag must exit nonzero naming the BitLocker gate (only
     when this host's store drive is in fact unencrypted -- the driver probes first
     and records the branch rather than asserting blind).
  C3 pin enforcement: a PATH-shimmed opencode reporting a wrong version makes
     verify_windows_install.ps1 exit nonzero NAMING the drift
  C4 first-run drive smoke, LIVE: verify_windows_install.ps1 -WithDriveSmoke
     against real Ollama (opencode startup hang retried once); the smoke's trace
     row honest: provider ollama-local, verified=0 (CR-3)
  C5 the doc-drift tests pass (PREREQUISITES.md == code pins)

The live layer DEFERS to verify_windows_install.ps1 -- that script defines the bar
(pin, autoupdate, store, models); the driver runs it rather than restating it.

Usage: .venv/Scripts/python.exe scripts/accept_r2.py
"""
from __future__ import annotations

import argparse
import collections
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv/Scripts/python.exe"
PACK = ROOT / "scripts/pack_windows.py"
INSTALL_PS = "install_windows.ps1"
VERIFY_PS = "verify_windows_install.ps1"
PREREQ_MD = "PREREQUISITES.md"
WORKSPACE = Path.home() / "spike-ws-a1" / "opencode-a1"   # harness drive's default

# opencode startup hang (~2-in-7 on some boxes): the verify script does NOT retry;
# the driver owns the retry, exactly like the S7j-W live drivers.
SMOKE_ATTEMPTS = 2
SMOKE_TIMEOUT_S = 1200
INSTALL_TIMEOUT_S = 1800


def _ps(script: Path, *args: str, env: dict | None = None, timeout: int = INSTALL_TIMEOUT_S):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(script), *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=timeout)


def check_c1(work: Path) -> list[str]:
    problems: list[str] = []
    out = subprocess.run([str(PY), str(PACK), "--out", str(work)], capture_output=True,
                         text=True)
    if out.returncode != 0:
        return [f"pack_windows.py failed: {out.stderr.strip()[:300]}"]
    zips = list(work.glob("IronFleet-harness-*-windows.zip"))
    if len(zips) != 1:
        return [f"expected exactly one zip in {work}, got {zips}"]
    with zipfile.ZipFile(zips[0]) as z:
        names = z.namelist()
        top = zips[0].stem
        for root_file in (INSTALL_PS, VERIFY_PS, PREREQ_MD):
            if f"{top}/{root_file}" not in names:
                problems.append(f"zip root missing {root_file}")
        dupes = [n for n, c in collections.Counter(names).items() if c > 1]
        if dupes:
            problems.append(f"duplicate zip entries: {dupes[:3]}")
        if [n for n in names if "\\" in n]:
            problems.append("backslash arcnames (would not extract as a tree on macOS/R6)")
        if any("/data/eval/" in n for n in names):
            problems.append("data/eval rode along")
        if any(n.endswith(".sqlite3") for n in names):
            problems.append("dev *.sqlite3 trace stores rode along")
    print(f"  zip: {zips[0].name} ({len(names)} entries)")
    return problems


def _store_drive_protected() -> bool | None:
    """True/False per manage-bde; None when undeterminable (Home edition etc.)."""
    bde = shutil.which("manage-bde.exe")
    if not bde:
        return None
    store = os.environ.get("HARNESS_HOME") or str(
        Path(os.environ["LOCALAPPDATA"]) / "IronFleet" / "harness")
    r = subprocess.run([bde, "-status", Path(store).drive or "C:"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return "Protection Status: Protection On" in r.stdout


def check_c2(work: Path) -> list[str]:
    problems: list[str] = []
    zips = list(work.glob("IronFleet-harness-*-windows.zip"))
    extract = work / "fresh-machine"
    with zipfile.ZipFile(zips[0]) as z:
        z.extractall(extract)
    root = extract / zips[0].stem

    # the recorded branch: is this host's store drive even BitLocker-protected?
    protected = _store_drive_protected()
    flag_needed = protected is not False  # None (undeterminable) also needs the flag
    args = (["-AcceptUnencryptedStore"] if flag_needed else [])
    print(f"  store drive BitLocker-protected: {protected} -> "
          f"installer run with -AcceptUnencryptedStore={flag_needed}")
    r = _ps(root / INSTALL_PS, *args)
    if r.returncode != 0:
        return [f"installer exit {r.returncode}: ...{r.stdout[-400:]}{r.stderr[-200:]}"]
    if flag_needed and "CR-7" not in r.stdout:
        problems.append("unencrypted-store branch ran but the CR-7 deviation was not printed")
    ver = subprocess.run([str(root / ".venv/Scripts/harness.exe"), "--version"],
                         capture_output=True, text=True)
    if ver.returncode != 0 or "0.1.0" not in ver.stdout:
        problems.append(f"fresh-venv harness --version: exit {ver.returncode} out={ver.stdout!r}")
    else:
        print(f"  fresh venv: {ver.stdout.strip()}")

    # negative control: a fresh HARNESS_HOME with NO flag must hit the BitLocker
    # gate. Runs whenever the drive is not PROVEN protected (Protection Off, or
    # undeterminable -- fail-closed is the same contract either way).
    if protected is not True:
        env = dict(os.environ, HARNESS_HOME=str(work / "fresh-store"))
        neg = _ps(root / INSTALL_PS, env=env)
        if neg.returncode == 0:
            problems.append("negative control FAILED: unencrypted fresh store was accepted silently")
        elif "BitLocker" not in neg.stdout and "manage-bde" not in neg.stdout:
            problems.append(f"negative control failed for the wrong reason: ...{neg.stdout[-300:]}")
        elif (work / "fresh-store").exists():
            problems.append("negative control: the refused store tree was created anyway")
        else:
            print(f"  negative control: fresh store refused (drive protected={protected}), nothing created")
    else:
        print("  negative control SKIPPED (store drive protected) -- recorded")
    return problems


def check_c3(root: Path, work: Path) -> list[str]:
    shim = work / "shim"
    shim.mkdir(exist_ok=True)
    (shim / "opencode.cmd").write_text("@echo 9.9.9\r\n", encoding="ascii")
    env = dict(os.environ, PATH=f"{shim}{os.pathsep}{os.environ['PATH']}")
    r = _ps(root / VERIFY_PS, "-AcceptUnencryptedStore", env=env)
    if r.returncode == 0:
        return ["pin shim: verify script exited 0 despite a wrong-version opencode"]
    if "drift" not in r.stdout:
        return [f"pin shim failed, but not naming drift: ...{r.stdout[-300:]}"]
    print(f"  shim opencode 9.9.9 -> FAIL naming drift (exit {r.returncode})")
    return []


def check_c4(root: Path) -> list[str]:
    problems: list[str] = []
    trace_db = WORKSPACE / "trace.db"
    rows_before = 0
    if trace_db.exists():
        with sqlite3.connect(trace_db) as cx:
            rows_before = cx.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0]
    for attempt in range(1, SMOKE_ATTEMPTS + 1):
        print(f"  drive smoke attempt {attempt}/{SMOKE_ATTEMPTS} (real Ollama + opencode)...")
        try:
            r = _ps(root / VERIFY_PS, "-WithDriveSmoke", "-AcceptUnencryptedStore",
                    timeout=SMOKE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            r = None
        if r is not None and r.returncode == 0:
            break
        tail = (r.stdout[-300:] if r is not None else "TIMEOUT")
        print(f"    attempt {attempt} failed: ...{tail}")
        if attempt == SMOKE_ATTEMPTS:
            return problems + [f"drive smoke failed {SMOKE_ATTEMPTS}x; last: ...{tail}"]
        print("    (known opencode startup hang ~2-in-7 -- retrying)")
    if not trace_db.exists():
        return problems + [f"no trace store at {trace_db} after the smoke"]
    with sqlite3.connect(trace_db) as cx:
        rows = cx.execute(
            "SELECT provider, model, verified, task_class FROM dispatches "
            "ORDER BY ts DESC LIMIT 5").fetchall()
        rows_after = cx.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0]
    if rows_after <= rows_before:
        return problems + [f"no new dispatch row after the smoke ({rows_before} -> {rows_after})"]
    prov, model, verified, task_class = rows[0]
    if prov != "ollama-local" or verified != 0:
        problems.append(f"smoke trace row not honest: provider={prov} verified={verified}")
    print(f"  traced: {task_class} via {prov}/{model} verified={verified} "
          f"(rows {rows_before} -> {rows_after})")
    return problems


def check_c5() -> list[str]:
    r = subprocess.run([str(PY), "-m", "pytest", "-q",
                        "tests/test_prerequisites_doc.py", "tests/test_pack_windows.py"],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        return [f"doc-drift/pack tests failed: {r.stdout[-400:]}"]
    print("  " + r.stdout.strip().splitlines()[-1])
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep", action="store_true", help="keep the temp work dir")
    args = ap.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="accept-r2-"))
    print(f"work dir: {work}")

    def extract_root() -> Path:
        return next((work / "fresh-machine").glob("IronFleet-harness-*-windows"))

    checks = [("C1", lambda: check_c1(work)),
              ("C2", lambda: check_c2(work)),
              ("C3", lambda: check_c3(extract_root(), work)),
              ("C4", lambda: check_c4(extract_root())),
              ("C5", check_c5)]
    failed = False
    for name, fn in checks:
        print(f"==> {name}")
        try:
            problems = fn()
        except Exception as ex:                      # a check that crashed is a failure
            problems = [f"{type(ex).__name__}: {ex}"]
        if problems:
            failed = True
            for p in problems:
                print(f"  FAIL {name}: {p}")
        else:
            print(f"  {name} PASS")
    if failed:
        print(f"work dir kept for inspection: {work}")
    elif not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    print("R2 ACCEPTANCE: FAIL" if failed else "R2 ACCEPTANCE: PASS (exit 0)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
