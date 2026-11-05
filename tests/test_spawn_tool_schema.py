# tests/test_spawn_tool_schema.py
"""Task 8 (spec 17 §5.7, finding F3): ported tools can declare a real parameter
schema, so a model can discover the fields — P5 measured NIM calling a schema-less
tool with empty input and failing twice. The schema rides the manifest row, is
rendered into the shim's TOOLS payload, and the shim derives a zod shape from it
at plugin init. Schema-less rows keep the proven empty-shape passthrough.

DEVIATION from the plan's sketch, recorded: the plan rendered literal per-tool
zod text from Python (a payload string the template would have to eval — JSON
cannot carry unquoted TS, and eval in the shim is not acceptable). The
derivation therefore lives in the TEMPLATE (runtime, from the payload JSON).
The locked contract is the spec's, not the sketch's: parameterized rows render a
real property list; schema-less rows are byte-identical to before."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.module_e.tools import load_manifest

DATA = Path(__file__).resolve().parent.parent / "data"
MANIFEST = DATA / "module-e" / "tools.yaml"
TEMPLATE = (Path(__file__).resolve().parent.parent / "src" / "harness" / "substrate"
            / "ironfleet-tools.ts")


# -- the manifest row (F3's source of truth) -----------------------------------

def test_spawn_agent_row_is_ported_with_a_real_schema():
    m = load_manifest(MANIFEST)
    spawn = m["spawn_agent"]
    assert spawn.status == "ported"
    assert spawn.entry == "harness.module_e.spawn_tool:spawn_agent"
    # the schema the model discovers: both fields, typed, described, required
    p = spawn.parameters
    assert p and set(p["required"]) == {"agent", "prompt"}
    assert p["properties"]["agent"]["type"] == "string"
    assert p["properties"]["prompt"]["type"] == "string"
    assert p["properties"]["prompt"]["description"]


def test_schema_less_rows_default_to_none():
    """Every row without `parameters` reads None — the payload and the shim must
    not change behaviour for the tools that never declared a schema."""
    m = load_manifest(MANIFEST)
    assert m["ironfleet_corpus_search"].parameters is None
    assert m["route"].parameters is None


def test_the_manifest_entry_resolves():
    """The row's `module:fn` must import — a typo in the entry string would only
    surface as a live dispatch failure otherwise."""
    from importlib import import_module
    mod_name, fn_name = load_manifest(MANIFEST)["spawn_agent"].entry.split(":", 1)
    assert callable(getattr(import_module(mod_name), fn_name))


# -- the shim: payload + derivation ---------------------------------------------

def _tools_payload(rendered: str) -> list[dict]:
    line = next(l for l in rendered.splitlines() if l.startswith("const TOOLS"))
    return json.loads(line.split("= ", 1)[1].rstrip())


def test_payload_carries_parameters_only_where_declared(tmp_path):
    from scripts.stand_up_opencode import render_tools_plugin
    from harness.module_e.tools import ported_tools
    m = load_manifest(MANIFEST)
    ts = render_tools_plugin(TEMPLATE.read_text(encoding="utf-8"), ws=tmp_path,
                             python="py", manifest=MANIFEST,
                             entries=[t for t in m.values() if t.status == "ported"])
    rows = {r["name"]: r for r in _tools_payload(ts)}
    assert rows["spawn_agent"]["parameters"]["required"] == ["agent", "prompt"]
    assert rows["route"]["parameters"] is None
    assert len(rows) == len(ported_tools(m))


def test_template_derives_zod_shapes_at_runtime():
    """The shim derives `args` from the payload: a real shape for parameterized
    rows, the proven empty passthrough for the rest. zod is a static import —
    one shared manifest, so every fresh mount needs it; bare "zod" resolution
    inside opencode's plugin runtime is proven by the recorded live smoke, and
    a resolution failure is a LOUD plugin-load error, never a silent degradation."""
    src = TEMPLATE.read_text(encoding="utf-8")
    assert "zodShapeOf" in src
    assert 'import { z } from "zod"' in src
    assert "args: parameters ? zodShapeOf(parameters) : {}" in src


# -- the tool body (pure parts; the live spawn is the recorded smoke) -----------

def test_spawn_agent_requires_both_fields():
    from harness.module_e.spawn_tool import spawn_agent
    with pytest.raises(KeyError, match="agent.*prompt|prompt.*agent"):
        spawn_agent({})
    with pytest.raises(KeyError):
        spawn_agent({"agent": "hunter"})
    with pytest.raises(KeyError):
        spawn_agent({"agent": "hunter", "prompt": "  "})


def test_agent_name_must_be_colon_free():
    from harness.module_e.spawn_tool import spawn_agent
    with pytest.raises(ValueError, match="colon-free"):
        spawn_agent({"agent": "bad:name", "prompt": "x"})


def test_child_workspace_is_a_session_sibling(tmp_path):
    from harness.module_e.spawn_tool import _child_workspace
    parent = tmp_path / "ses-1" / "manager"
    parent.mkdir(parents=True)
    assert _child_workspace(parent, "hunter") == tmp_path / "ses-1" / "hunter"


def test_matter_identity_reads_the_parent_workspace(tmp_path):
    from harness.module_e.spawn_tool import _matter_of
    (tmp_path / "matter.json").write_text(
        json.dumps({"matter_ref": "m-1", "classification": "LOCAL_PREFERRED"}),
        encoding="utf-8")
    assert _matter_of(tmp_path) == ("m-1", "LOCAL_PREFERRED")
    with pytest.raises(RuntimeError, match="matter.json"):
        _matter_of(tmp_path / "nope")


def test_spawn_agent_refuses_an_unsynced_cwd(tmp_path, monkeypatch):
    """cwd that is not a synced matter workspace: loud, before any child work."""
    from harness.module_e import spawn_tool
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="matter.json"):
        spawn_tool.spawn_agent({"agent": "hunter", "prompt": "x"})


def test_spawn_agent_refuses_an_unknown_target(tmp_path, monkeypatch):
    """A real persona name that the mount does not ship (sync generates the persona
    files, so this must be checked AFTER the sync) — loud, and never a spawn."""
    from harness.module_e import spawn_tool
    parent = tmp_path / "ses-1" / "manager"
    parent.mkdir(parents=True)
    (parent / "matter.json").write_text(
        json.dumps({"matter_ref": "m-t8", "classification": "LOCAL_PREFERRED"}),
        encoding="utf-8")
    monkeypatch.chdir(parent)
    with pytest.raises(RuntimeError, match="no drivable agent file"):
        spawn_tool.spawn_agent({"agent": "no-such-persona", "prompt": "x"})
