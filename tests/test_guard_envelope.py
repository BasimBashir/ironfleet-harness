# tests/test_guard_envelope.py
from pathlib import Path
import pytest
from harness.module_e.guard import annotate_eligible, render_guard_plugin

TEMPLATE = """\
const WS = "__SPIKE_WS__"
const PYTHON = "__PYTHON__"
const GUARD_CLI = "__GUARD_CLI__"
const GUARD_DIR = "__GUARD_DIR__"
const ANNOTATE = new Set<string>(__ANNOTATE__)
"""

@pytest.mark.parametrize("tool", ["ironfleet_statutory_demand", "ironfleet_without_prejudice",
                                  "task", "route", "refine_output"])
def test_whitelisted_tools_are_annotated(tool):
    assert annotate_eligible(tool, {"ironfleet_statutory_demand",
                                    "ironfleet_without_prejudice", "route",
                                    "refine_output"})

@pytest.mark.parametrize("tool", ["read", "write", "edit", "bash", "glob", "grep",
                                  "webfetch", "todowrite", "skill"])
def test_builtin_tools_are_never_annotated(tool):
    # Detection + blocking still run on these; only their content is untouched.
    assert not annotate_eligible(tool, {"ironfleet_statutory_demand"})

def test_unknown_custom_tool_is_not_annotated():
    # Fail-safe: a tool the manifest never heard of is detected-and-blocked, never rewritten.
    assert not annotate_eligible("some-future-tool", set())

def test_render_substitutes_every_placeholder():
    out = render_guard_plugin(TEMPLATE, ws=Path("C:/ws"), python="C:/py/python.exe",
                              guard_cli="C:/guard_cli.py",
                              whitelist={"route", "refine_output"})
    assert '"C:/ws"' in out
    assert '"C:/.ironfleet-guard/ws"' in out   # guard_dir(ws): outside the agent's cwd
    assert '"C:/py/python.exe"' in out
    assert '"C:/guard_cli.py"' in out
    assert '"route"' in out and '"refine_output"' in out
    assert ("__ANNOTATE__" not in out and "__SPIKE_WS__" not in out
            and "__GUARD_DIR__" not in out)

def test_rendered_annotate_set_is_a_bracketed_array_literal():
    # SEMANTIC, not substring-incidental: JS's Set constructor takes ONE iterable —
    # `new Set("a", "b")` silently uses only "a" (string -> char set) and matches nothing.
    # The rendered payload must be an array literal so the whitelist actually works.
    out = render_guard_plugin(TEMPLATE, ws=Path("C:/ws"), python="C:/py/python.exe",
                              guard_cli="C:/guard_cli.py",
                              whitelist={"route", "refine_output"})
    assert 'new Set<string>(["refine_output", "route", "task"])' in out

def test_render_escapes_backslashes_for_windows_paths():
    out = render_guard_plugin(TEMPLATE, ws=Path("C:\\ws"), python="C:\\py\\python.exe",
                              guard_cli="C:\\guard_cli.py", whitelist=set())
    assert "C:/ws" in out          # backslashes would escape inside the TS string literal
