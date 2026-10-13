# tests/test_tools_manifest.py
from pathlib import Path
import pytest
from harness.module_e.tools import load_manifest, ported_tools, ToolEntry

DATA = Path(__file__).resolve().parent.parent / "data" / "module-e"

def test_manifest_loads_every_declared_tool():
    m = load_manifest(DATA / "tools.yaml")
    assert len(m) == 25                      # 20 deferred + 5 ported (R1: corpus_search)

def test_the_two_pattern_proofs_and_two_seam_tools_are_ported():
    p = ported_tools(load_manifest(DATA / "tools.yaml"))
    assert {"ironfleet_statutory_demand", "ironfleet_without_prejudice",
            "route", "refine_output"} <= p

@pytest.mark.parametrize("status", ["ported", "deferred", "blocked"])
def test_every_non_ported_tool_states_a_reason(status):
    for t in load_manifest(DATA / "tools.yaml").values():
        if t.status == status and status != "ported":
            assert t.reason, f"{t.name}: {status} without a reason — a silent drop"

def test_ported_tools_declare_an_entry_point():
    for t in load_manifest(DATA / "tools.yaml").values():
        if t.status == "ported":
            assert t.entry and ":" in t.entry, f"{t.name}: no module:fn entry"

def test_names_are_unique_and_prefixed():
    names = list(load_manifest(DATA / "tools.yaml"))
    assert len(names) == len(set(names))
    # Custom tools are namespaced so they cannot shadow or be shadowed by builtins.
    for n in names:
        assert n.startswith("ironfleet_") or n in {"route", "refine_output"}

def test_kernel_aliases_live_on_skill_rows_not_their_own_rows():
    # The 6 kernels are 13-line re-export shims into 6 of these skills; a kernel that became its
    # own row would duplicate a tool and break the "one tool, one row" invariant.
    m = load_manifest(DATA / "tools.yaml")
    aliased = [a for t in m.values() for a in (t.aliases or [])]
    assert len(aliased) == len(set(aliased)) == 6
    # No kernel name may collide with a tool name in either direction.
    for t in m.values():
        assert t.name not in aliased, f"{t.name} is also declared as an alias"
    # A ported row carrying an alias must have an entry point the alias resolves to.
    for t in m.values():
        if t.aliases and t.status == "ported":
            assert ":" in t.entry, f"{t.name}: ported alias owner with no entry point"
