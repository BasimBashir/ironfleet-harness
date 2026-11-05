# src/harness/service/system.py — /doctor and /provider as plain functions (M3).
"""The shell's system view: the pin verdict, the autoupdate guard, and the
provider registry as data. Moved from tui.py's _doctor/_providers; the TUI
echoes what these return. `on_error` keeps the doctor's soft failures under
the same session.tui.doctor_* error tags."""
from __future__ import annotations

from pathlib import Path

from harness.bootstrap import _provider_specs
from harness.packaging.macdist import PINS
from harness.session.commands import doctor_lines
from harness.substrate.mount import installed_version


def _home() -> Path:
    """Seam for tests: Path.home() resolves via env on Windows, which pytest's
    monkeypatch handles poorly across modules — this is the single read point."""
    return Path.home()


def doctor_report(on_error=lambda where, exc: None) -> str:
    """One screen of honest state. The provider rows show what the REGISTRY
    declares (tier, window) — the probe verdict lands at registration; re-probing
    every provider on a slash command would re-key the world for a view."""
    try:
        installed = installed_version()
    except Exception as exc:                                  # noqa: BLE001
        on_error("doctor_version", exc)
        installed = None
    cfg = _home() / ".config" / "opencode" / "opencode.jsonc"
    autoupdate = None
    if cfg.is_file():
        try:
            body = cfg.read_text(encoding="utf-8")
            autoupdate = '"autoupdate": false' in body or '"autoupdate":false' in body
        except Exception as exc:                              # noqa: BLE001
            on_error("doctor_cfg", exc)
    provs = [(s["name"], f"declared {s.get('tier', '?')},"
             f" window {s.get('context_window') or '—'}")
             for s in _provider_specs()]
    return "\n".join(doctor_lines(
        installed=installed, pin=str(PINS["opencode"]),
        autoupdate=autoupdate, providers=provs))


def provider_lines() -> str:
    """The registry as data — rows, tiers, windows. Switching a class's provider
    is a routing-table edit (data/, by ruling); this shows, it does not rewire."""
    lines = [f"{s['name']}: {s['model']} @ {s['base_url']}"
             f" (tier {s.get('tier', '?')}, window {s.get('context_window') or '—'})"
             for s in _provider_specs()]
    return "\n".join(lines) + "\n(route edits are data edits in data/routing-a1.yaml)"
