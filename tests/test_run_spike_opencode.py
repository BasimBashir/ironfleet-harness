# tests/test_run_spike_opencode.py
import json
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_spike_opencode.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_spike_opencode", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_guard_plugin_substitutes_paths():
    mod = _load()
    template = 'const WS = "__SPIKE_WS__"\nconst PYTHON = "__PYTHON__"\nconst GUARD = "__GUARD_CLI__"\n'
    out = mod.render_guard_plugin(template, ws="C:/ws x", python="C:/py/python.exe",
                                  guard_cli="C:/hc/src/guard_cli.py")
    assert '"C:/ws x"' in out and '"C:/py/python.exe"' in out and '"C:/hc/src/guard_cli.py"' in out
    assert "__SPIKE_WS__" not in out and "__PYTHON__" not in out and "__GUARD_CLI__" not in out


def test_hunter_agent_md_body_is_persona_verbatim():
    mod = _load()
    persona = "You are @HUNTER.\n\nRules\n1. CITE [1]."
    md = mod.hunter_agent_md(persona, model="ollama/qwen3.8:27b")
    assert md.startswith("---\n")
    assert "mode: subagent" in md and "model: ollama/qwen3.8:27b" in md
    assert persona in md                       # body = PERSONA_PORT verbatim, no edits


def test_extract_final_text_takes_last_assistant_message():
    mod = _load()
    events = [
        {"type": "session.created", "properties": {"id": "s1"}},
        {"type": "message.updated",
         "properties": {"info": {"id": "m1", "role": "user"}, "parts": [{"type": "text", "text": "q"}]}},
        {"type": "message.updated",
         "properties": {"info": {"id": "m2", "role": "assistant"},
                        "parts": [{"type": "text", "text": "part one "},
                                  {"type": "reasoning", "text": "(thinking)"}]}},
        {"type": "message.updated",
         "properties": {"info": {"id": "m2", "role": "assistant"},
                        "parts": [{"type": "text", "text": "part one "},
                                  {"type": "text", "text": "part two"},
                                  {"type": "reasoning", "text": "(thinking)"}]}},
    ]
    assert mod.extract_final_text(events) == "part one part two"


def test_extract_final_text_empty_when_no_assistant_message():
    mod = _load()
    assert mod.extract_final_text([{"type": "session.created"}]) == ""


def test_extract_final_text_from_run_mode_flat_parts():
    """`opencode run --format json` streams flat part events: {"type": "text",
    "part": {"messageID": ..., "text": ...}} — observed live 2026-09-01."""
    mod = _load()
    events = [
        {"type": "step_start", "part": {"type": "step-start", "messageID": "m1"}},
        {"type": "text", "part": {"messageID": "m1", "type": "text", "text": "part one "}},
        {"type": "text", "part": {"messageID": "m1", "type": "text", "text": "part two"}},
        {"type": "step_finish", "part": {"messageID": "m1", "type": "step-finish"}},
        {"type": "step_start", "part": {"type": "step-start", "messageID": "m2"}},
        {"type": "text", "part": {"messageID": "m2", "type": "text", "text": "final answer"}},
    ]
    assert mod.extract_final_text(events) == "final answer"


def test_extract_tool_texts_from_run_mode_events():
    mod = _load()
    events = [
        {"type": "tool", "part": {"messageID": "m1", "type": "tool", "tool": "bash",
                                  "output": " Authority check: [Imaginary Act 2026, s 9] threshold "}},
        {"type": "text", "part": {"messageID": "m1", "type": "text", "text": "done"}},
    ]
    assert mod.extract_tool_texts(events) == [" Authority check: [Imaginary Act 2026, s 9] threshold "]
