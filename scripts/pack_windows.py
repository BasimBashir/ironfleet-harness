# scripts/pack_windows.py
"""Stage + zip the Windows distribution (S7j-W step 2, spec 13 §2.1).

The product tree IS the repo tree: the zip carries src/ + data/ (routing, mount,
module-e, golden corpus) + the install script at the zip root. Excluded: the dev
substrate (.git, .venv, caches, SDD ledgers) and data/eval (internal run evidence,
not product). Output: dist/IronFleet-harness-<version>-windows.zip (dist/ is
gitignored — a build artifact, not source).

Usage:
  .venv/Scripts/python.exe scripts/pack_windows.py [--out DIR]
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SRC = ROOT / "src" / "harness" / "ops" / "install_windows.ps1"

# Pruned by NAME anywhere in the tree; the dev substrate has no product meaning.
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".superpowers"}
# Pruned by PATH relative to the repo root.
SKIP_PATHS = {".git", ".venv", "dist", "build", Path("data") / "eval"}


def iter_files(root: Path = ROOT):
    """Every file the distribution carries, with .venv/.git pruned during the walk."""
    for dirpath, dirnames, filenames in os_walk(root):
        here = Path(dirpath)
        rel = here.relative_to(root)
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_NAMES and (rel / d) not in SKIP_PATHS
                       and d not in SKIP_PATHS]
        for f in sorted(filenames):
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
    if not INSTALL_SRC.is_file():
        raise FileNotFoundError(f"install script missing: {INSTALL_SRC}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in iter_files(root):
            z.write(p, Path(name) / p.relative_to(root))
        z.write(INSTALL_SRC, Path(name) / "install_windows.ps1")
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
