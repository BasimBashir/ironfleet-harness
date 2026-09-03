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
    }
    ts = scan_install_tree("t1", "/x", files)
    assert ts.lifecycle == [] and ts.packages == 1


def test_owning_package_scopes_and_root():
    assert owning_package("node_modules/@scope/pkg/dist/x.node") == "@scope/pkg"
    assert owning_package("node_modules/foo/a.exe") == "foo"
    assert owning_package("bin/opencode.exe") == "(root)"
