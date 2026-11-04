# src/harness/module_e/guard_port.py
from __future__ import annotations
from pydantic import BaseModel

from harness.quote_check import quote_audit

class GuardResult(BaseModel):
    annotated: str
    ungrounded: list[str]

def _citations(text: str) -> list[str]:
    out, buf, depth = [], "", 0
    for ch in text:
        if ch == "[":
            depth, buf = depth + 1, (buf + ch if depth else ch)
        elif ch == "]" and depth:
            buf += ch; depth -= 1
            if depth == 0:
                out.append(buf); buf = ""
        elif depth:
            buf += ch
    return out

def portable_grounding_guard(draft: str, allowed_authorities: list[str],
                             allowed_passages: list[str] | None = None) -> GuardResult:
    """Structured citation-envelope check (house rule: no regex beyond bracket scanning +
    the quote_check referee). Annotations match the current IronFleet guard's
    '[UNGROUNDED — not confirmed]' convention so spike parity is measurable against the
    same behaviour. R1 D6: quoted spans must ALSO ground — containment against the
    retrieved passages (allowed_passages); the S7c splice makes this pass by
    construction, so a failure means the model hand-wrote a quote. Needle checks are
    unchanged and compose: needles AND quotes must both ground."""
    ungrounded = [c for c in _citations(draft)
                  if not any(a in c for a in allowed_authorities)]
    annotated = draft
    for c in ungrounded:
        annotated = annotated.replace(c, f"{c} [UNGROUNDED — not confirmed]")
    if allowed_passages is not None:
        _, fabricated = quote_audit(annotated, allowed_passages)
        for q in fabricated:
            annotated = annotated.replace(f'"{q}"', f'" {q} " [UNQUOTED — not in retrieved corpus]')
            annotated = annotated.replace(f"“{q}”", f"“ {q} ” [UNQUOTED — not in retrieved corpus]")
            annotated = annotated.replace(f"‘{q}’", f"‘ {q} ’ [UNQUOTED — not in retrieved corpus]")
        ungrounded = ungrounded + fabricated
    return GuardResult(annotated=annotated, ungrounded=ungrounded)

class OpenCodeHookAdapter:
    """OpenCode hook shape: JSON on stdin → decision JSON on stdout."""
    def handle(self, stdin_json: dict) -> dict:
        res = portable_grounding_guard(stdin_json.get("output", ""),
                                       stdin_json.get("allowed", []),
                                       stdin_json.get("allowed_passages"))
        return {"decision": "block" if res.ungrounded else "approve",
                "reason": f"ungrounded: {res.ungrounded}" if res.ungrounded else "grounded",
                "output": res.annotated}

class OpenHandsHandlerAdapter:
    """OpenHands event-handler shape: on_action_execution_end(event) → event mutation."""
    def on_action_execution_end(self, event: dict) -> dict:
        res = portable_grounding_guard(event.get("observation", ""), event.get("allowed", []))
        event["observation"] = res.annotated
        if res.ungrounded:
            event.setdefault("_spike", {})["guard_blocked"] = res.ungrounded
        return event

def dsh_plugin_skeleton() -> str:
    return """// dsh plugin skeleton (TS): register the guard on tools/post-execute
export function apply(ctx) {
  ctx.on('tools/post-execute', (ev, next) => {
    const r = globalThis.__spikeGuard(ev.output, ev.allowed ?? []);
    if (r.ungrounded.length) return { kind: 'deny', reason: `ungrounded: ${r.ungrounded}` };
    return next(ev);
  });
}"""
