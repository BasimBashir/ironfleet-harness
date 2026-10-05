"""S7g: the macOS distribution as data (spec §4.2).

The build itself — PyInstaller, codesign, the DMG — cannot cross-compile from Windows.
What CAN be proven on any OS is that the recipe is self-consistent: every plist parses
and carries the keys launchd and Finder expect, every file the manifest names is staged,
every version the installer pins is non-empty. A Mac session then fills the one hole
this module leaves (the native binary in Contents/MacOS) rather than discovering a
malformed plist at signing time.

opencode is bootstrapped at install time against PINS, not vendored (user ruling
2026-10-05): no Bun runtime is frozen into our artifact, and the pin is one string in
one place that install-time verification drift-checks.
"""
from __future__ import annotations

import plistlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The repo root, for "copy" manifest entries: this file is at
# src/harness/packaging/macdist.py, so parents[3] is harness-core.
MANIFEST_COPIES_ROOT = Path(__file__).resolve().parents[3]

# --- pins --------------------------------------------------------------------
# opencode-ai@1.18.25 is the M0-decided pinned version (S7b's proven one). A ruling
# that bumps S7c's Windows leg bumps this string too; this is the single place.
PINS: dict[str, object] = {
    "opencode": "opencode-ai@1.18.25",
    "autoupdate": False,      # S7c decision (b), discharged for the macOS leg
}

BUNDLE_ID = "ai.ironfleet.harness"
LAUNCHD_LABEL = "ai.ironfleet.egress-proxy"
APP_NAME = "IronFleet.app"
LAUNCHER_NAME = "ironfleet-launcher"
DUE_FOR_MAC = "due-for-Mac (S7g-M)"

INFO_PLIST: dict[str, Any] = {
    "CFBundleName": "IronFleet",
    "CFBundleIdentifier": BUNDLE_ID,
    "CFBundleVersion": "1",
    "CFBundleShortVersionString": "0.1.0",
    "CFBundlePackageType": "APPL",
    "CFBundleExecutable": LAUNCHER_NAME,
    "CFBundleInfoDictionaryVersion": "6.0",
    "LSMinimumSystemVersion": "12.0",
    "NSHighResolutionCapable": True,
}

# The egress proxy as a user launch agent. KeepAlive: the proxy is the ONLY path
# opencode has to the gate, so it dying must not silently sever every matter. The proxy
# binds 127.0.0.1:7373 (scripts/stand_up_opencode.py); ProgramArguments and
# WorkingDirectory are injected at staging time because launchd resolves neither
# relative paths nor ~, and the absolute bundle path is only known then.
LAUNCHD_PLIST: dict[str, Any] = {
    "Label": LAUNCHD_LABEL,
    "RunAtLoad": True,
    "KeepAlive": True,
    "StandardOutPath": "~/Library/Logs/IronFleet/egress-proxy.out.log",
    "StandardErrorPath": "~/Library/Logs/IronFleet/egress-proxy.err.log",
}

MOUNT_README = """\
# Per-matter mounts (S7f wiring, reused)

Each matter gets a directory under here holding its `matter.json`. The opencode mount's
provider `baseURL` points at `http://127.0.0.1:7373/v1/m/<matter_ref>`, so opencode's own
provider wiring carries matter identity to the gate — the identity form proven live by
S7f's C7. Precedence in the proxy: `X-IronFleet-Matter` header, then the `/v1/m/<ref>`
path, then this `matter.json`. An unregistered matter is refused (`500
matter_unavailable`): no passthrough, no default matter.
"""


@dataclass(frozen=True)
class Entry:
    """One file in the staged distribution.

    kind:  plist       -> payload selects INFO_PLIST or LAUNCHD_PLIST, dumped as XML
           binary-slot -> a placeholder; pack_macos.sh replaces it on a Mac
           text        -> payload is the file content
           copy        -> payload is a repo-relative source under MANIFEST_COPIES_ROOT
           pins        -> generated from PINS
    """
    relpath: str
    kind: str
    payload: str = ""


def manifest_entries() -> list[Entry]:
    return [
        Entry("Contents/Info.plist", "plist"),
        Entry(f"Contents/MacOS/{LAUNCHER_NAME}", "binary-slot"),
        Entry(f"Contents/Resources/launchd/{LAUNCHD_LABEL}.plist", "plist"),
        Entry("Contents/Resources/PINS.txt", "pins"),
        Entry("Contents/Resources/mount/matters/README.md", "text", MOUNT_README),
        Entry("Contents/Resources/ops/p07_setup_macos.sh", "copy",
              "src/harness/ops/p07_setup_macos.sh"),
        Entry("Contents/Resources/ops/p07_verify_macos.sh", "copy",
              "src/harness/ops/p07_verify_macos.sh"),
        Entry("Contents/Resources/ops/verify_macos_install.sh", "copy",
              "src/harness/ops/verify_macos_install.sh"),
    ]


class PackagingError(ValueError):
    """The recipe is internally inconsistent. The message names the offending key."""
