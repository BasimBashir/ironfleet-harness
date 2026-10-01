# tests/test_module_e_characterization.py
import json
from pathlib import Path
import pytest
from harness.module_e.personas import load_index
from harness.module_e.supervisor import load_routes
from harness.module_e.tools import load_manifest, ported_tools, declared_tools

DATA = Path(__file__).resolve().parent.parent / "data"

def test_every_routed_persona_is_shipped(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    shipped = {p.stem for p in (ws / ".opencode" / "agent").glob("*.md")}
    routes = load_routes(DATA / "module-e" / "supervisor.yaml")
    for intent in routes.routes:
        for persona in routes.resolve(intent, "HIGH"):   # HIGH exercises every addition
            assert persona in shipped, f"{intent} routes to unshipped persona {persona}"
    for persona in routes.default_route:
        assert persona in shipped

def test_every_persona_allowed_tool_is_a_declared_manifest_row():
    # Deferred is fine (auditor's six kernel tools are deferred); unknown is not.
    declared = declared_tools(load_manifest(DATA / "module-e" / "tools.yaml"))
    for p in load_index(DATA / "module-e" / "personas.yaml"):
        for t in p.allowed_tools:
            assert t in declared, f"{p.name}: allowed_tool {t} is not in the manifest at all"

def test_every_manifest_status_is_from_the_known_set():
    # A typo'd status would silently drop from ported_tools() AND make the reason assertion
    # vacuous while len(m)==24 still passes (Task 6 review Minor 1) — pin the vocabulary.
    for t in load_manifest(DATA / "module-e" / "tools.yaml").values():
        assert t.status in {"ported", "deferred", "blocked"}, \
            f"{t.name}: unknown status {t.status!r}"

def test_only_ported_tools_are_enabled_in_generated_agents(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    ported = ported_tools(load_manifest(DATA / "module-e" / "tools.yaml"))
    for f in (ws / ".opencode" / "agent").glob("*.md"):
        if f.name.endswith("-drive.md"):
            continue                       # the drive twin enables nothing: all ten builtins
                                           # AND all four ported tools are written `false`
        md = f.read_text(encoding="utf-8")
        fm = md.split("---\n", 2)[1]
        for line in fm.splitlines():
            if line.strip().endswith(": true"):
                name = line.strip().split(":")[0].strip()
                assert name in ported, f"{f.name}: enabled tool {name} is not ported"

def test_deferred_persona_tools_are_visible_in_the_generated_agent(tmp_path):
    # The no-silent-drop property, asserted on the real artifact: auditor's deferred kernel tools
    # must appear in auditor.md as a `# deferred` ledger, not vanish.
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    auditor = (ws / ".opencode" / "agent" / "auditor.md").read_text(encoding="utf-8")
    deferred = [t for t in load_index(DATA / "module-e" / "personas.yaml")
                if t.name == "auditor"][0].allowed_tools
    ported = ported_tools(load_manifest(DATA / "module-e" / "tools.yaml"))
    for t in deferred:
        if t not in ported:
            assert f"#   - {t}" in auditor, f"auditor: deferred tool {t} silently dropped"

def test_every_task_type_declared_by_a_persona_has_a_mount_alias():
    cfg = json.loads((DATA / "opencode-a1" / "opencode.json").read_text())
    models = set(cfg["provider"]["gate-local"]["models"])
    for p in load_index(DATA / "module-e" / "personas.yaml"):
        assert f"gate/{p.task_type}" in models, f"{p.name}: no mount alias for {p.task_type}"
