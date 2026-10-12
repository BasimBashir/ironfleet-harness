# tests/test_cli.py — S7j-W step 2: the user-facing entry point.
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "harness_cli", ROOT / "src" / "harness" / "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_flag_prints_and_exits_zero(capsys):
    mod = _load()
    with pytest.raises(SystemExit) as ex:
        mod.main(["--version"])
    assert ex.value.code == 0
    assert "harness" in capsys.readouterr().out


def test_default_routing_resolves_the_packaged_yaml():
    # The distribution tree ships data/ at its repo paths; the CLI's explicit default must
    # land on the real routing file (the launcher keeps its no-CWD-default rule — the CLI
    # is the layer that knows where the packaged data is).
    mod = _load()
    p = mod.default_routing()
    assert p.name == "routing-a1.yaml" and p.is_file()


def test_no_subcommand_prints_help_and_exits_two(capsys):
    import re
    mod = _load()
    assert mod.main([]) == 2
    out = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert "serve" in out and "drive" in out


# ── S7j-W step 2: the Windows distribution ───────────────────────────────────

def test_the_distribution_carries_the_product_paths():
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts.pack_windows import iter_files, SKIP_PATHS
    rels = {p.relative_to(ROOT) for p in iter_files(ROOT)}
    assert Path("data/routing-a1.yaml") in rels
    assert Path("data/opencode-a1/opencode.json") in rels
    assert Path("data/module-e/personas.yaml") in rels
    assert Path("src/harness/cli.py") in rels
    assert Path("pyproject.toml") in rels
    assert not any(p.parts[0] in {".venv", ".git"} for p in rels)
    assert not any(p == Path("data") / "eval" or (Path("data") / "eval") in p.parents
                   for p in rels)
    assert not any("__pycache__" in p.parts for p in rels)


def test_the_install_script_ships_and_names_the_real_steps():
    import sys
    sys.path.insert(0, str(ROOT))
    from scripts.pack_windows import INSTALL_SRC, iter_files
    assert INSTALL_SRC.is_file()
    body = INSTALL_SRC.read_text(encoding="utf-8")
    assert "1.18.25" not in body or "PINS" in body          # pin read from PINS, not pasted
    for needle in ("autoupdate", "p07_setup_windows.ps1", "harness.exe"):
        assert needle in body, needle
    # and the packer actually puts it at the zip root (added after the walk)
    rels = {p.relative_to(ROOT) for p in iter_files(ROOT)}
    assert INSTALL_SRC.relative_to(ROOT) in rels
