# src/harness/session/commands.py
"""The shell's slash commands as pure assembly (spec 17 s5.6, plan Task 13).

opencode's TUI cannot host slash commands (P2 measured: no extensibility) —
so /ingest, /persona new, /doctor and /provider live in OUR shell. The pieces
here are the testable assembly and validation; the live work they name (the
ingest run, the provider probes, the mount regen) rides the existing substrate
in the caller (the TUI worker, the CLI).
"""
from __future__ import annotations

from pathlib import Path

from harness.module_e.tools import declared_tools, load_manifest

MODULE_E = Path(__file__).resolve().parents[3] / "data" / "module-e"


# -- /persona new -----------------------------------------------------------------

def build_persona_row(name: str, description: str, allowed: list[str],
                      prompt: str, task_type: str = "drafting") -> dict:
    """A validated personas.yaml row — exactly the fields Persona/load_index
    consume (a shape drift breaks the regen). The old agent-authoring CLI's
    core, folded in per the ratified R3 scope."""
    if ":" in name:
        raise ValueError(f"persona name must be colon-free (Windows registry"
                         f" directory names): {name!r}")
    declared = declared_tools(load_manifest(MODULE_E / "tools.yaml"))
    unknown = [t for t in allowed if t not in declared]
    if unknown:
        raise ValueError(f"allowed_tools {unknown} are not in the tool manifest"
                         f" (declared: {sorted(declared)})")
    return {"name": name, "description": description, "task_type": task_type,
            "primary": prompt, "variants": {}, "allowed_tools": list(allowed),
            "denied_tools": []}


def parse_persona_new(args: str) -> tuple[str, str, list[str], str]:
    """/persona new's one-line form: name|description|tool,tool|prompt. Anything
    else is a usage error naming the form — never a silent partial persona."""
    parts = [p.strip() for p in args.split("|")]
    if len(parts) != 4 or not all(parts):
        raise ValueError("/persona new expects name|description|tools|prompt")
    name, description, tools, prompt = parts
    return name, description, [t.strip() for t in tools.split(",") if t.strip()], prompt


# -- /ingest -----------------------------------------------------------------------

def ingest_argv(matter_ref: str, sources: list[Path], report: Path) -> list[str]:
    """The corpus_ingest CLI argv (sha256 resume, recorded-skip, batches of 64 —
    imported and run by the caller, never reimplemented)."""
    if ":" in matter_ref:
        raise ValueError(f"matter ref must be colon-free: {matter_ref!r}")
    return ["--matter", matter_ref,
            "--sources", *[str(s) for s in sources],
            "--out-report", str(report)]


# -- /doctor ------------------------------------------------------------------------

def doctor_lines(*, installed: str | None, pin: str, autoupdate: bool | None,
                 providers: list[tuple[str, str]]) -> list[str]:
    """The honest state, one screen: the pin verdict, the autoupdate guard, and
    each provider's probe verdict verbatim. DRIFT names the fix, not just the
    fault — the R2 installer's enforce-don't-best-effort rule, in the shell."""
    expected = pin.split("@", 1)[-1]
    if installed is None:
        lines = [f"pin: {pin} — opencode not found on PATH"]
    elif installed == expected:
        lines = [f"pin: {pin} — installed {installed} OK"]
    else:
        lines = [f"pin: DRIFT — installed {installed}, expected {expected}"
                 f" (npm i -g {pin}; never npm update)"]
    if autoupdate is False:
        lines.append("autoupdate: false OK")
    else:
        lines.append('autoupdate: DRIFT — set "autoupdate": false in the global'
                     " ~/.config/opencode/opencode.jsonc")
    lines.append("providers:")
    if providers:
        lines.extend(f"  {name}: {verdict}" for name, verdict in providers)
    else:
        lines.append("  (none probed)")
    return lines
