# tests/test_persona_generator.py
from pathlib import Path
import pytest
import yaml
from harness.module_e.personas import load_index, render_agent_md, generate_all, UnknownTool

INDEX = """\
personas:
  - name: hunter
    description: "Legal research specialist"
    task_type: research
    primary: _source/hunter.txt
    variants: {}
    allowed_tools: [ironfleet_without_prejudice, ironfleet_imca_2016]
    denied_tools: [file_write, shell_exec, web_scrape]
"""

PORTED = {"ironfleet_without_prejudice", "route"}
DECLARED = PORTED | {"ironfleet_imca_2016"}        # declared but deferred

@pytest.fixture
def src(tmp_path):
    d = tmp_path / "personas"
    (d / "_source").mkdir(parents=True)
    # newline="" on both write and read: the repo has core.autocrlf and no .gitattributes, so
    # default newline translation would silently turn LF into CRLF and break byte-exact parity.
    (d / "_source" / "hunter.txt").write_text("You are @HUNTER.\n\nCite everything.\n",
                                              encoding="utf-8", newline="")
    (tmp_path / "personas.yaml").write_text(INDEX)
    return tmp_path

def _write(src, personas):
    # safe_dump of a list starts with "- name: hunter" — there is no "personas:" prefix to
    # strip, so the slice the draft carried would eat "- name: hu" and corrupt the YAML.
    (src / "personas.yaml").write_text(
        "personas:\n" + yaml.safe_dump(personas, sort_keys=False),
        encoding="utf-8", newline="")

def test_body_is_verbatim(src):
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="subagent",
                         declared=DECLARED, ported=PORTED, source_root=src / "personas")
    body = md.split("---\n", 2)[2]
    # subagent mode prefixes the deferred-tool ledger, so the verbatim corpus text is the
    # tail of the body — byte-exact at the end is exactly what newline translation would break.
    assert body.endswith("You are @HUNTER.\n\nCite everything.\n")

def test_frontmatter_carries_description_mode_and_model(src):
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="subagent",
                         declared=DECLARED, ported=PORTED)
    fm = md.split("---\n", 2)[1]
    assert "description: Legal research specialist" in fm
    assert "mode: subagent" in fm
    assert "model: gate/research" in fm

def test_denied_tools_become_permission_denies(src):
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="subagent",
                         declared=DECLARED, ported=PORTED)
    fm = md.split("---\n", 2)[1]
    assert "edit: deny" in fm        # file_write
    assert "bash: deny" in fm        # shell_exec
    assert "webfetch: deny" in fm    # web_scrape

def test_only_ported_tools_are_enabled(src):
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="subagent",
                         declared=DECLARED, ported=PORTED)
    fm = md.split("---\n", 2)[1]
    assert "ironfleet_without_prejudice: true" in fm
    # ironfleet_imca_2016 is declared but deferred — no tool ID exists to enable.
    assert "ironfleet_imca_2016" not in fm

def test_deferred_tools_are_recorded_not_silently_dropped(src):
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="subagent",
                         declared=DECLARED, ported=PORTED)
    body = md.split("---\n", 2)[2]
    assert "# deferred" in body
    assert "ironfleet_imca_2016" in body

def test_a_tool_the_manifest_never_heard_of_fails_loud(src):
    p = load_index(src / "personas.yaml")[0]
    # ironfleet_imca_2016 absent from DECLARED here — a name the manifest doesn't know.
    with pytest.raises(UnknownTool) as ex:
        render_agent_md(p, model="gate/research", mode="subagent",
                        declared={"ironfleet_without_prejudice"},
                        ported={"ironfleet_without_prejudice"})
    assert "ironfleet_imca_2016" in str(ex.value)

def test_drive_twin_disables_every_tool(src):
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="primary",
                         declared=DECLARED, ported=PORTED, source_root=src / "personas")
    fm = md.split("---\n", 2)[1]
    assert "tools:" in fm
    for line in fm.splitlines():
        if ": false" in line:
            assert line.strip().endswith(": false")
    assert "read: false" in fm and "task: false" in fm and "bash: false" in fm
    # the body is still the verbatim persona, and the drive twin carries no deferred ledger
    body = md.split("---\n", 2)[2]
    assert body == "You are @HUNTER.\n\nCite everything.\n"

def test_generate_all_writes_subagent_and_drive_files(src, tmp_path):
    out = tmp_path / "agent"
    paths = generate_all(src / "personas.yaml", src / "personas", out,
                         declared=DECLARED, ported=PORTED)
    assert sorted(p.name for p in paths) == ["hunter-drive.md", "hunter.md"]

def test_generate_all_emits_variant_files(src, tmp_path):
    # raw dicts, not Persona objects: the test mutates the record before writing it back.
    doc = yaml.safe_load((src / "personas.yaml").read_text(encoding="utf-8"))["personas"]
    doc[0]["variants"] = {"glass": "_source/hunter-glass.txt"}
    (src / "personas" / "_source" / "hunter-glass.txt").write_text(
        "You are @HUNTER (Glass).\n", encoding="utf-8", newline="")
    _write(src, doc)
    out = tmp_path / "agent"
    names = sorted(p.name for p in generate_all(src / "personas.yaml", src / "personas", out,
                                                declared=DECLARED, ported=PORTED))
    assert "hunter-glass.md" in names and "hunter-glass-drive.md" in names

def test_variant_body_is_the_variant_text_not_the_primary(src, tmp_path):
    doc = yaml.safe_load((src / "personas.yaml").read_text(encoding="utf-8"))["personas"]
    doc[0]["variants"] = {"glass": "_source/hunter-glass.txt"}
    (src / "personas" / "_source" / "hunter-glass.txt").write_text(
        "You are @HUNTER (Glass).\n", encoding="utf-8", newline="")
    _write(src, doc)
    out = tmp_path / "agent"
    generate_all(src / "personas.yaml", src / "personas", out,
                 declared=DECLARED, ported=PORTED)
    body = (out / "hunter-glass.md").read_text().split("---\n", 2)[2]
    # the deferred ledger prefixes the body; the variant text — not the primary's — ends it.
    assert body.endswith("You are @HUNTER (Glass).\n")
