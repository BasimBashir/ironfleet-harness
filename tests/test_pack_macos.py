# tests/test_pack_macos.sh guard — the script must not half-build off macOS
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/harness/ops/pack_macos.sh"


def _git_bash() -> str | None:
    """Git Bash, NOT WSL's bash. This box's PATH exposes
    C:\\WINDOWS\\system32\\bash.EXE first, and it cannot open Windows paths at all —
    it 127s on a perfectly valid script path (observed live 2026-10-19: the macOS
    pack guard "failed" with 127 while the script was fine). Prefer the Program
    Files installs; fall back to which("bash") only when it is not WSL."""
    for cand in (r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if Path(cand).is_file():
            return cand
    b = shutil.which("bash")
    if b and "system32" not in b.lower():
        return b
    return None


@pytest.mark.skipif(platform.system() == "Darwin",
                    reason="the guard is a non-macOS property; on macOS the script builds")
def test_pack_macos_refuses_off_macos_and_builds_nothing(tmp_path):
    # PyInstaller does not cross-compile. Without this guard a Windows run would stage
    # a layout whose MacOS/ binary is a PLACEHOLDER and present it as a build.
    bash_bin = _git_bash()
    if not bash_bin:
        pytest.skip("no non-WSL bash on this box (Git Bash is present on this dev box)")
    env_dir = tmp_path / "dist"
    r = subprocess.run([bash_bin, str(SCRIPT)], capture_output=True, text=True,
                       cwd=ROOT)
    assert r.returncode == 2, r.stderr
    assert "due-for-Mac (S7g-M)" in r.stderr
    # the guard runs first: nothing was created
    assert not env_dir.exists()
    assert not (ROOT / "dist").exists()


def test_pack_macos_script_marks_its_mac_only_steps():
    # Every step that cannot run here carries an S7g-M marker, so a reader can see the
    # boundary between the portable staging layer and the Mac build without running it.
    text = SCRIPT.read_text(encoding="utf-8")
    assert "S7g-W boundary" in text            # the boundary is named
    assert text.count("# S7g-M") >= 4          # pyinstaller, codesign, notarize, dmg
    assert "pyinstaller" in text.lower()
    assert "codesign" in text
    assert "notarytool" in text
