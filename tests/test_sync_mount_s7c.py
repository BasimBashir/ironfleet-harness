# tests/test_sync_mount_s7c.py
"""Task 10: the full S7c mount — the tools shim, the Python dispatcher, and the sync_mount
assembly that puts personas, skills, guard and tools into one workspace."""
import json
import subprocess
import sys
from pathlib import Path
import pytest
from harness.module_e.tools import load_manifest, ported_tools

DATA = Path(__file__).resolve().parent.parent / "data"
MANIFEST = DATA / "module-e" / "tools.yaml"

DEFERRED_ON_AUDITOR = ["ironfleet_solvency_assessor", "ironfleet_penalty_clause",
                       "ironfleet_imca_2016", "ironfleet_limitation_act",
                       "ironfleet_security_interest"]


def test_sync_mount_writes_the_full_s7c_mount(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    assert (ws / "opencode.json").is_file()
    assert (ws / "matter.json").is_file()
    assert (ws / ".opencode" / "plugins" / "ironfleet-guard.ts").is_file()
    assert (ws / ".opencode" / "plugins" / "ironfleet-tools.ts").is_file()
    assert (ws / "allowed.json").is_file()
    assert (ws / ".opencode" / "agent" / "hunter.md").is_file()
    assert (ws / ".opencode" / "agent" / "hunter-drive.md").is_file()
    assert (ws / ".opencode" / "skills" / "nz-court-calendar" / "SKILL.md").is_file()


def test_mount_carries_all_thirteen_personas_and_their_drive_twins(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    names = sorted(p.stem for p in (ws / ".opencode" / "agent").glob("*.md"))
    for persona in ["adversary", "ambiguity", "architect", "auditor", "citation", "clerk",
                    "evaluator", "hunter", "ingestor", "negotiator", "strategist",
                    "verifier", "wargamer"]:
        assert persona in names, persona
        assert f"{persona}-drive" in names, persona


def test_guard_plugin_whitelist_matches_the_ported_manifest(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    plugin = (ws / ".opencode" / "plugins" / "ironfleet-guard.ts").read_text()
    manifest = load_manifest(MANIFEST)
    for name in ported_tools(manifest):
        assert f'"{name}"' in plugin, name
    # the envelope rule's always-annotate builtin
    assert '"task"' in plugin


def test_guard_plugin_substitutes_no_placeholders(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    body = (ws / ".opencode" / "plugins" / "ironfleet-guard.ts").read_text()
    for ph in ("__SPIKE_WS__", "__PYTHON__", "__GUARD_CLI__", "__ANNOTATE__"):
        assert ph not in body


def test_tools_plugin_declares_exactly_the_ported_tools(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    body = (ws / ".opencode" / "plugins" / "ironfleet-tools.ts").read_text()
    ported = ported_tools(load_manifest(MANIFEST))
    # The declaration line, not the whole file: the header comment names the placeholders and so
    # carries their substituted values too, exactly as the guard template's does.
    tools_line = next(l for l in body.splitlines() if l.startswith("const TOOLS"))
    for name in ported:
        assert f'"{name}"' in tools_line, name
    assert tools_line.count('"name":') == len(ported)     # nothing hand-typed, nothing extra
    # the shim must not advertise a row the manifest does not port
    assert "ironfleet_solvency_assessor" not in tools_line
    # and it must name the manifest that governs it, not a placeholder
    assert str(MANIFEST).replace("\\", "/") in body
    for ph in ("__SPIKE_WS__", "__PYTHON__", "__MANIFEST__", "__TOOLS__"):
        assert ph not in body


def test_mount_authorities_are_annotate_only_and_the_guard_log_is_fresh(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    assert json.loads((ws / "allowed.json").read_text()) == {"allowed": [], "block": False}
    assert (ws / "guard-log.jsonl").read_text() == ""


def test_all_twenty_six_skill_docs_ship_in_the_mount(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    docs = sorted((ws / ".opencode" / "skills").glob("*" + "/SKILL.md"))
    assert len(docs) == 26


def test_auditor_is_the_only_persona_with_an_enabled_tool(tmp_path):
    """Step 4's measured end state: exactly one persona gains a tool, and it is the ported row."""
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    agent = ws / ".opencode" / "agent"
    enabled = {}
    for f in sorted(agent.glob("*.md")):
        if f.stem.endswith("-drive"):
            continue                     # drive twins disable every tool by design
        enabled[f.name] = [l.strip() for l in f.read_text(encoding="utf-8").splitlines()
                           if l.startswith("  ") and l.strip().endswith(": true")]
    assert enabled["auditor.md"] == ["ironfleet_statutory_demand: true"]
    assert [k for k, v in enabled.items() if v] == ["auditor.md"]
    # the five deferred rows ride the ledger, not a tool ID
    body = (agent / "auditor.md").read_text(encoding="utf-8").split("---\n", 2)[2]
    for name in DEFERRED_ON_AUDITOR:
        assert f"#   - {name}" in body, name
    # the dropped old-tree name is gone, not left dangling
    assert "nz_calendar" not in (agent / "auditor.md").read_text(encoding="utf-8")


def test_no_agent_file_emits_a_bare_tools_key(tmp_path):
    """LIVE FINDING (Task 10): opencode 1.18.25 validates a null `tools` as a schema failure and
    refuses the WHOLE configuration ('Expected object | undefined, got null tools'), which takes
    every agent and plugin down with it. A persona that enables nothing must have no tools block
    at all — `permission:` alone is fine."""
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    for f in sorted((ws / ".opencode" / "agent").glob("*.md")):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line == "tools:":
                assert i + 1 < len(lines) and lines[i + 1].startswith("  "), f.name


def test_workspace_is_its_own_git_repo_and_uncommitted(tmp_path):
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, DATA / "opencode-a1", "m-test", "LOCAL_PREFERRED", 7373)
    assert (ws / ".git").is_dir()
    # the matter never enters any history
    assert not list((ws / ".git").glob("*.m-test*"))


# ── the dispatcher: what the TS shim actually spawns ─────────────────────────

def test_dispatcher_runs_a_ported_tool_end_to_end(tmp_path):
    from harness.module_e.dispatch import dispatch
    # CHARACTERISATION (adjusted from the brief): the vendored detector's contract is
    # `content` + `trust_tier` -> {status, result.wp_status} (Task 7). The brief's fixture
    # (`{"text": ...}` -> {"detected": true}) predates that finding and is an ERROR row, not a
    # classification.
    args = tmp_path / "in.json"
    args.write_text(json.dumps({"content": "WITHOUT PREJUDICE\n\nWe propose settling at 60 cents.",
                                "trust_tier": "T2"}), encoding="utf-8")
    out = tmp_path / "out.json"
    assert dispatch(str(MANIFEST), "ironfleet_without_prejudice", str(args), str(out)) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "SUCCESS"
    assert result["result"]["wp_status"] == "WP"


def test_dispatcher_runs_the_route_tool_end_to_end(tmp_path):
    from harness.module_e.dispatch import dispatch
    args = tmp_path / "in.json"
    args.write_text(json.dumps({"intent": "ingestion"}), encoding="utf-8")
    out = tmp_path / "out.json"
    assert dispatch(str(MANIFEST), "route", str(args), str(out)) == 0
    r = json.loads(out.read_text(encoding="utf-8"))
    assert r["personas"] == ["ingestor"]
    assert r["defaulted"] is False


def test_dispatcher_refuses_a_deferred_tool(tmp_path):
    from harness.module_e.dispatch import dispatch
    args = tmp_path / "in.json"; args.write_text("{}")
    # Looked up by ROW name — kernel aliases (cccfa_2003 etc.) are fields on a row, not keys.
    with pytest.raises(RuntimeError) as ex:
        dispatch(str(MANIFEST), "ironfleet_solvency_assessor",
                 str(args), str(tmp_path / "out.json"))
    assert "deferred" in str(ex.value)


def test_dispatcher_surfaces_a_failure_as_a_nonzero_exit_and_stderr(tmp_path):
    """The TS-visible failure path: a Python exception must exit non-zero with the error on
    stderr — the shim returns that text, so nothing may swallow it into an empty result."""
    args = tmp_path / "in.json"
    args.write_text("{}", encoding="utf-8")
    out = tmp_path / "out.json"
    r = subprocess.run([sys.executable, "-m", "harness.module_e.dispatch", str(MANIFEST), "route",
                        str(args), str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode != 0
    assert "KeyError" in r.stderr            # Task 7: missing dict keys raise KeyError
    assert not out.exists()                  # no silent empty result written
