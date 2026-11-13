# the frozen exe must honour `exe -c CODE args` (ingest parse child), `exe -m mod`
# (module_e tools shim) and `exe script.py` (module_e guard_cli) instead of relaunching
import sys

from harness.ops.ironfleet_app import run_dash_c

_CHILD = ("import sys\nfrom pathlib import Path\n"
          "Path(sys.argv[2]).write_text(sys.argv[1])\n")


def test_dash_c_runs_code_with_python_argv(tmp_path, monkeypatch):
    out = tmp_path / "o.txt"
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    code = "import sys; from pathlib import Path; Path(sys.argv[2]).write_text(sys.argv[1])"
    assert run_dash_c(["IronFleet.exe", "-c", code, "hello", str(out)])
    assert out.read_text() == "hello"


def test_dash_m_runs_module(tmp_path, monkeypatch):
    pkg = tmp_path / "dashm_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(_CHILD, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    out = tmp_path / "o2.txt"
    assert run_dash_c(["IronFleet.exe", "-m", "dashm_pkg.mod", "yo", str(out)])
    assert out.read_text() == "yo"


def test_script_py_runs_with_python_argv(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    out = tmp_path / "o3.txt"
    assert run_dash_c(["IronFleet.exe", str(script), "hey", str(out)])
    assert out.read_text() == "hey"


def test_plain_launch_is_not_dash_c():
    assert not run_dash_c(["IronFleet.exe"])
    assert not run_dash_c(["IronFleet.exe", "missing-script.py"])
