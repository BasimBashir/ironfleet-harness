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


_PLACEHOLDER = (
    f"PLACEHOLDER — {DUE_FOR_MAC}. pack_macos.sh replaces this file with the "
    f"PyInstaller binary. It is NOT an executable and must not be shipped as-is.\n"
)

# Mach-O magics, so a Windows staging build can be proven free of a native binary:
# 32-bit, 64-bit, and fat/universal.
_MACHO_MAGICS = {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe",
                 b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"}


def stage_distribution(root: Path, *, launcher: str = LAUNCHER_NAME) -> Path:
    """Write the bundle layout described by the manifest under `root`.

    Returns the `.app` path. Raises FileNotFoundError if a copy source is missing —
    a recipe that names a file that isn't there is a build error, not a warning.
    """
    app = root / APP_NAME
    for entry in manifest_entries():
        target = app / entry.relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.kind == "plist":
            if entry.relpath == "Contents/Info.plist":
                data = dict(INFO_PLIST)
            else:
                # launchd resolves neither ~ nor relative paths; the absolute bundle
                # path is known only here, so ProgramArguments is injected, not templated.
                data = dict(LAUNCHD_PLIST)
                data["ProgramArguments"] = [str(app / "Contents/MacOS" / launcher)]
                data["WorkingDirectory"] = str(app / "Contents/Resources")
            target.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_XML))
        elif entry.kind == "binary-slot":
            target.write_text(_PLACEHOLDER, encoding="utf-8")
        elif entry.kind == "text":
            target.write_text(entry.payload, encoding="utf-8")
        elif entry.kind == "pins":
            lines = [f"opencode={PINS['opencode']}",
                     f"autoupdate={str(PINS['autoupdate']).lower()}"]
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif entry.kind == "copy":
            src = MANIFEST_COPIES_ROOT / entry.payload
            if not src.is_file():
                raise FileNotFoundError(f"manifest copy source missing: {entry.payload}")
            target.write_bytes(src.read_bytes())
        else:                                    # pragma: no cover - guarded by a test
            raise PackagingError(f"unknown manifest kind {entry.kind!r} for {entry.relpath}")
    return app


def is_binary_slot_placeholder(app: Path) -> bool:
    """True while the launcher is still the placeholder, i.e. S7g-M has not run.

    The property that lets a Windows build be honestly labelled 'not a build': the tree
    is complete, but the one native thing in it is a note saying it is missing.
    """
    launcher = app / "Contents/MacOS" / LAUNCHER_NAME
    if not launcher.is_file():
        return False
    head = launcher.read_bytes()[:4]
    if head in _MACHO_MAGICS:
        return False                       # a real Mach-O: the Mac build has run
    return "PLACEHOLDER" in launcher.read_text(encoding="utf-8")


def validate_plist_data(data: Any, *, launchd: bool) -> None:
    """Schema-check a plist's keys. Raises PackagingError naming the offending key.

    Deliberately narrow: it covers exactly the keys this module's own plists use. It is
    not a general plist linter — that would be scope the Mac step does not need.
    """
    if not isinstance(data, dict):
        raise PackagingError("plist root is not a dict")
    if launchd:
        label = data.get("Label")
        if not isinstance(label, str) or not label:
            raise PackagingError("launchd plist: Label missing or empty")
        args_ = data.get("ProgramArguments")
        if not (isinstance(args_, list) and args_
                and all(isinstance(a, str) and a for a in args_)):
            raise PackagingError(f"launchd plist {label}: ProgramArguments missing or empty")
        keep_alive = data.get("KeepAlive")
        if keep_alive is not None and not isinstance(keep_alive, (bool, dict)):
            raise PackagingError(f"launchd plist {label}: KeepAlive must be bool or dict")
    else:
        if not data.get("CFBundleIdentifier"):
            raise PackagingError("Info.plist: CFBundleIdentifier missing or empty")
        if not data.get("CFBundleExecutable"):
            raise PackagingError("Info.plist: CFBundleExecutable missing or empty")


def validate_launchd_labels(labels: list[str]) -> None:
    """Two agents may not share a Label — launchd keys its registry by label."""
    seen: set[str] = set()
    for label in labels:
        if label in seen:
            raise PackagingError(f"duplicate launchd Label: {label}")
        seen.add(label)


def validate_distribution(root: Path) -> list[str]:
    """Every problem with a staged tree, or [] if it is sound.

    Collects rather than raising so one run reports every defect — a Mac session should
    fix the whole list, not iterate one crash at a time.
    """
    app = root / APP_NAME
    problems: list[str] = []
    expected = {e.relpath for e in manifest_entries()}

    for rel in sorted(expected):
        if not (app / rel).is_file():
            problems.append(f"missing staged file: {rel}")
    for f in sorted(p for p in app.rglob("*") if p.is_file()):
        # as_posix: MANIFEST relpaths use forward slashes on every OS
        rel = f.relative_to(app).as_posix()
        if rel not in expected:
            problems.append(f"unexpected staged file: {rel}")

    labels: list[str] = []
    for entry in manifest_entries():
        if entry.kind != "plist":
            continue
        target = app / entry.relpath
        if not target.is_file():
            continue                       # already reported as missing
        try:
            data = plistlib.loads(target.read_bytes())
        except Exception as exc:           # plistlib raises several types
            problems.append(f"plist does not parse: {entry.relpath} ({exc})")
            continue
        launchd = entry.relpath != "Contents/Info.plist"
        try:
            validate_plist_data(data, launchd=launchd)
        except PackagingError as exc:
            problems.append(str(exc))
        if launchd and isinstance(data, dict) and isinstance(data.get("Label"), str):
            labels.append(data["Label"])
    try:
        validate_launchd_labels(labels)
    except PackagingError as exc:
        problems.append(str(exc))

    for entry in manifest_entries():       # a staged op must match its repo source
        if entry.kind != "copy":
            continue
        target = app / entry.relpath
        if target.is_file() and target.read_bytes() != (MANIFEST_COPIES_ROOT / entry.payload).read_bytes():
            problems.append(f"staged copy drifted from source: {entry.relpath}")
    return problems
