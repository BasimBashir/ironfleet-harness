# src/harness/module_e/personas.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

BUILTIN_TOOLS = ["read", "glob", "grep", "task", "todowrite", "skill", "bash",
                 "edit", "write", "webfetch"]
# Old-tree denial names -> the OpenCode builtin that would satisfy them. A denied name with no
# entry here names a tool this mount does not have, so there is nothing to deny (reconciled and
# recorded in Task 9, never silently).
DENY_MAP = {"file_write": "edit", "shell_exec": "bash",
            "web_scrape": "webfetch", "web_search": "webfetch"}

@dataclass
class Persona:
    name: str
    description: str
    task_type: str
    primary: str
    variants: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)

class UnknownTool(ValueError):
    """A persona references a tool the manifest does not declare. Fail loud — a silent drop
    would let the persona advertise a capability the mount does not have (S7c spec §3.5)."""

def load_index(path: Path) -> list[Persona]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [Persona(**p) for p in doc["personas"]]

def _frontmatter(p: Persona, model: str, mode: str,
                 declared: set[str], ported: set[str]) -> str:
    lines = ["---", f"description: {p.description}", f"mode: {mode}", f"model: {model}"]
    if mode == "subagent":
        unknown = [t for t in p.allowed_tools if t not in declared]
        if unknown:
            raise UnknownTool(f"{p.name}: allowed_tools {unknown} are not in the tool manifest")
        # `tools:` is only written when there is something under it: opencode 1.18.25 validates a
        # bare `tools:` as null and rejects the WHOLE configuration ("Expected object | undefined,
        # got null tools"), which takes every agent and plugin down with it (observed live with
        # `opencode agent list` on a mounted workspace).
        enabled = [f"  {t}: true" for t in sorted(p.allowed_tools) if t in ported]
        if enabled:
            lines.append("tools:")
            lines += enabled
        deny = sorted({DENY_MAP.get(d) for d in p.denied_tools if d in DENY_MAP})
        if deny:
            lines.append("permission:")
            for d in deny:
                lines.append(f"  {d}: deny")
    else:  # drive twin: the parity comparator is a plain chat call — any tool makes the model
           # act agentively instead of answering (spike, observed 2026-09-01).
        lines.append("tools:")
        for t in BUILTIN_TOOLS:
            lines.append(f"  {t}: false")
    return "\n".join(lines) + "\n"

def _deferred_ledger(p: Persona, ported: set[str]) -> str:
    suppressed = [t for t in p.allowed_tools if t not in ported]
    if not suppressed:
        return ""
    lines = ["# deferred — named in the manifest, not yet ported (S7c batch task):"]
    lines += [f"#   - {t}" for t in suppressed]
    return "\n".join(lines) + "\n\n"

def render_agent_md(p: Persona, model: str, mode: str, declared: set[str], ported: set[str],
                    source_root: Path | None = None, rel: str | None = None) -> str:
    rel = rel or p.primary
    # newline="" is load-bearing: the repo has core.autocrlf and no .gitattributes, so a plain
    # read_text would translate the corpus's LF to CRLF on Windows and silently break the
    # byte-exact parity Task 1 established. Read bytes as they are in the file.
    body = (Path(source_root) / rel).read_text(encoding="utf-8", newline="") if source_root else ""
    ledger = _deferred_ledger(p, ported) if mode == "subagent" else ""
    return f"{_frontmatter(p, model, mode, declared, ported)}---\n{ledger}{body}"

def generate_all(index_path: Path, src_dir: Path, out_dir: Path,
                 declared: set[str], ported: set[str]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for p in load_index(index_path):
        model = f"gate/{p.task_type}"
        for rel, suffix in [(p.primary, ""), *[(v, f"-{k}") for k, v in p.variants.items()]]:
            name = f"{p.name}{suffix}"
            for mode, tag in [("subagent", ""), ("primary", "-drive")]:
                f = out_dir / f"{name}{tag}.md"
                # newline="" on the write too: this is the generation-time write, and
                # translating LF->CRLF here would destroy the byte-exact parity the corpus
                # read preserved (Task 10 compares the generated body to the corpus bytes).
                f.write_text(render_agent_md(p, model, mode, declared, ported, src_dir, rel),
                             encoding="utf-8", newline="")
                written.append(f)
    return written
