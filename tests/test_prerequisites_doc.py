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


def test_doc_names_every_registered_model():
    import yaml
    # R3 (2026-10-19): the spec table moved from bootstrap.py's source to
    # data/providers.yaml — one row per provider (url + model + engine + kind), which
    # is ALSO the user's provider/model/url swap surface. The doc must name every
    # registered model, discovered from the data file (never a hand-kept list).
    rows = yaml.safe_load((ROOT / "data" / "providers.yaml").read_text(encoding="utf-8"))
    models = {r["model"] for r in rows["providers"]}
    assert {"thomson1-chat:latest", "bge-m3:567m"} <= models  # the file parsed
    assert "stepfun-ai/step-5-preview" in models             # the R3 cloud row
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
