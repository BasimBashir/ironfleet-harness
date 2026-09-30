# src/harness/module_e/refine.py
from __future__ import annotations
import json, os, re, urllib.request

_BASE_URL = os.environ.get("GATE_BASE_URL", "http://127.0.0.1:7373/v1")

_CRITIQUE_SYSTEM = (
    "You are a senior NZ legal reviewer. Critique the draft. List HIGH and MEDIUM severity "
    "issues, each on its own line prefixed 'HIGH:' or 'MEDIUM:'. End with a final line "
    "'OVERALL_QUALITY: N/10'. Do not rewrite the draft.")
_IMPROVE_SYSTEM = (
    "You are a senior NZ legal drafter. Rewrite the draft addressing every HIGH and MEDIUM "
    "issue in the critique. Preserve all correct content — do not regress. Preserve citations "
    "exactly. Output only the rewritten draft.")

def _chat(messages: list[dict], task_class: str) -> str:
    """One LLM round-trip THROUGH THE GATE: the proxy is the gate's egress point. The wire
    model is the bare alias (resolve_alias's contract); matter identity rides matter.json."""
    body = json.dumps({"model": f"gate/{task_class}", "messages": messages,
                       "stream": False}).encode()
    req = urllib.request.Request(f"{_BASE_URL}/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]

def _parse_quality_score(critique: str) -> float | None:
    m = re.search(r"OVERALL_QUALITY:\s*([0-9]+(?:\.[0-9])?)\s*/\s*10", critique)
    return float(m.group(1)) if m else None

def refine_tool(args: dict) -> dict:
    """The manifest's `refine_output` entry: one critique pass + one improve pass, both through
    the gate, with the guard covering the result like any custom tool's output."""
    text = args.get("text")
    if not text or not isinstance(text, str):
        raise ValueError("refine_output requires non-empty 'text'")
    task_class = args.get("task_class", "drafting")
    critique = _chat([{"role": "system", "content": _CRITIQUE_SYSTEM},
                      {"role": "user", "content": text}], task_class)
    improved = _chat([{"role": "system", "content": _IMPROVE_SYSTEM},
                      {"role": "user", "content":
                       f"DRAFT:\n{text}\n\nCRITIQUE:\n{critique}"}], task_class)
    return {"refined": improved, "score_before": _parse_quality_score(critique),
            "score_after": _parse_quality_score(improved), "critique": critique}
