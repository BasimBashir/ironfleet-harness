"""The Windows distribution zip (R2): the three user-facing files sit at the zip
root — install script, first-run verify + drive smoke, prerequisites doc — and the
dev substrate (data/eval) never rides along."""
from __future__ import annotations

import zipfile
from collections import Counter
from pathlib import Path

import pytest

import harness
from scripts.pack_windows import pack


def test_zip_carries_install_verify_and_prerequisites_at_root(tmp_path):
    zp = pack(out_dir=tmp_path)
    assert zp.name == f"IronFleet-harness-{harness.__version__}-windows.zip"
    top = f"IronFleet-harness-{harness.__version__}-windows"
    all_names = zipfile.ZipFile(zp).namelist()
    for root_file in ("install_linux.sh", "verify_linux_install.sh",
                      "install_windows.ps1", "verify_windows_install.ps1",
                      "PREREQUISITES.md"):
        assert f"{top}/{root_file}" in all_names, root_file
    # no duplicate entries (the ops-tree copies stay at their src paths), and every
    # arcname is posix — backslash names would not extract as a tree on macOS (R6)
    assert not [n for n, c in Counter(all_names).items() if c > 1]
    assert not [n for n in all_names if "\\" in n]


def test_zip_ships_with_a_matching_sha256(tmp_path):
    # M11: unsigned release, checksummed — the digest beside the zip must match
    import hashlib
    zp = pack(out_dir=tmp_path)
    sidecar = tmp_path / f"{zp.name}.sha256"
    digest, _, name = sidecar.read_text(encoding="utf-8").partition("  ")
    assert name.strip() == zp.name
    h = hashlib.sha256()
    with open(zp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    assert digest == h.hexdigest()


def test_zip_excludes_dev_substrate(tmp_path):
    zp = pack(out_dir=tmp_path)
    names = zipfile.ZipFile(zp).namelist()
    assert not any(n.replace("\\", "/").startswith("IronFleet") and "/data/eval/" in n
                   for n in names)
    assert not any("/.venv/" in n or "/.git/" in n for n in names)
    assert not any(n.endswith(".sqlite3") for n in names)  # dev trace stores stay out


def test_linux_install_scripts_are_valid_bash():
    """M11 T5: the installer/verifier twins parse as bash on every box with a
    bash on PATH (this Windows box ships Git Bash) — a syntax error must fail
    the suite here, not a fresh-OS operator there."""
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if not bash:  # pragma: no cover — every rig this repo targets has bash
        pytest.skip("no bash on PATH")
    ops = Path(__file__).resolve().parents[1] / "src" / "harness" / "ops"
    for name in ("install_linux.sh", "verify_linux_install.sh"):
        r = subprocess.run([bash, "-n", str(ops / name)], capture_output=True, text=True)
        assert r.returncode == 0, f"{name}: {r.stderr.strip()}"
