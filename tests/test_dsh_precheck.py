# tests/test_dsh_precheck.py
from harness.security.dsh_precheck import scan_package_jsons

def test_flags_lifecycle_scripts_and_missing_licence():
    files = {
        "package.json": '{"name":"root","license":"MIT","scripts":{"postinstall":"node setup.js"}}',
        "vendor/cordis/package.json": '{"name":"cordis","scripts":{"prepare":"echo hi"}}',
        "packages/a/package.json": '{"name":"a"}',                      # no licence field
    }
    rep = scan_package_jsons(files)
    assert rep.lifecycle_scripts == [("root", "postinstall"), ("cordis", "prepare")]
    assert rep.packages == 3 and rep.missing_licence == 2  # cordis AND packages/a lack licence fields
    assert rep.critical_findings == 1                                  # root-level install-time execution

def test_windows_path_separators_count_vendored():
    files = {                                                          # Path.relative_to yields backslashes on Windows
        "package.json": '{"name":"root","license":"MIT"}',
        "vendor\\cordis\\package.json": '{"name":"cordis","license":"MIT"}',
        "packages\\a\\package.json": '{"name":"a","license":"MIT"}',
    }
    rep = scan_package_jsons(files)
    assert rep.packages == 3 and rep.vendored == 1 and rep.critical_findings == 0
