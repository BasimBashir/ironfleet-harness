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


from pathlib import Path

from harness.security.opencode_precheck import (
    inventory_native_binaries, write_manifest, ScanResult)


def test_inventory_native_binaries_hashes_and_skips_others(tmp_path):
    pkg = tmp_path / "node_modules" / "opencode-windows-x64" / "bin"
    pkg.mkdir(parents=True)
    exe = pkg / "opencode.exe"
    exe.write_bytes(b"MZfake")
    (tmp_path / "readme.txt").write_text("skip")
    bins = inventory_native_binaries("t1", tmp_path)
    assert len(bins) == 1
    assert bins[0].sha256 == hashlib.sha256(b"MZfake").hexdigest()
    assert bins[0].size == 6
    assert bins[0].relpath == "node_modules/opencode-windows-x64/bin/opencode.exe"


def test_write_manifest_lines(tmp_path):
    from harness.security.opencode_precheck import NativeBinary
    res = ScanResult()
    res.native_binaries.append(NativeBinary(tree="t1", relpath="a.exe", sha256="ab" * 32, size=1))
    out = tmp_path / "manifest.txt"
    write_manifest(res, out)
    assert out.read_bytes() == f"{'ab' * 32}  t1/a.exe\n".encode()


def test_inventory_skips_unreadable_entries(tmp_path, monkeypatch):
    pkg = tmp_path / "node_modules" / "opencode-windows-x64" / "bin"
    pkg.mkdir(parents=True)
    good = pkg / "opencode.exe"
    good.write_bytes(b"MZok")
    trap = pkg / "locked.node"
    trap.write_bytes(b"trap")
    real_read_bytes = Path.read_bytes

    def boom(self):
        if self.name == "locked.node":
            raise OSError("permission denied")
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", boom)
    bins = inventory_native_binaries("t1", tmp_path)
    assert [(b.relpath, b.sha256) for b in bins] == [
        ("node_modules/opencode-windows-x64/bin/opencode.exe",
         hashlib.sha256(b"MZok").hexdigest())]


from harness.security.opencode_precheck import (
    TreeScan, main, write_scan_json)


def test_cli_smoke_writes_all_three_artifacts(tmp_path, capsys):
    tree = tmp_path / "fresh"
    (tree / "node_modules" / "foo").mkdir(parents=True)
    (tree / "package.json").write_text(
        '{"name":"opencode-ai","license":"MIT","scripts":{"postinstall":"node ./postinstall.mjs"}}')
    (tree / "node_modules" / "foo" / "package.json").write_text('{"name":"foo","license":"MIT"}')
    exe = tree / "node_modules" / "foo" / "pre.exe"
    exe.write_bytes(b"PE")
    man = tmp_path / "runtime-package.json"
    man.write_text('{"dependencies":{"@ai-sdk/openai-compatible":"^3.0.41"}}')
    out = tmp_path / "out"
    out.mkdir()
    rc = main([str(out), f"--tree=t1={tree}", f"--runtime-manifest=t1={man}"])
    assert rc == 0
    data = json.loads((out / "scan.json").read_text())
    assert data["trees"][0]["tree"] == "t1"
    assert any(f["field"] == "dependencies.@ai-sdk/openai-compatible"
               for f in data["trees"][0]["floating"])
    assert "- lifecycle scripts (CRITICAL until adjudicated): 1" in \
        (out / "mechanical-scan.md").read_text()
    assert "t1/node_modules/foo/pre.exe" in (out / "sha256-manifest.txt").read_text()
    assert "scanned" in capsys.readouterr().out


def test_cli_rejects_missing_tree_dir_before_writing(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    rc = main([str(out), f"--tree=t1={tmp_path / 'does-not-exist'}"])
    assert rc == 2
    assert list(out.iterdir()) == []
    assert "not a directory" in capsys.readouterr().err


def test_cli_rejects_missing_manifest_file(tmp_path, capsys):
    out = tmp_path / "out"
    rc = main([str(out), f"--runtime-manifest=t1={tmp_path / 'nope.json'}"])
    assert rc == 2
    assert not out.exists()
    assert "not a file" in capsys.readouterr().err


def test_cli_rejects_missing_opencode_json_file(tmp_path):
    rc = main([str(tmp_path / "out"),
               f"--opencode-json=t1={tmp_path / 'nope.json'}"])
    assert rc == 2


def test_write_scan_json_lf_bytes_and_trailing_newline(tmp_path):
    res = ScanResult(trees=[TreeScan(tree="t1", root="/x")])
    out = tmp_path / "scan.json"
    write_scan_json(res, out)
    raw = out.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert json.loads(raw.decode("utf-8"))["trees"][0]["tree"] == "t1"
