# tests/test_pack_macos.sh guard — the script must not half-build off macOS
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/harness/ops/pack_macos.sh"


@pytest.mark.skipif(platform.system() == "Darwin",
                    reason="the guard is a non-macOS property; on macOS the script builds")
def test_pack_macos_refuses_off_macos_and_builds_nothing(tmp_path):
    # PyInstaller does not cross-compile. Without this guard a Windows run would stage
    # a layout whose MacOS/ binary is a PLACEHOLDER and present it as a build.
    # Resolve the interpreter rather than passing a bare "bash": on this box PATH also
    # exposes WSL's bash, which cannot open Windows paths and would 127 instead of
    # exercising the guard. shutil.which selects the same Git Bash the skip check gates on.
    bash_bin = shutil.which("bash")
    if not bash_bin:
        pytest.skip("bash unavailable (Git Bash is present on this dev box)")
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
