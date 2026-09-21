# tests/test_alias.py
import pytest
from pathlib import Path
from harness.alias import load_aliases, resolve_alias, UnknownAlias

ALIAS_YAML = """\
aliases:
  gate/extraction: {task_class: extraction}
  gate/drafting:   {task_class: drafting}
rules:
  - task_class: extraction
    local_only: [ollama-local]
defaults:
  local_only: []
"""

def _aliases(tmp_path, yaml_text=ALIAS_YAML):
    p = tmp_path / "routing.yaml"; p.write_text(yaml_text)
    return load_aliases(p)

def test_resolve_known_alias(tmp_path):
    assert resolve_alias("gate/extraction", _aliases(tmp_path)) == "extraction"

def test_unknown_alias_raises(tmp_path):
    with pytest.raises(UnknownAlias, match="gate/nonsense"):
        resolve_alias("gate/nonsense", _aliases(tmp_path))

def test_bare_model_name_raises(tmp_path):
    # A raw "thomson1:latest" is not a gate alias — it must not silently pass as a class.
    with pytest.raises(UnknownAlias, match="thomson1:latest"):
        resolve_alias("thomson1:latest", _aliases(tmp_path))

def test_malformed_entry_raises_unknown_alias(tmp_path):
    # Present in the map but unusable: same failure as absent, same exception type.
    # Task 3's proxy catches UnknownAlias for a 400; a bare KeyError would 500.
    broken = _aliases(tmp_path, """\
aliases:
  gate/extraction: {task_class: extraction}
  gate/broken:     {}
  gate/scalar:     not-a-mapping
rules: []
defaults: {local_only: []}
""")
    for model in ("gate/broken", "gate/scalar"):
        with pytest.raises(UnknownAlias, match=model):
            resolve_alias(model, broken)
    # The argument is the model string the caller sent, not the malformed entry.
    with pytest.raises(UnknownAlias) as excinfo:
        resolve_alias("gate/broken", broken)
    assert excinfo.value.args[0] == "gate/broken"

def test_aliases_default_empty_when_absent(tmp_path):
    # A routing table without an aliases section resolves nothing.
    p = tmp_path / "r.yaml"
    p.write_text("rules: []\ndefaults: {local_only: []}\n")
    assert load_aliases(p) == {}
    with pytest.raises(UnknownAlias, match="gate/extraction"):
        resolve_alias("gate/extraction", load_aliases(p))

def test_aliases_rejects_non_mapping(tmp_path):
    # Fail closed on malformed data rather than passing an unrecognised string through.
    p = tmp_path / "bad.yaml"
    p.write_text("aliases: [not, a, mapping]\nrules: []\ndefaults: {local_only: []}\n")
    with pytest.raises(ValueError):
        load_aliases(p)
