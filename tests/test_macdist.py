# tests/test_macdist.py — the macOS distribution as data (spec §4.2)
import plistlib

import pytest

from harness.packaging import macdist
from harness.packaging.macdist import (
    APP_NAME, BUNDLE_ID, DUE_FOR_MAC, INFO_PLIST, LAUNCHD_LABEL, LAUNCHD_PLIST,
    LAUNCHER_NAME, MANIFEST_COPIES_ROOT, PINS, PackagingError, manifest_entries,
)


def test_pins_are_the_m0_decided_versions():
    # One string in one place. A ruling that bumps the Windows leg bumps this too; this
    # test pins the CURRENT decision so a casual edit cannot silently change what the
    # installer bootstraps.
    assert PINS["opencode"] == "opencode-ai@1.18.25"
    assert PINS["autoupdate"] is False


def test_manifest_entries_cover_the_bundle_layout():
    rels = {e.relpath for e in manifest_entries()}
    assert "Contents/Info.plist" in rels
    assert f"Contents/MacOS/{LAUNCHER_NAME}" in rels
    assert f"Contents/Resources/launchd/{LAUNCHD_LABEL}.plist" in rels
    assert "Contents/Resources/PINS.txt" in rels
    # every op that ships in the bundle is a real repo file, not a promise
    for e in manifest_entries():
        if e.kind == "copy":
            assert (MANIFEST_COPIES_ROOT / e.payload).is_file(), e.payload


def test_every_entry_kind_is_known():
    # An unknown kind would make stage_distribution raise at build time on a Mac —
    # better to fail a test here than at signing time.
    for e in manifest_entries():
        assert e.kind in {"plist", "binary-slot", "text", "copy", "pins"}, e


def test_info_plist_carries_the_keys_macos_requires():
    assert INFO_PLIST["CFBundleIdentifier"] == BUNDLE_ID
    assert INFO_PLIST["CFBundleExecutable"] == LAUNCHER_NAME
    assert INFO_PLIST["CFBundleName"]


def test_launchd_plist_template_has_no_programarguments():
    # Deliberate: launchd needs an ABSOLUTE path, which is only known at staging time.
    # The template carries everything else; stage_distribution injects this pair.
    assert "ProgramArguments" not in LAUNCHD_PLIST
    assert LAUNCHD_PLIST["Label"] == LAUNCHD_LABEL
    assert LAUNCHD_PLIST["KeepAlive"] is True


def test_pins_and_plists_round_trip_through_plistlib():
    # plistlib is stdlib and cross-platform: this is the check that works on Windows.
    # If a value we put in a plist cannot survive a dump/load cycle, the staged file
    # would not be the plist we intended.
    round_tripped = plistlib.loads(plistlib.dumps(INFO_PLIST, fmt=plistlib.FMT_XML))
    assert round_tripped == INFO_PLIST
    round_tripped = plistlib.loads(plistlib.dumps(LAUNCHD_PLIST, fmt=plistlib.FMT_XML))
    assert round_tripped == LAUNCHD_PLIST


def test_due_for_mac_is_a_stable_string():
    # The driver and pack_macos.sh print this verbatim; a drifting message would make
    # the due-for-Mac assertion brittle.
    assert DUE_FOR_MAC == "due-for-Mac (S7g-M)"
