# tests/test_check_golden.py
import hashlib
import importlib.util
from pathlib import Path
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_golden.py"

def _load():
    spec = importlib.util.spec_from_file_location("check_golden", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

CASE_YAML = """\
id: gc-test-001-x
matter_type: voidable-transactions
task_class: analysis
prompt: |
  Advise whether the payment is recoverable.
expected_citations:
  - "Insolvency Act 2006, s 287"
required_grounding:
  - "voidable transaction"
persona_checks:
  recoverable: "recoverable"
"""

GOOD_REF = """\
The payment is recoverable as a voidable transaction: Insolvency Act 2006, s 287
makes a preferential payment voidable against the liquidator.
"""

SEED_YAML = """\
id: seed-ignore-001
matter_type: civil-litigation
task_class: analysis
prompt: |
  Synthetic seed - must be ignored by the checker.
expected_citations: []
required_grounding: []
persona_checks: {}
"""

def _fixture(tmp_path: Path) -> Path:
    cases = tmp_path / "golden_cases"; cases.mkdir()
    src = cases / "sources" / "Set_2"; src.mkdir(parents=True)
    (src / "judgment.pdf").write_bytes(b"%PDF-dummy")
    sha = hashlib.sha256(b"%PDF-dummy").hexdigest()
    (cases / "sources" / "MANIFEST.yaml").write_text(yaml.safe_dump({
        "manifest": [{"id": "gc-test-001-x", "sources": ["judgment.pdf"],
                      "citation": "Test v Test [2020] NZHC 1",
                      "sha256_per_source": [sha], "cluster": "voidable-transactions"}]}))
    (cases / "gc-test-001-x.yaml").write_text(CASE_YAML)
    (cases / "seed-ignore-001.yaml").write_text(SEED_YAML)
    refs = cases / "references"; refs.mkdir()
    (refs / "gc-test-001-x.md").write_text(GOOD_REF)
    return cases

def test_all_good_and_seeds_ignored(tmp_path):
    mod = _load()
    assert mod.check(_fixture(tmp_path)) == []

def test_sha_mismatch_detected(tmp_path):
    mod = _load()
    cases = _fixture(tmp_path)
    m = yaml.safe_load((cases / "sources" / "MANIFEST.yaml").read_text())
    m["manifest"][0]["sha256_per_source"] = ["0" * 64]
    (cases / "sources" / "MANIFEST.yaml").write_text(yaml.safe_dump(m))
    problems = mod.check(cases)
    assert any("sha256 mismatch" in p and "judgment.pdf" in p for p in problems)

def test_failing_reference_detected(tmp_path):
    mod = _load()
    cases = _fixture(tmp_path)
    (cases / "references" / "gc-test-001-x.md").write_text("No citations here at all.")
    problems = mod.check(cases)
    assert any("gc-test-001-x: reference answer fails" in p for p in problems)

def test_missing_yaml_and_reference_detected(tmp_path):
    mod = _load()
    cases = _fixture(tmp_path)
    (cases / "gc-test-001-x.yaml").unlink()
    problems = mod.check(cases)
    assert any("no golden-case YAML" in p for p in problems)

def test_cluster_filter(tmp_path):
    mod = _load()
    cases = _fixture(tmp_path)
    m = yaml.safe_load((cases / "sources" / "MANIFEST.yaml").read_text())
    m["manifest"].append({"id": "gc-test-002-y", "sources": ["other.pdf"],
                          "citation": "Other v Other [2021] NZHC 2",
                          "sha256_per_source": ["1" * 64], "cluster": "receivership"})
    (cases / "sources" / "MANIFEST.yaml").write_text(yaml.safe_dump(m))
    # unfiltered: both the missing source file and missing YAML for gc-test-002-y
    assert any("gc-test-002-y" in p for p in mod.check(cases))
    # filtered to voidable-transactions: only gc-test-001-x is checked -> clean
    assert mod.check(cases, cluster="voidable-transactions") == []

def test_orphan_yaml_detected(tmp_path):
    mod = _load()
    cases = _fixture(tmp_path)
    # Add a YAML with no corresponding manifest entry
    orphan_yaml = CASE_YAML.replace("gc-test-001-x", "gc-orphan-no-entry")
    (cases / "gc-orphan-no-entry.yaml").write_text(orphan_yaml)
    problems = mod.check(cases)
    assert any("gc-orphan-no-entry: YAML without manifest entry" in p for p in problems)

def test_orphan_yaml_with_cluster_filtering(tmp_path):
    mod = _load()
    cases = _fixture(tmp_path)
    # Add YAML for a different cluster's entry and an orphan
    m = yaml.safe_load((cases / "sources" / "MANIFEST.yaml").read_text())
    m["manifest"].append({"id": "gc-test-002-y", "sources": ["other.pdf"],
                          "citation": "Other v Other [2021] NZHC 2",
                          "sha256_per_source": ["1" * 64], "cluster": "receivership"})
    (cases / "sources" / "MANIFEST.yaml").write_text(yaml.safe_dump(m))
    other_yaml = CASE_YAML.replace("gc-test-001-x", "gc-test-002-y")
    (cases / "gc-test-002-y.yaml").write_text(other_yaml)
    orphan_yaml = CASE_YAML.replace("gc-test-001-x", "gc-orphan-z")
    (cases / "gc-orphan-z.yaml").write_text(orphan_yaml)
    # unfiltered: both the orphan and the missing source for gc-test-002-y
    unfiltered_problems = mod.check(cases)
    assert any("gc-orphan-z: YAML without manifest entry" in p for p in unfiltered_problems)
    assert any("gc-test-002-y" in p for p in unfiltered_problems)
    # filtered to voidable-transactions: orphan still fires, gc-test-002-y does NOT
    filtered_problems = mod.check(cases, cluster="voidable-transactions")
    assert any("gc-orphan-z: YAML without manifest entry" in p for p in filtered_problems)
    assert not any("gc-test-002-y" in p for p in filtered_problems)

def test_zero_match_cluster_fails(tmp_path):
    mod = _load()
    cases = _fixture(tmp_path)
    problems = mod.check(cases, cluster="no-such-cluster")
    assert any("matches no manifest entries" in p for p in problems)

def test_sources_sha256_length_mismatch(tmp_path):
    mod = _load()
    cases = _fixture(tmp_path)
    m = yaml.safe_load((cases / "sources" / "MANIFEST.yaml").read_text())
    # Create length mismatch: 2 sources but only 1 sha256
    m["manifest"][0]["sources"] = ["judgment.pdf", "another.pdf"]
    m["manifest"][0]["sha256_per_source"] = [hashlib.sha256(b"%PDF-dummy").hexdigest()]
    (cases / "sources" / "MANIFEST.yaml").write_text(yaml.safe_dump(m))
    problems = mod.check(cases)
    assert any("gc-test-001-x: sources/sha256_per_source length mismatch" in p for p in problems)
