# tests/test_accept_s7g.py — the PURE parts of the S7g acceptance driver.
# main() runs the live Mac-only checks and is NEVER run in the suite (house rule).
import platform

import pytest

from harness.packaging.macdist import LAUNCHD_LABEL


@pytest.fixture(autouse=True)
def _no_harness_home(monkeypatch):
    # conftest's harness_home fixture sets HARNESS_HOME for tests that want it; here it
    # would mask every platform branch — check_c1 monkeypatches platform.system() but
    # resolve_store_root consults HARNESS_HOME FIRST, so with it set all three branches
    # answer the env branch and the headline C1 test passes while exercising zero
    # branches. tests/test_paths.py carries the same fixture for the same reason.
    monkeypatch.delenv("HARNESS_HOME", raising=False)


def test_check_c1_passes_when_every_os_resolves_with_a_source():
    # C1 is cross-OS by construction: the resolver is monkeypatched per platform because
    # platform.system() cannot be trusted to be Darwin on a Windows test box.
    from scripts.accept_s7g import check_c1
    assert check_c1() == []


def test_check_c1_reports_an_os_that_returns_no_source(monkeypatch):
    from harness import paths
    from scripts.accept_s7g import check_c1

    def broken():
        raise RuntimeError("probe failed")

    monkeypatch.setattr(paths, "resolve_store_root", broken)
    problems = check_c1()
    assert problems and any("resolve_store_root" in p for p in problems)


def test_check_c2_passes_on_a_staged_tree(tmp_path):
    from harness.packaging.macdist import stage_distribution
    from scripts.accept_s7g import check_c2
    stage_distribution(tmp_path / "dist")
    assert check_c2(tmp_path / "dist") == []


def test_check_c2_reports_a_malformed_plist(tmp_path):
    from harness.packaging.macdist import stage_distribution
    from scripts.accept_s7g import check_c2
    root = tmp_path / "dist"
    stage_distribution(root)
    agent = root / "IronFleet.app" / f"Contents/Resources/launchd/{LAUNCHD_LABEL}.plist"
    agent.write_text("<plist><dict><key>Label</key></dict></plist>", encoding="utf-8")
    assert any("does not parse" in p for p in check_c2(root))


def test_check_c3_passes_when_pins_and_manifest_are_sound(tmp_path):
    from harness.packaging.macdist import stage_distribution
    from scripts.accept_s7g import check_c3
    stage_distribution(tmp_path / "dist")
    assert check_c3(tmp_path / "dist") == []


def test_check_c3_reports_an_empty_pin(tmp_path, monkeypatch):
    # Stage first: check_c3 calls validate_distribution, and an unstaged root would make
    # this test pass on the "missing staged file" problems instead of the pin one — and
    # a bare "/" root would make it rglob an entire filesystem.
    from harness.packaging import macdist
    from harness.packaging.macdist import stage_distribution
    from scripts.accept_s7g import check_c3
    stage_distribution(tmp_path / "dist")
    monkeypatch.setitem(macdist.PINS, "opencode", "")
    assert any("opencode" in p for p in check_c3(tmp_path / "dist"))


def test_check_c4_reports_when_the_guard_cannot_be_proven(monkeypatch):
    # C4 proves pack_macos.sh refuses off macOS. If bash is unavailable the check must
    # REPORT that as a problem rather than silently skipping — a check that can't run
    # is not a check that passed.
    import scripts.accept_s7g as drv
    monkeypatch.setattr(drv.shutil, "which", lambda _: None)
    problems = drv.check_c4()
    assert problems and any("bash" in p for p in problems)


def test_check_c5_passes_on_a_staged_tree(tmp_path):
    from harness.packaging.macdist import stage_distribution
    from scripts.accept_s7g import check_c5
    stage_distribution(tmp_path / "dist")
    assert check_c5(tmp_path / "dist") == []


def test_check_c5_reports_an_unexpected_file(tmp_path):
    from harness.packaging.macdist import stage_distribution
    from scripts.accept_s7g import check_c5
    root = tmp_path / "dist"
    stage_distribution(root)
    (root / "IronFleet.app" / "Contents/Resources/stray.md").write_text(
        "nope", encoding="utf-8")
    assert any("stray.md" in p for p in check_c5(root))


@pytest.mark.skipif(platform.system() == "Darwin",
                    reason="on macOS the driver may proceed to the live checks")
def test_main_off_macos_exits_due_for_mac(tmp_path, monkeypatch):
    # THE CONTRACT: on Windows the honest outcome is exit 2 — static checks proven,
    # live checks not executable here, and NO verdict written for what did not run.
    import scripts.accept_s7g as drv
    monkeypatch.setattr(drv.shutil, "which", lambda _: True)
    monkeypatch.setattr(drv.subprocess, "run", lambda *a, **kw: type(
        "R", (), {"returncode": 2, "stderr": "due-for-Mac (S7g-M)", "stdout": ""})())
    assert drv.main() == 2


def test_live_checks_defers_to_verify_macos_install_sh(monkeypatch):
    # Fix 1: the decisive evidence for exit 0 comes from RUNNING verify_macos_install.sh,
    # not from probing that three binaries exist on PATH. This pins the wiring without
    # needing a Mac: (a) the script IS invoked at all, (b) a non-zero exit is a problem,
    # (c) a FAIL: line is a problem even at exit 0, (d) a clean script is a clean layer.
    import scripts.accept_s7g as drv
    monkeypatch.setattr(drv.shutil, "which", lambda _: "/usr/bin/bash")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(drv.subprocess, "run", run)
    problems = drv._live_checks()
    # (a) the "never invoked anywhere" state cannot silently return
    assert calls and any("verify_macos_install.sh" in arg for arg in calls[0])
    # (b) a non-zero exit is reported, not swallowed
    assert problems and any("exited 1" in p for p in problems)

    # (c) a FAIL: line counts even when the script exits 0
    monkeypatch.setattr(drv.subprocess, "run", lambda argv, **kw: type(
        "R", (), {"returncode": 0,
                  "stdout": "FAIL: opencode drift — installed 'x' != pinned 'y'",
                  "stderr": ""})())
    problems = drv._live_checks()
    assert any("opencode drift" in p for p in problems)

    # (d) a clean script with no FAIL lines is a clean live layer
    monkeypatch.setattr(drv.subprocess, "run", lambda argv, **kw: type(
        "R", (), {"returncode": 0, "stdout": "S7g install OK", "stderr": ""})())
    assert drv._live_checks() == []


@pytest.mark.skipif(platform.system() == "Darwin",
                    reason="the static layer is what can fail off macOS")
def test_main_returns_1_when_a_static_check_reports_a_problem(tmp_path, monkeypatch):
    # THE OTHER ARM OF THE CONTRACT: a check that CAN run on this host and fails is
    # exit 1 — never exit 2, which would relabel a genuine Windows-side defect as
    # "due-for-Mac" (spec §4.5 forbids exactly that misuse). The problems branch fires
    # before the Darwin branch, so this is decidable on any host.
    import scripts.accept_s7g as drv
    monkeypatch.setattr(drv.shutil, "which", lambda _: True)
    monkeypatch.setattr(drv.subprocess, "run", lambda *a, **kw: type(
        "R", (), {"returncode": 2, "stderr": "due-for-Mac (S7g-M)", "stdout": ""})())
    monkeypatch.setattr(drv, "check_c3",
                        lambda root: ["a check that could run on this host, failed"])
    assert drv.main() == 1
