"""S7g acceptance — A-6 macOS packaging (spec 10, section 10).

Exit codes are THREE-VALUED and must not overclaim:

  0  every check ran and passed — ONLY reachable on a Mac
  2  static checks passed, live checks were not executable on this host.
     This is the S7g-W outcome on Windows: due-for-Mac, and NO verdict is written,
     exactly as S7c's --skip-parity DEBUG mode exits 2 rather than report a result
     it did not obtain.
  1  a check that CAN run on this host failed. Never used to mean "Mac-only step
     skipped" — that is exit 2.

  C1 resolve_store_root answers for every OS with a labelled source
  C2 every plist parses and carries the keys launchd/Finder expect
  C3 the manifest is self-consistent and every pin is non-empty
  C4 pack_macos.sh refuses off macOS and builds nothing
  C5 the staged tree matches the manifest, with the binary slot still a placeholder

  Live (S7g-M, macOS only): the pinned opencode bootstrapped and drift-free; the
  launchd agents loaded; a real dispatch traced end-to-end from the installed package;
  the store on the encrypted volume with its source recorded.
  The live layer DEFERS to src/harness/ops/verify_macos_install.sh — that script is the
  artifact that defines the bar (drift, autoupdate, agent loaded, proxy up, store
  source); the driver runs it rather than restating a weaker version of it.

Usage: .venv/Scripts/python.exe scripts/accept_s7g.py
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))          # stand_up_opencode.py lesson

from harness import paths
from harness.packaging import macdist
from harness.packaging.macdist import (
    APP_NAME, DUE_FOR_MAC, LAUNCHD_LABEL, PINS, is_binary_slot_placeholder,
    manifest_entries, stage_distribution, validate_distribution,
)

CAPABILITY = "A-6 macOS packaging"
PACK_SCRIPT = ROOT / "src/harness/ops/pack_macos.sh"
VERIFY_SCRIPT = ROOT / "src/harness/ops/verify_macos_install.sh"

_PLATFORMS = ("Darwin", "Windows", "Linux")


def _anchored(path: Path) -> bool:
    """Absolute under ANY flavour's rules — the store root is never a relative path.

    C1 checks every OS's branch from a single host, and resolve_store_root builds each
    branch from this HOST's Path.home()/LOCALAPPDATA, so a branch's shape is not
    necessarily its own OS's native shape: asked from Windows, the macOS root
    /Volumes/IronFleetPriv/harness reads as 'not absolute' purely for lacking a drive,
    and the Linux branch (Path.home() on this box) is Windows-shaped, not Posix. The
    property C1 can honestly assert across all of that is 'never relative', asked under
    any flavour.
    """
    return path.is_absolute() or PurePosixPath(path).is_absolute() \
        or PureWindowsPath(path).is_absolute()


def check_c1() -> list[str]:
    """resolve_store_root answers for every OS with a labelled source.

    Monkeypatched per platform rather than trusting platform.system() to be Darwin on a
    Windows box: the property under test is that each BRANCH works, not that this host
    happens to be on one of them.
    """
    problems: list[str] = []
    real = paths.resolve_store_root
    real_system = paths.platform.system
    real_volume_present = paths._macos_volume_present
    try:
        for system in _PLATFORMS:
            # Both patches are RESTORED afterwards: leaving _macos_volume_present patched
            # would make the real-host call below report the volume present on a Mac that
            # does not have it mounted.
            paths.platform.system = lambda _s=system: _s      # noqa: PLW0642
            paths._macos_volume_present = lambda: True
            try:
                root, source = real()
                if not _anchored(root):
                    problems.append(f"{system}: root is not absolute ({root})")
                if not source:
                    problems.append(f"{system}: resolve_store_root returned an empty source")
            except Exception as exc:                           # noqa: BLE001
                problems.append(f"{system}: resolve_store_root raised {exc!r}")
    finally:
        paths.platform.system = real_system
        paths._macos_volume_present = real_volume_present
    # the real host too, unpatched — the live caller's answer must be labelled as well
    try:
        root, source = real()
        if not _anchored(root):
            problems.append("this host: resolve_store_root returned a relative root")
        if not source:
            problems.append("this host: resolve_store_root returned an empty source")
    except Exception as exc:                                   # noqa: BLE001
        problems.append(f"this host: resolve_store_root raised {exc!r}")
    return problems


def check_c2(root: Path) -> list[str]:
    """Every plist parses and satisfies the schema (C2 covers both plist kinds)."""
    return [p for p in validate_distribution(root)
            if "does not parse" in p or "launchd plist" in p or "Info.plist" in p
            or "duplicate launchd" in p]


def check_c3(root: Path) -> list[str]:
    """Manifest self-consistency plus non-empty pins."""
    problems: list[str] = []
    if not PINS.get("opencode"):
        problems.append("PINS['opencode'] is empty — the installer would bootstrap nothing")
    if PINS.get("autoupdate") is not True and "autoupdate" not in PINS:
        problems.append("PINS['autoupdate'] is missing")
    problems += [p for p in validate_distribution(root)
                 if "missing staged file" in p or "unexpected staged file" in p
                 or "drifted" in p]
    return problems


def check_c4() -> list[str]:
    """pack_macos.sh refuses off macOS and builds nothing.

    The guard is the reason a Windows run cannot stage a placeholder binary and call it
    a build. If bash is unavailable this is REPORTED, not skipped: a check that cannot
    run is not a check that passed.
    """
    # Resolve the interpreter rather than passing a bare "bash": on this box PATH also
    # exposes WSL's bash, which cannot open a C:\ path and returns 127 — that would read
    # as a guard failure that never happened, and the driver would exit 1 on a Windows
    # host where the spec requires exit 2. shutil.which selects Git Bash, the same
    # interpreter tests/test_pack_macos.py gates its skip on.
    bash_bin = shutil.which("bash")
    if not bash_bin:
        return [f"cannot prove the pack_macos.sh guard: bash not found on PATH"]
    r = subprocess.run([bash_bin, str(PACK_SCRIPT)], capture_output=True, text=True,
                       cwd=ROOT)
    if r.returncode != 2:
        return [f"pack_macos.sh exited {r.returncode} on {platform.system()} "
                f"(expected 2 {DUE_FOR_MAC})"]
    if DUE_FOR_MAC not in (r.stderr + r.stdout):
        return [f"pack_macos.sh exited 2 without the {DUE_FOR_MAC} message"]
    if (ROOT / "dist").exists():
        return ["pack_macos.sh created a dist/ tree off macOS — the guard must run first"]
    return []


def check_c5(root: Path) -> list[str]:
    """The staged tree matches the manifest and the binary slot is still a placeholder.

    The placeholder is what makes a Windows staging build honestly labelled 'not a
    build': complete tree, one native thing missing, and a note in its place.
    """
    problems = [p for p in validate_distribution(root)
                if "missing staged file" in p or "unexpected staged file" in p]
    app = root / APP_NAME
    if not app.is_dir():
        return problems + [f"no staged {APP_NAME} under {root}"]
    if not is_binary_slot_placeholder(app):
        # On a Mac this is expected AFTER the build; in the S7g-W static phase the slot
        # must still be the placeholder, or the tree is claiming a binary it does not have.
        problems.append("the MacOS binary slot is not the placeholder — a native binary "
                        "is present, which a Windows staging build cannot produce")
    return problems


def _live_checks() -> list[str]:
    """S7g-M. Executable only on macOS; defers to verify_macos_install.sh.

    The bar for exit 0 is spec §10: the pinned opencode drift-free, autoupdate off in the
    global config, the egress-proxy agent loaded and reachable, the store on the encrypted
    volume with its source recorded. verify_macos_install.sh checks exactly those, so the
    decisive evidence comes from RUNNING it — restating a weaker version here (say, that
    opencode/codesign/launchctl merely exist on PATH) would grant ACCEPTED to a Mac
    session whose opencode had drifted, whose agent was never loaded, and whose store had
    fallen back to ~/Library. codesign presence stays as a prerequisite note, since
    signing needs Xcode and the script does not check for it.
    """
    problems: list[str] = []
    if not shutil.which("codesign"):
        problems.append("codesign not found — Xcode Command Line Tools required before "
                        "the S7g-M build can sign (prerequisite)")
    # Same interpreter resolution as check_c4: a bare "bash" is WSL on this dev box and
    # cannot open a C:\ path.
    bash_bin = shutil.which("bash")
    if not bash_bin:
        problems.append("cannot run verify_macos_install.sh: bash not found on PATH "
                        "(S7g-M)")
        return problems
    env = dict(os.environ)
    env["IRONFLEET_ROOT"] = str(ROOT)          # the script's own ROOT resolution style
    # The script imports harness.packaging.macdist and harness.paths via python3, so the
    # repo must be importable in the subprocess — replicate the sys.path insert above.
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (*env.get("PYTHONPATH", "").split(os.pathsep), str(ROOT)) if p)
    r = subprocess.run([bash_bin, str(VERIFY_SCRIPT)], capture_output=True, text=True,
                       cwd=ROOT, env=env)
    if r.returncode != 0:
        problems.append(f"verify_macos_install.sh exited {r.returncode} (S7g-M)")
    # The script may print FAIL: lines and still exit 0 on some future edit; a FAIL line
    # is a defect either way, so scan the output independently of the exit code.
    for line in (r.stdout + r.stderr).splitlines():
        if line.startswith("FAIL:"):
            problems.append(f"verify_macos_install.sh: {line.strip()}")
    return problems


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        # Stage into a scratch dir, never the repo: check_c4 asserts pack_macos.sh
        # leaves no dist/ behind, and a driver that created its own dist/ would make
        # that assertion about its own output.
        scratch = Path(td) / "dist"
        stage_distribution(scratch)

        problems: list[str] = []
        problems += check_c1()
        problems += check_c2(scratch)
        problems += check_c3(scratch)
        problems += check_c4()
        problems += check_c5(scratch)

        print("", file=sys.stderr)
        for system in _PLATFORMS:
            print(f"  [C1] resolver branch checked: {system}", file=sys.stderr)
        print(f"  [C2] plists parse + schema ({LAUNCHD_LABEL} + Info.plist)", file=sys.stderr)
        print(f"  [C3] manifest consistent; opencode pinned to {PINS['opencode']}; "
              f"autoupdate={PINS['autoupdate']}", file=sys.stderr)
        print(f"  [C4] pack_macos.sh guard: refuses off macOS, builds nothing", file=sys.stderr)
        print(f"  [C5] staged tree matches the manifest; binary slot is the placeholder",
              file=sys.stderr)

        if problems:
            for p in problems:
                print(f"  FAIL  {p}", file=sys.stderr)
            print(f"[accept-s7g] REJECTED: {len(problems)} problem(s) ({CAPABILITY})",
                  file=sys.stderr)
            return 1

        if platform.system() != "Darwin":
            # THE HONEST OUTCOME: the static layer is proven, the live layer is not
            # executable here. No verdict is written for checks that did not run.
            print(f"[accept-s7g] STATIC LAYER PROVEN on {platform.system()}; live layer "
                  f"{DUE_FOR_MAC} — no verdict written.", file=sys.stderr)
            return 2

        live = _live_checks()
        if live:
            for p in live:
                print(f"  FAIL  {p}", file=sys.stderr)
            print(f"[accept-s7g] REJECTED on macOS: live layer incomplete ({CAPABILITY})",
                  file=sys.stderr)
            return 1

        print("[accept-s7g] ACCEPTED: static layer + macOS live layer "
              f"({CAPABILITY})", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
