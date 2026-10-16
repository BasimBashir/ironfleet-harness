"""The Windows distribution zip (R2): the three user-facing files sit at the zip
root — install script, first-run verify + drive smoke, prerequisites doc — and the
dev substrate (data/eval) never rides along."""
from __future__ import annotations

import zipfile
from collections import Counter

import harness
from scripts.pack_windows import pack


def test_zip_carries_install_verify_and_prerequisites_at_root(tmp_path):
    zp = pack(out_dir=tmp_path)
    assert zp.name == f"IronFleet-harness-{harness.__version__}-windows.zip"
    top = f"IronFleet-harness-{harness.__version__}-windows"
    all_names = zipfile.ZipFile(zp).namelist()
    for root_file in ("install_windows.ps1", "verify_windows_install.ps1",
                      "PREREQUISITES.md"):
        assert f"{top}/{root_file}" in all_names, root_file
    # no duplicate entries (the ops-tree copies stay at their src paths), and every
    # arcname is posix — backslash names would not extract as a tree on macOS (R6)
    assert not [n for n, c in Counter(all_names).items() if c > 1]
    assert not [n for n in all_names if "\\" in n]


def test_zip_excludes_dev_substrate(tmp_path):
    zp = pack(out_dir=tmp_path)
    names = zipfile.ZipFile(zp).namelist()
    assert not any(n.replace("\\", "/").startswith("IronFleet") and "/data/eval/" in n
                   for n in names)
    assert not any("/.venv/" in n or "/.git/" in n for n in names)
    assert not any(n.endswith(".sqlite3") for n in names)  # dev trace stores stay out
