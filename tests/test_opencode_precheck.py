# tests/test_opencode_precheck.py
import hashlib
import json

from harness.security.opencode_precheck import (
    ScanResult, scan_install_tree, owning_package)


def test_dep_lifecycle_scripts_are_critical_and_plain_install_counts():
    files = {
        "package.json": '{"name":"opencode-ai","license":"MIT","scripts":{"postinstall":"node ./postinstall.mjs"}}',
        "node_modules/opencode-windows-x64/package.json": '{"name":"opencode-windows-x64","license":"MIT"}',
        "node_modules/foo/package.json": '{"name":"foo","license":"MIT","scripts":{"install":"node build.js"}}',
        "node_modules/bar/package.json": '{"name":"bar"}',
    }
    ts = scan_install_tree("t1", "/x", files)
    assert ts.packages == 4
    assert ts.missing_licence == 1
    assert [(f.package, f.script) for f in ts.lifecycle] == [
        ("opencode-ai", "postinstall"), ("foo", "install")]
    assert ScanResult(trees=[ts]).critical_findings == 2   # ANY package in the dist tree


def test_non_lifecycle_scripts_and_bad_json_ignored():
    files = {
        "package.json": '{"name":"r","license":"MIT","scripts":{"test":"pytest","start":"node ."}}',
        "broken/package.json": "not json",
        "weird/package.json": "[]",
    }
    ts = scan_install_tree("t1", "/x", files)
    assert ts.lifecycle == [] and ts.packages == 1


def test_owning_package_scopes_and_root():
    assert owning_package("node_modules/@scope/pkg/dist/x.node") == "@scope/pkg"
    assert owning_package("node_modules/foo/a.exe") == "foo"
    assert owning_package("bin/opencode.exe") == "(root)"


from harness.security.opencode_precheck import (
    is_floating, scan_runtime_manifest, scan_opencode_json)


def test_is_floating():
    for s in ("^3.0.41", "~1.2.3", ">=2.0.0", "", "*", "latest", "x",
              "1.x", "1.2.x", ">1.0.0", "<2"):
        assert is_floating(s), s
    for s in ("1.18.25", "file:../x"):
        assert not is_floating(s), s


def test_runtime_manifest_floating_deps_flagged_pinned_ignored():
    text = json.dumps({"dependencies": {
        "@ai-sdk/openai-compatible": "^3.0.41",
        "@opencode-ai/plugin": "1.18.25"}})
    fs = scan_runtime_manifest("t2", "~/.config/opencode/package.json", text)
    assert [(f.field, f.spec) for f in fs] == [
        ("dependencies.@ai-sdk/openai-compatible", "^3.0.41")]
    assert scan_runtime_manifest("t", "p", "[]") == []
    assert scan_runtime_manifest("t", "p", "null") == []
    assert scan_runtime_manifest("t", "p", '{"dependencies": "1.0"}') == []


def test_opencode_json_provider_npm_refs():
    text = json.dumps({"provider": {
        "ollama-local": {"npm": "@ai-sdk/openai-compatible", "options": {}},
        "pinned": {"npm": "@scope/pkg@1.18.25"},
        "float": {"npm": "pkg@^3.0.41"}}})
    fs = scan_opencode_json("t4", "opencode.json", text)
    assert [(f.field, f.spec) for f in fs] == [
        ("provider.ollama-local.npm", "(none)"),
        ("provider.float.npm", "^3.0.41")]
    assert scan_opencode_json("t", "p", '{"provider": []}') == []
