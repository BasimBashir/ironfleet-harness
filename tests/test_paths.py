# tests/test_paths.py — the privileged store root, resolved once for every OS (spec §4.1)
import platform

import pytest

from harness import paths
from harness.paths import resolve_store_root


@pytest.fixture(autouse=True)
def _no_harness_home(monkeypatch):
    # conftest's harness_home fixture sets HARNESS_HOME for tests that want it; here it
    # would mask every platform branch, so clear it for the whole module by default.
    monkeypatch.delenv("HARNESS_HOME", raising=False)


def _system(monkeypatch, name):
    monkeypatch.setattr(paths.platform, "system", lambda: name)


def _home(monkeypatch, path):
    monkeypatch.setattr(paths.Path, "home", classmethod(lambda cls: path))


def test_harness_home_wins_on_every_os(monkeypatch):
    # HARNESS_HOME is the operator's override and takes precedence everywhere — including
    # on macOS, where it can relocate the store onto a differently-encrypted volume.
    _system(monkeypatch, "Darwin")
    monkeypatch.setenv("HARNESS_HOME", "/explicit/store")
    root, source = resolve_store_root()
    assert root.as_posix() == "/explicit/store"
    assert source == "HARNESS_HOME"


def test_empty_harness_home_does_not_win(monkeypatch):
    # An empty string is absent, not a path: fall through to the platform default.
    _system(monkeypatch, "Linux")
    monkeypatch.setenv("HARNESS_HOME", "")
    root, source = resolve_store_root()
    assert source == "xdg"
    assert root.name == "harness"


def test_macos_uses_the_encrypted_volume_when_present(monkeypatch, tmp_path):
    _system(monkeypatch, "Darwin")
    monkeypatch.setattr(paths, "_macos_volume_present", lambda: True)
    root, source = resolve_store_root()
    assert root.as_posix() == paths.MACOS_STORE
    assert source == "ironfleetpriv-volume"


def test_macos_falls_back_off_the_volume_and_names_it(monkeypatch, tmp_path):
    # The fallback is deliberate and LABELLED: a store off IronFleetPriv is a privilege
    # downgrade an operator must be able to see (CR-7 discipline). The source string is
    # how they see it.
    _system(monkeypatch, "Darwin")
    monkeypatch.setattr(paths, "_macos_volume_present", lambda: False)
    home = tmp_path / "operator"
    _home(monkeypatch, home)
    root, source = resolve_store_root()
    assert root == home / "Library" / "Application Support" / "IronFleet" / "harness"
    assert source == "library-fallback"


def test_windows_uses_localappdata(monkeypatch, tmp_path):
    _system(monkeypatch, "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    root, source = resolve_store_root()
    assert root == tmp_path / "AppData" / "Local" / "IronFleet" / "harness"
    assert source == "localappdata"


def test_windows_falls_back_to_home_without_localappdata(monkeypatch, tmp_path):
    # A service account may have no LOCALAPPDATA; the resolver still returns a root.
    _system(monkeypatch, "Windows")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    _home(monkeypatch, tmp_path / "svc")
    root, source = resolve_store_root()
    assert root == tmp_path / "svc" / "AppData" / "Local" / "IronFleet" / "harness"
    assert source == "localappdata"


def test_linux_uses_xdg_data_home(monkeypatch, tmp_path):
    _system(monkeypatch, "Linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    root, source = resolve_store_root()
    assert root == tmp_path / "xdg" / "ironfleet" / "harness"
    assert source == "xdg"


def test_linux_defaults_to_local_share(monkeypatch, tmp_path):
    _system(monkeypatch, "Linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    _home(monkeypatch, tmp_path / "op")
    root, source = resolve_store_root()
    assert root == tmp_path / "op" / ".local" / "share" / "ironfleet" / "harness"
    assert source == "xdg"


def test_an_unknown_os_still_resolves(monkeypatch, tmp_path):
    # Never raise: an unrecognised platform gets a home-relative root, not a crash —
    # the same never-raise contract machine_capacity() holds.
    _system(monkeypatch, "Plan9")
    _home(monkeypatch, tmp_path / "glenda")
    root, source = resolve_store_root()
    assert root.is_absolute()
    assert source == "home-relative (unknown platform Plan9)"


def test_constants_agree_with_the_ops_scripts():
    # p07_setup_macos.sh hardcodes this volume name; the core and the ops script must
    # agree on one constant, or the verifier's "on the encrypted volume" check drifts.
    assert paths.MACOS_VOLUME == "IronFleetPriv"
    assert paths.MACOS_STORE == "/Volumes/IronFleetPriv/harness"
