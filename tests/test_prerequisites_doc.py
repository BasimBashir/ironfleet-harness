"""PREREQUISITES.md cannot silently rot: every third-party pin the code registers
must be named in the doc, discovered FROM the code (R2 spec 15 s2.3)."""
from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "PREREQUISITES.md").read_text(encoding="utf-8")


def test_doc_names_the_opencode_pin():
    from harness.packaging.macdist import PINS
    assert PINS["opencode"] in DOC, f"doc must name the pinned {PINS['opencode']}"


def test_doc_names_the_tui_toolkit():
    # R3 spec 17 D-T1: Textual is the declared TUI dependency — a fresh box that
    # misses it has no shell at all, so the doc must name exactly what pyproject pins.
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    textual = next((d for d in deps["project"]["dependencies"] if d.startswith("textual")), None)
    assert textual is not None, "textual must be a pinned dependency (spec 17 D-T1)"
    assert textual in DOC, f"doc must name {textual}"


def test_doc_names_every_registered_model():
    import yaml
    # R3 (2026-10-19): the spec table moved from bootstrap.py's source to
    # data/providers.yaml — one row per provider (url + model + engine + kind), which
    # is ALSO the user's provider/model/url swap surface. The doc must name every
    # registered model, discovered from the data file (never a hand-kept list).
    rows = yaml.safe_load((ROOT / "data" / "providers.yaml").read_text(encoding="utf-8"))
    models = {r["model"] for r in rows["providers"]}
    assert {"thomson1-chat:latest", "bge-m3:567m"} <= models  # the file parsed
    assert "nvidia/nemotron-3.5-super-vl-120b-a12b" in models  # the R3 cloud row
    for m in sorted(models):
        assert m in DOC, f"doc must name registered model {m} (data/providers.yaml)"


def test_doc_names_pinned_python_deps():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pinned = [d for d in deps["project"]["dependencies"] if "==" in d]
    assert pinned, "expected at least one == pin in pyproject dependencies"
    for d in pinned:
        assert d in DOC, f"doc must name pinned dependency {d}"


def test_doc_names_the_local_servers_and_ports():
    for endpoint in ("127.0.0.1:11434", "127.0.0.1:7373", "127.0.0.1:8778"):
        assert endpoint in DOC, f"doc must name the local server {endpoint}"


def test_version_is_single_sourced():
    # M11 T1: pyproject's `version` is the single source (CHANGELOG header says so);
    # `harness.__version__` must equal it or the zip name, `harness --version` and
    # the doc's version story drift apart.
    import harness
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert harness.__version__ == deps["project"]["version"]


def test_changelog_covers_the_current_version():
    # M11 T1: every released version is recorded; the current one must have an entry.
    import harness
    cl = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"[{harness.__version__}]" in cl, "CHANGELOG.md must carry the current version"
