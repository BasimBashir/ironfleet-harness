# tests/test_persona_generator.py
from pathlib import Path
import pytest
import yaml
from harness.module_e.personas import (BUILTIN_TOOLS, load_index, render_agent_md, generate_all,
                                       UnknownTool)

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
    assert "websearch: deny" in fm   # M1/S2 default, no old-tree name needed

def _fm_of(src, **overrides):
    doc = yaml.safe_load((src / "personas.yaml").read_text(encoding="utf-8"))["personas"]
    doc[0].update(overrides)
    _write(src, doc)
    p = load_index(src / "personas.yaml")[0]
    return render_agent_md(p, model="gate/research", mode="subagent",
                           declared=DECLARED, ported=PORTED).split("---\n", 2)[1]

def test_a_persona_denying_nothing_still_gets_the_four_risky_builtins_denied(src):
    """M1/S2: `citation` shipped with `denied_tools: []` and so ran with bash and webfetch
    live. The deny is now the default, not something each persona must remember to ask for."""
    fm = _fm_of(src, denied_tools=[])
    for t in ("bash", "edit", "webfetch", "websearch"):
        assert f"  {t}: deny" in fm, t
    assert "write: deny" not in fm   # factory stages write their artifacts

def test_allowed_builtins_lifts_only_the_named_deny(src):
    fm = _fm_of(src, denied_tools=[], allowed_builtins=["edit"])
    assert "edit: deny" not in fm
    for t in ("bash", "webfetch", "websearch"):
        assert f"  {t}: deny" in fm, t

def test_only_ported_tools_are_enabled(src):
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="subagent",
                         declared=DECLARED, ported=PORTED)
    fm = md.split("---\n", 2)[1]
    assert "ironfleet_without_prejudice: true" in fm
    # ironfleet_imca_2016 is declared but deferred — no tool ID exists to enable.
    assert "ironfleet_imca_2016" not in fm

def test_a_ported_tool_the_persona_does_not_allow_is_disabled_not_unlisted(src):
    """OpenCode's `tools:` map is an OVERRIDE, not a whitelist: a name it does not list keeps
    its default (enabled) state. So the map names EVERY ported tool — the unallowed ones are
    written `false`, not left out, and the runtime surface is exactly the persona's allowed
    tools."""
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="subagent",
                         declared=DECLARED, ported=PORTED)
    fm = md.split("---\n", 2)[1]
    assert "  ironfleet_without_prejudice: true" in fm      # allowed -> enabled
    assert "  route: false" in fm                           # ported, not allowed -> written off
    assert sorted(l.strip() for l in fm.splitlines()
                  if l.startswith("  ") and l.split(":")[1].strip() in ("true", "false")) == \
        ["ironfleet_without_prejudice: true", "route: false"]
    assert "tools:" in fm            # the map is populated, never bare (Task 10's live finding)

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
    """Zero-tool means zero-tool: `tools:` is an override, so the twin must write `false` for
    EVERY tool the mount can offer — all ten builtins AND every ported custom tool, not just
    the ones it happens to be offered. PORTED here is {"ironfleet_without_prejudice", "route"}.
    (Final-review F1: the twin used to write only the builtins, which left the four ported
    tools selectable at runtime.)"""
    p = load_index(src / "personas.yaml")[0]
    md = render_agent_md(p, model="gate/research", mode="primary",
                         declared=DECLARED, ported=PORTED, source_root=src / "personas")
    fm = md.split("---\n", 2)[1]
    assert "tools:" in fm
    for line in fm.splitlines():
        if ": false" in line:
            assert line.strip().endswith(": false")
    assert "read: false" in fm and "task: false" in fm and "bash: false" in fm
    # every ported tool is named and written off too — an unlisted one stays enabled by default
    for t in sorted(PORTED):
        assert f"  {t}: false" in fm, t
    assert len([l for l in fm.splitlines() if l.strip().endswith(": false")]) == \
        len(BUILTIN_TOOLS) + len(PORTED)
    assert not [l for l in fm.splitlines() if l.strip().endswith(": true")]
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

def test_generated_bytes_are_lf_and_carry_the_corpus_bytes_verbatim(src, tmp_path):
    """Task 2's carried one-liner, finally landed (final-review F2): the byte-parity write path
    had no regression net. Every other test reads with `read_text`, whose universal-newline
    translation would silently MASK a dropped `newline=""` on the corpus read or the write — a
    refactor could ship CRLF workspaces while the suite stays green. So this one reads BYTES."""
    out = tmp_path / "agent"
    generate_all(src / "personas.yaml", src / "personas", out,
                 declared=DECLARED, ported=PORTED)
    corpus = (src / "personas" / "_source" / "hunter.txt").read_bytes()
    for name in ["hunter.md", "hunter-drive.md"]:       # subagent (with ledger) and drive twin
        content = (out / name).read_bytes()
        assert b"\r\n" not in content, f"{name}: CRLF in a generated agent file"
        # the deferred-ledger prefix may sit between the frontmatter and the body, so the corpus
        # bytes are asserted as a substring, not as the whole tail.
        assert corpus in content, f"{name}: corpus bytes altered"
