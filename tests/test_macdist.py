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


def test_stage_distribution_writes_every_entry(tmp_path):
    from harness.packaging.macdist import stage_distribution, validate_distribution
    app = stage_distribution(tmp_path / "dist")
    assert app.name == APP_NAME
    # the whole point of staging on Windows: the tree is complete and machine-checkable
    assert validate_distribution(tmp_path / "dist") == []


def test_staged_plists_parse_and_match_the_templates(tmp_path):
    import plistlib
    from harness.packaging.macdist import stage_distribution
    app = stage_distribution(tmp_path / "dist")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert info == INFO_PLIST
    agent = plistlib.loads((app / f"Contents/Resources/launchd/{LAUNCHD_LABEL}.plist").read_bytes())
    # ProgramArguments is injected: launchd needs the absolute bundle path
    assert agent["ProgramArguments"] == [str(app / "Contents/MacOS" / LAUNCHER_NAME)]
    assert agent["WorkingDirectory"] == str(app / "Contents/Resources")
    assert agent["Label"] == LAUNCHD_LABEL


def test_staged_pins_file_names_the_pinned_opencode(tmp_path):
    from harness.packaging.macdist import stage_distribution
    app = stage_distribution(tmp_path / "dist")
    text = (app / "Contents/Resources/PINS.txt").read_text(encoding="utf-8")
    assert "opencode=opencode-ai@1.18.25" in text
    assert "autoupdate=false" in text


def test_binary_slot_is_a_placeholder_not_an_executable(tmp_path):
    # This is what keeps a Windows staging build from being mistaken for a built app.
    from harness.packaging.macdist import is_binary_slot_placeholder, stage_distribution
    app = stage_distribution(tmp_path / "dist")
    launcher = app / "Contents/MacOS" / LAUNCHER_NAME
    assert is_binary_slot_placeholder(app)
    assert "PLACEHOLDER" in launcher.read_text(encoding="utf-8")
    assert DUE_FOR_MAC in launcher.read_text(encoding="utf-8")


def test_validate_distribution_rejects_a_missing_file(tmp_path):
    from harness.packaging.macdist import stage_distribution, validate_distribution
    root = tmp_path / "dist"
    stage_distribution(root)
    (root / APP_NAME / "Contents/Resources/PINS.txt").unlink()
    problems = validate_distribution(root)
    assert any("PINS.txt" in p and "missing" in p for p in problems)


def test_validate_distribution_rejects_an_unexpected_file(tmp_path):
    from harness.packaging.macdist import stage_distribution, validate_distribution
    root = tmp_path / "dist"
    stage_distribution(root)
    (root / APP_NAME / "Contents/Resources/stray.txt").write_text("nope", encoding="utf-8")
    assert any("stray.txt" in p for p in validate_distribution(root))


def test_validate_distribution_rejects_a_drifted_copy(tmp_path):
    # A staged op that no longer matches its repo source would ship a stale script.
    from harness.packaging.macdist import stage_distribution, validate_distribution
    root = tmp_path / "dist"
    stage_distribution(root)
    target = root / APP_NAME / "Contents/Resources/ops/p07_verify_macos.sh"
    target.write_text("# tampered\n", encoding="utf-8")
    assert any("drifted" in p for p in validate_distribution(root))


def test_validate_plist_data_rejects_a_launchd_plist_without_programarguments():
    from harness.packaging.macdist import validate_plist_data
    with pytest.raises(PackagingError) as exc:
        validate_plist_data({"Label": LAUNCHD_LABEL, "RunAtLoad": True}, launchd=True)
    assert "ProgramArguments" in str(exc.value)


def test_validate_plist_data_rejects_an_empty_label():
    from harness.packaging.macdist import validate_plist_data
    with pytest.raises(PackagingError) as exc:
        validate_plist_data({"Label": "", "ProgramArguments": ["/bin/true"]}, launchd=True)
    assert "Label" in str(exc.value)


def test_validate_plist_data_rejects_a_bad_keepalive():
    # KeepAlive is bool-or-dict; a string would load but do something unintended.
    from harness.packaging.macdist import validate_plist_data
    with pytest.raises(PackagingError) as exc:
        validate_plist_data({"Label": LAUNCHD_LABEL, "ProgramArguments": ["/bin/true"],
                             "KeepAlive": "yes"}, launchd=True)
    assert "KeepAlive" in str(exc.value)


def test_validate_plist_data_accepts_a_well_formed_launchd_plist():
    from harness.packaging.macdist import validate_plist_data
    validate_plist_data({"Label": LAUNCHD_LABEL, "ProgramArguments": ["/bin/true"],
                         "KeepAlive": True}, launchd=True)   # no raise


def test_validate_plist_data_rejects_an_info_plist_without_a_bundle_id():
    from harness.packaging.macdist import validate_plist_data
    with pytest.raises(PackagingError) as exc:
        validate_plist_data({"CFBundleName": "x"}, launchd=False)
    assert "CFBundleIdentifier" in str(exc.value)


def test_validate_launchd_labels_rejects_a_duplicate():
    from harness.packaging.macdist import validate_launchd_labels
    with pytest.raises(PackagingError) as exc:
        validate_launchd_labels([LAUNCHD_LABEL, LAUNCHD_LABEL])
    assert "duplicate" in str(exc.value)


def test_validate_launchd_labels_accepts_distinct_labels():
    from harness.packaging.macdist import validate_launchd_labels
    validate_launchd_labels(["a.b.c", "a.b.d"])   # no raise


def test_validate_distribution_rejects_an_unparseable_plist(tmp_path):
    from harness.packaging.macdist import stage_distribution, validate_distribution
    root = tmp_path / "dist"
    stage_distribution(root)
    (root / APP_NAME / "Contents/Info.plist").write_text(
        "<plist><dict><key>a</key></dict></plist>", encoding="utf-8")   # unbalanced
    assert any("does not parse" in p for p in validate_distribution(root))


def test_stage_distribution_raises_for_a_missing_copy_source(tmp_path, monkeypatch):
    from harness.packaging.macdist import Entry, manifest_entries, stage_distribution
    monkeypatch.setattr(macdist, "manifest_entries", lambda: [
        Entry("Contents/Resources/ops/nope.sh", "copy", "src/harness/ops/does-not-exist.sh")])
    with pytest.raises(FileNotFoundError) as exc:
        stage_distribution(tmp_path / "dist")
    assert "does-not-exist.sh" in str(exc.value)


def test_validate_plist_data_rejects_a_non_dict_root():
    # A plist whose root is not a dict is not a launchd or Info plist at all; reading one
    # back would hand the rest of the pipeline a list where it expects keys.
    from harness.packaging.macdist import validate_plist_data
    with pytest.raises(PackagingError) as exc:
        validate_plist_data(["CFBundleIdentifier"], launchd=False)
    assert "plist root is not a dict" in str(exc.value)


def test_validate_plist_data_rejects_an_info_plist_without_an_executable():
    # Finder launches CFBundleExecutable; an empty one names no binary to run.
    from harness.packaging.macdist import validate_plist_data
    with pytest.raises(PackagingError) as exc:
        validate_plist_data({"CFBundleIdentifier": BUNDLE_ID}, launchd=False)
    assert "CFBundleExecutable" in str(exc.value)


def test_validate_plist_data_rejects_empty_programarguments():
    # A present-but-empty list is as broken as a missing one: launchd would run nothing.
    from harness.packaging.macdist import validate_plist_data
    with pytest.raises(PackagingError) as exc:
        validate_plist_data({"Label": LAUNCHD_LABEL, "ProgramArguments": []}, launchd=True)
    assert "ProgramArguments" in str(exc.value)


def test_is_binary_slot_placeholder_is_false_for_a_real_macho(tmp_path):
    # The negative control for the placeholder check: a real Mach-O magic means
    # pack_macos.sh has run and the tree is an actual build, not a Windows staging.
    from harness.packaging.macdist import is_binary_slot_placeholder, stage_distribution
    app = stage_distribution(tmp_path / "dist")
    launcher = app / "Contents/MacOS" / LAUNCHER_NAME
    launcher.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 1024)   # 64-bit Mach-O magic
    assert is_binary_slot_placeholder(app) is False
