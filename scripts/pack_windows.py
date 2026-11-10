# scripts/pack_windows.py
"""Stage + zip the Windows distribution (S7j-W step 2, spec 13 §2.1).

The product tree IS the repo tree: the zip carries src/ + data/ (routing, mount,
module-e, golden corpus) + three files staged at the zip root (R2): the installer,
the first-run verify + drive smoke, and PREREQUISITES.md. Excluded: the dev
substrate (.git, .venv, caches, SDD ledgers) and data/eval (internal run evidence,
not product). Output: dist/IronFleet-harness-<version>-windows.zip (dist/ is
gitignored — a build artifact, not source).

Usage:
  .venv/Scripts/python.exe scripts/pack_windows.py [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "src" / "harness" / "ops"
# The five files a fresh-machine user must see on top of the extracted zip:
# the Windows installer + its verify, the M11 Linux twins, and the dependency
# inventory. The zip name keeps "-windows" for accept_r2's fresh-machine
# contract, but the zip is the tri-OS distribution (same tree, all three OSes).
INSTALL_SRC = OPS / "install_windows.ps1"
VERIFY_SRC = OPS / "verify_windows_install.ps1"
INSTALL_LINUX_SRC = OPS / "install_linux.sh"
VERIFY_LINUX_SRC = OPS / "verify_linux_install.sh"
PREREQ_SRC = ROOT / "PREREQUISITES.md"

# Pruned by NAME anywhere in the tree; the dev substrate has no product meaning.
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".superpowers"}
# Pruned by PATH relative to the repo root.
SKIP_PATHS = {".git", ".venv", "dist", "build", Path("data") / "eval"}
# Pruned by SUFFIX anywhere: every .sqlite3 in the tree is dev run evidence
# (trace stores, research benches) — internal, not product.
SKIP_SUFFIXES = (".sqlite3",)


def iter_files(root: Path = ROOT):
    """Every file the distribution carries, with .venv/.git pruned during the walk."""
    for dirpath, dirnames, filenames in os_walk(root):
        here = Path(dirpath)
        rel = here.relative_to(root)
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_NAMES and (rel / d) not in SKIP_PATHS
                       and d not in SKIP_PATHS]
        for f in sorted(filenames):
            if not f.endswith(SKIP_SUFFIXES):
                yield here / f


def os_walk(root: Path):
    """os.walk with posix/nt-safe pruning — factored so tests can monkeypatch nothing."""
    import os
    return os.walk(root)


def pack(root: Path = ROOT, out_dir: Path | None = None) -> Path:
    import harness
    name = f"IronFleet-harness-{harness.__version__}-windows"
    out_dir = Path(out_dir) if out_dir else root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{name}.zip"
    for label, src in (("install", INSTALL_SRC), ("verify", VERIFY_SRC),
                       ("prerequisites", PREREQ_SRC)):
        if not src.is_file():
            raise FileNotFoundError(f"{label} artifact missing: {src}")
    seen: set[str] = set()

    def stage(p: Path, arc: str) -> None:
        # the tree walk already carries the ops scripts at their src paths; the
        # zip-root copy is the user-facing one — first write wins, no duplicates
        if arc not in seen:
            z.write(p, arc)
            seen.add(arc)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in iter_files(root):
            # posix arcnames: Path's backslashes would both defeat the seen-set AND
            # produce entries macOS/R6 cannot extract as a tree
            stage(p, (Path(name) / p.relative_to(root)).as_posix())
        stage(INSTALL_SRC, f"{name}/install_windows.ps1")
        stage(VERIFY_SRC, f"{name}/verify_windows_install.ps1")
        stage(INSTALL_LINUX_SRC, f"{name}/install_linux.sh")
        stage(VERIFY_LINUX_SRC, f"{name}/verify_linux_install.sh")
        stage(PREREQ_SRC, f"{name}/PREREQUISITES.md")
    # M11 (plan ruling, 2026-11-10): the release ships UNSIGNED + sha256-checksummed —
    # the checksum travels with the artifact, verify before install
    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    (out_dir / f"{zip_path.name}.sha256").write_text(
        f"{h.hexdigest()}  {zip_path.name}\n", encoding="utf-8")
    return zip_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="output dir (default: dist/)")
    args = ap.parse_args(argv)
    zp = pack(out_dir=Path(args.out) if args.out else None)
    print(zp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
