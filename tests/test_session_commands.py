# tests/test_session_commands.py
"""Task 13 (spec 17 s5.6): the shell's slash commands, as pure assembly the TUI
and the CLI both drive. opencode's TUI cannot host them (P2: no extensibility) —
these live in OUR shell. The live parts (the ingest run, the probe verdicts, the
mount regen) are the recorded smoke's and the acceptance driver's; here the
assembly and validation are locked."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.session.commands import (
    build_persona_row,
    doctor_lines,
    ingest_argv,
    parse_persona_new,
)

DATA = Path(__file__).resolve().parent.parent / "data"


# -- /persona new: the validated personas.yaml row -------------------------------

def test_build_persona_row_happy_path():
    row = build_persona_row(name="paralegal", description="drafts bundles",
                            allowed=["route", "ironfleet_corpus_search"],
                            prompt="You are the paralegal.", task_type="drafting")
    # the exact fields load_index/Persona consume — a shape drift breaks the regen
    assert row == {"name": "paralegal", "description": "drafts bundles",
                   "task_type": "drafting", "primary": "You are the paralegal.",
                   "variants": {},
                   "allowed_tools": ["route", "ironfleet_corpus_search"],
                   "denied_tools": []}


def test_build_persona_row_rejects_colon_free_violations():
    with pytest.raises(ValueError, match="colon-free"):
        build_persona_row(name="bad:name", description="d", allowed=[], prompt="p")


def test_build_persona_row_rejects_unknown_tools():
    """allowed_tools must exist in the DECLARED set (any status) — the generator
    turns an undeclared name into a loud UnknownTool at regen; the row builder
    fails first, naming the unknown ones. Builtin names (read, bash...) are NOT
    manifest rows — persona tool maps draw from the manifest; builtins ride the
    deny reconciliation."""
    with pytest.raises(ValueError, match="no-such-tool"):
        build_persona_row(name="p", description="d",
                          allowed=["route", "no-such-tool"], prompt="p")
    with pytest.raises(ValueError, match="'read'"):
        build_persona_row(name="p", description="d", allowed=["read"], prompt="p")


def test_parse_persona_new_pipe_form():
    name, desc, allowed, prompt = parse_persona_new(
        "paralegal|drafts bundles|read,write|You are the paralegal.")
    assert name == "paralegal" and desc == "drafts bundles"
    assert allowed == ["read", "write"] and prompt == "You are the paralegal."
    with pytest.raises(ValueError, match="name|description|tools|prompt"):
        parse_persona_new("only-three|parts|here")


# -- /ingest: the corpus_ingest argv ----------------------------------------------

def test_ingest_argv_shape(tmp_path):
    src = tmp_path / "docs"
    argv = ingest_argv("m-1", [src], tmp_path / "report.json")
    assert argv == ["--matter", "m-1", "--sources", str(src),
                    "--out-report", str(tmp_path / "report.json")]


def test_ingest_argv_rejects_colons():
    with pytest.raises(ValueError, match="colon-free"):
        ingest_argv("bad:ref", [], Path("r.json"))


# -- /doctor: the honest state, one screen ----------------------------------------

def test_doctor_lines_ok_when_the_pin_matches():
    lines = doctor_lines(installed="1.18.25", pin="opencode-ai@1.18.25",
                         autoupdate=False,
                         providers=[("ollama-local", "mechanical-only (verified=False)"),
                                    ("nvidia-nim", "full (verified=True)")])
    text = "\n".join(lines)
    assert "1.18.25" in text and "DRIFT" not in text
    assert "autoupdate: false" in text
    assert "ollama-local" in text and "mechanical-only" in text
    assert "nvidia-nim" in text and "full" in text


def test_doctor_lines_says_drift_when_the_binary_does_not_match():
    lines = doctor_lines(installed="9.9.9", pin="opencode-ai@1.18.25",
                         autoupdate=True, providers=[])
    text = "\n".join(lines)
    assert "DRIFT" in text and "9.9.9" in text
    assert "autoupdate" in text and "false" in text     # names the fix, not just the fault


def test_doctor_lines_handles_an_unreadable_binary():
    lines = doctor_lines(installed=None, pin="opencode-ai@1.18.25",
                         autoupdate=False, providers=[])
    assert any("not found" in l for l in lines)
