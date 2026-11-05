# tests/test_no_scripts_imports.py — M3 acceptance: no production path imports the
# scripts/ or spike/ trees. AST walk (not a grep) so string mentions and comments
# cannot false-positive, and the shims' own re-exports live in scripts/, not src/.
# Red after Commit 2 (the two tui.py imports), green after Commit 3.
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "harness"


def _banned_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "scripts" or alias.name.startswith("scripts."):
                    bad.append(f"{path}:{node.lineno}: import {alias.name}")
                if alias.name == "harness.spike" or alias.name.startswith("harness.spike."):
                    bad.append(f"{path}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "scripts" or mod.startswith("scripts."):
                bad.append(f"{path}:{node.lineno}: from {mod} import ...")
            if mod == "harness.spike" or mod.startswith("harness.spike."):
                bad.append(f"{path}:{node.lineno}: from {mod} import ...")
    return bad


def test_no_src_file_imports_scripts_or_spike():
    offenders = [line for py in sorted(SRC.rglob("*.py")) for line in _banned_imports(py)]
    assert offenders == [], "production paths must not import scripts/ or spike/:\n" + \
        "\n".join(offenders)
