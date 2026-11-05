# tests/test_verify_opencode_mount.py
import subprocess, sys
from pathlib import Path
import pytest

RIG = Path(__file__).resolve().parent.parent / "scripts" / "verify_opencode_mount.py"

def test_rig_reports_pin_and_expected_version():
    from scripts.verify_opencode_mount import EXPECTED_VERSION, FALLBACK
    assert EXPECTED_VERSION == "1.18.25"
    assert FALLBACK == "pin-hold"

def test_version_match_passes(monkeypatch):
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.18.25")
    assert rig.verify_version() == []

def test_version_drift_is_reported(monkeypatch):
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.19.0")
    problems = rig.verify_version()
    assert problems and "1.19.0" in problems[0]

def test_guard_hook_names_present():
    # The seam list the guard will hang on — checked now so S7c inherits a verified mount.
    from scripts.verify_opencode_mount import GUARD_SEAMS
    assert set(GUARD_SEAMS) >= {"tool.execute.before", "tool.execute.after",
                                "experimental.text.complete"}

def test_rig_cli_runs(monkeypatch):
    # Never touch the real opencode in a unit test — stub the version probe.
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.18.25")
    rc = rig.main([])
    assert rc == 0

def test_installed_version_resolves_via_shutil_which(monkeypatch):
    # Windows CreateProcess does not apply PATHEXT, so a bare "opencode" never finds the npm
    # shim (opencode.CMD) and the rig reports a false "not found" — fail-closed against a
    # problem that does not exist, and the pin is never actually checked. The probe must go
    # through shutil.which. Regression guard for the failure observed on this box.
    from scripts import verify_opencode_mount as rig
    seen = {}
    class _R:
        stdout = "1.18.25"
        stderr = ""
        returncode = 0
    def fake_run(argv, **kw):
        seen["argv"] = argv
        return _R()
    monkeypatch.setattr(rig.shutil, "which", lambda name: "C:/npm/opencode.CMD")
    monkeypatch.setattr(rig.subprocess, "run", fake_run)
    assert rig.installed_version() == "1.18.25"
    assert seen["argv"][0] == "C:/npm/opencode.CMD", \
        "the resolved path must be what subprocess invokes, not the bare name"


# --- S7b final review, S1 + the behavioural-mount ruling ------------------------------
# Fixtures below are the REAL binary's output shapes, captured live 2026-10-01 on the pinned
# 1.18.25 in a synced mount workspace. The clean shape is what a scrubbed env must produce; the
# adversarial shape is what the same workspace resolves when the parent env holds credentials
# (anthropic 19, openai 61, amazon-bedrock 178 = 275 lines, truncated here to what the parser
# and the problem text need).

CLEAN_MODELS = (
    "opencode/big-pickle\nopencode/ling-3.0-flash-fin-free\nopencode/longcat-2.5-preview-free\n"
    "opencode/mimo-v2.6-flash-free\nopencode/muse-spark-1.3-contributor-free\n"
    "opencode/nemotron-3-ultra-free\nopencode/nemotron-3.5-lightning-free\n"
    "opencode/space-bunny-free\n"
    "gate-local/gate/analysis\ngate-local/gate/classification\ngate-local/gate/complex_reasoning\n"
    "gate-local/gate/drafting\ngate-local/gate/extraction\ngate-local/gate/grounding_check\n"
    "gate-local/gate/redaction\ngate-local/gate/research\ngate-local/gate/summarization\n"
)
KEYLESS_ONLY_MODELS = CLEAN_MODELS.split("gate-local/")[0]
ADVERSARIAL_MODELS = CLEAN_MODELS + (
    "anthropic/claude-opus-4.5\nanthropic/claude-sonnet-4.5\n"
    "openai/gpt-5.2\nopenai/gpt-5.2-mini\n"
    "amazon-bedrock/amazon.nova-pro-v1:0\namazon-bedrock/amazon.nova-micro-v1:0\n"
)


def _declared():
    import json
    mount = Path(__file__).resolve().parent.parent / "data" / "opencode-a1" / "opencode.json"
    return sorted(json.loads(mount.read_text(encoding="utf-8"))
                  ["provider"]["gate-local"]["models"])


def test_mount_suppresses_the_keyless_catalog_provider():
    # `opencode/*` ships as keyless builtin catalog models: 8 of them resolved live in a fully
    # scrubbed env, so NO env scrub can reach them — the mount must name the provider for
    # suppression instead. Verified live: with the key present, the resolved list is exactly
    # gate-local (9); without this key, the keyless 8 are selectable next to the gate.
    import json
    mount = Path(__file__).resolve().parent.parent / "data" / "opencode-a1" / "opencode.json"
    cfg = json.loads(mount.read_text(encoding="utf-8"))
    assert "opencode" in cfg.get("disabled_providers", []), \
        "the keyless builtin catalog provider must be suppressed — no env scrub reaches it"
    assert "gate-local" not in cfg["disabled_providers"], \
        "suppressing the gate provider would leave the mount with nothing to dispatch through"


def test_parse_models_reads_the_real_output():
    from scripts.verify_opencode_mount import parse_models
    models, unparsed = parse_models(CLEAN_MODELS)
    assert len(models) == 17
    assert {m.split("/")[0] for m in models} == {"opencode", "gate-local"}
    assert unparsed == []


def test_parse_models_surfaces_lines_it_cannot_read():
    # A future version that adds a header must not silently read as an empty/partial set: what
    # the parser cannot understand comes back as evidence, and verify_models fails loudly on it.
    from scripts.verify_opencode_mount import parse_models
    models, unparsed = parse_models("Available models:\ngate-local/gate/extraction\n")
    assert models == {"gate-local/gate/extraction"}
    assert unparsed == ["Available models:"]


def _verify(models_raw: str, rc: int = 0, monkeypatch=None):
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "list_models", lambda ws, env, timeout=300: (rc, models_raw))
    return rig.verify_models(Path("C:/ws"), {"OPENCODE_DISABLE_MODELS_FETCH": "1"})


def test_verify_models_passes_on_gate_local_only(monkeypatch):
    from scripts.verify_opencode_mount import GATE_PROVIDER
    raw = "".join(f"{GATE_PROVIDER}/{m}\n" for m in _declared())
    problems, evidence = _verify(raw, monkeypatch=monkeypatch)
    assert problems == []
    assert evidence["models_fetch_disabled"] == "1"
    assert evidence["declared_gate_local_models"] == _declared()


def test_verify_models_reports_selectable_non_gate_providers(monkeypatch):
    # The adversarial shape: a credential in the parent env makes anthropic/openai/
    # amazon-bedrock selectable next to the gate. This is the check the trace store could
    # never make — a dispatch to any of them never appears in the gate's trace.
    problems, evidence = _verify(ADVERSARIAL_MODELS, monkeypatch=monkeypatch)
    text = "\n".join(problems)
    for provider in ("anthropic", "openai", "amazon-bedrock"):
        assert provider in text, f"{provider} selectable but not reported"
    assert set(evidence["providers"]) >= {"anthropic", "openai", "amazon-bedrock", "gate-local"}


def test_verify_models_fails_when_the_gate_provider_resolves_nothing(monkeypatch):
    # Only the keyless builtins resolve — e.g. the mount's provider block broke, or the
    # suppression list swallowed gate-local. The rig must not read "no gate models" as a pass.
    problems, _ = _verify(KEYLESS_ONLY_MODELS, monkeypatch=monkeypatch)
    assert any("no gate-local" in p for p in problems), problems


def test_verify_models_flags_gate_local_model_drift(monkeypatch):
    from scripts.verify_opencode_mount import GATE_PROVIDER
    declared = _declared()
    raw = "".join(f"{GATE_PROVIDER}/{m}\n" for m in declared if m != declared[0])
    problems, _ = _verify(raw, monkeypatch=monkeypatch)
    assert any("drifted" in p for p in problems), problems


def test_verify_models_reports_a_non_zero_exit(monkeypatch):
    problems, evidence = _verify("", rc=1, monkeypatch=monkeypatch)
    assert any("exited 1" in p for p in problems), problems


def test_verify_child_env_reuses_the_scrub_predicate(monkeypatch):
    # One definition of "bearer" for scrub and check: AWS_REGION is NOT a credential but it
    # makes amazon-bedrock's 178 models selectable on its own (verified live 2026-10-01), so
    # the whole family goes — and the rig must flag whatever the scrub would have dropped.
    from scripts import verify_opencode_mount as rig
    problems = rig.verify_child_env({"AWS_REGION": "us-east-1",
                                     "ANTHROPIC_AUTH_TOKEN": "tok",
                                     "OPENCODE_DISABLE_MODELS_FETCH": "1",
                                     "OPENCODE_DISABLE_TELEMETRY": "1",
                                     "DO_NOT_TRACK": "1"})
    flagged = "\n".join(problems)
    assert "AWS_REGION" in flagged and "ANTHROPIC_AUTH_TOKEN" in flagged
    assert "OPENCODE_DISABLE_MODELS_FETCH" not in flagged


def test_verify_child_env_flags_lost_hardening():
    from scripts import verify_opencode_mount as rig
    problems = rig.verify_child_env({"PWD": "C:/ws"})
    assert any("OPENCODE_DISABLE_MODELS_FETCH" in p for p in problems), problems
    assert any("OPENCODE_DISABLE_TELEMETRY" in p for p in problems), problems


def test_verify_child_env_is_clean_on_the_real_scrub(monkeypatch):
    from scripts import verify_opencode_mount as rig
    from scripts.stand_up_opencode import child_env
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-attacker")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    assert rig.verify_child_env(child_env("C:/ws")) == []


def test_rig_never_fetches_the_published_schema():
    # The S7b ruling is explicit: validating the mount against https://opencode.ai/config.json
    # would be actively worse than no check, because the binary patches additionalProperties at
    # schema-generation time and the published schema is looser than the runtime structs. The
    # rig is behavioural, so it must not even import an HTTP client.
    src = RIG.read_text(encoding="utf-8")
    assert "urlopen" not in src and "http.client" not in src
    assert "import requests" not in src and "import httpx" not in src
    assert "urllib.request" not in src


def test_rig_without_live_reports_the_behavioural_check_as_not_run(monkeypatch, capsys):
    # A silently skipped strongest check is a footgun: the static run must say out loud that
    # the positive gate-local-only assertion did not happen.
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.18.25")
    def _explode(ws, env, timeout=300):
        raise AssertionError("the behavioural check must not run without --live")
    monkeypatch.setattr(rig, "list_models", _explode)
    assert rig.main([]) == 0
    assert "NOT RUN" in capsys.readouterr().err


def test_static_tier_reaches_the_child_env_check(monkeypatch):
    # The first cut returned before verify_child_env unless --live was passed, so the static
    # tier could not reach its own check while the header claimed it did (fix-round finding).
    # A dirty child env must be reported on the static path, with no binary involved.
    import harness.substrate.mount as driver
    from scripts import verify_opencode_mount as rig
    # verify_mount looks child_env up in the substrate module's globals, so the patch goes there.
    monkeypatch.setattr(driver, "child_env", lambda ws: {
        "PWD": str(ws), "AWS_REGION": "us-east-1", "ANTHROPIC_AUTH_TOKEN": "tok",
        "OPENCODE_DISABLE_MODELS_FETCH": "1", "OPENCODE_DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1"})
    problems, evidence = rig.verify_mount(ws=None, live=False)
    text = "\n".join(problems)
    assert "AWS_REGION" in text and "ANTHROPIC_AUTH_TOKEN" in text, problems
    # bearer_keys returns sorted
    assert evidence["child_env_bearer_keys"] == ["ANTHROPIC_AUTH_TOKEN", "AWS_REGION"]
    assert evidence["behavioural_check"].startswith("NOT RUN")


def test_static_tier_records_what_the_machine_carries(monkeypatch):
    # Evidence, not a problem: a box holding provider keys is the case the scrub exists for. The
    # static tier records what was scrubbed out of the parent so its output shows the scrub did
    # something rather than merely existing. This box carries several ANTHROPIC_* variables that
    # do not activate anything on the pinned binary — the assertion is a subset, because the
    # point is that NONE of them survive into the child.
    import harness.substrate.mount as driver
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.18.25")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-attacker")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    _, evidence = rig.verify_mount(ws=None, live=False)
    scrubbed = evidence["parent_bearer_keys_scrubbed"]
    assert {"ANTHROPIC_API_KEY", "AWS_REGION"} <= set(scrubbed), scrubbed
    assert evidence["child_env_bearer_keys"] == []


def test_a_sync_failure_cannot_leak_the_throwaway_workspace(monkeypatch):
    # The live-path sync_mount call used to sit ABOVE the try/finally that rmtree's the
    # throwaway workspace, so a raised sync leaked a verify-opencode-mount-* tempdir per
    # failure. Owned workspaces must be cleaned up on the sync path too, not only on the
    # models path.
    import harness.substrate.mount as driver
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.18.25")

    def boom(ws, mount, **kw):
        raise RuntimeError("sync failed")

    monkeypatch.setattr(driver, "sync_mount", boom)
    calls = []
    monkeypatch.setattr(rig.shutil, "rmtree",
                        lambda p, ignore_errors=False: calls.append(Path(p)))
    with pytest.raises(RuntimeError):
        rig.verify_mount(live=True)
    assert len(calls) == 1 and "verify-opencode-mount-" in calls[0].name


def test_mount_aggregation_reports_a_leak_end_to_end(monkeypatch, tmp_path):
    # verify_mount(live=True) is the unit-tested path to the verdict: workspace synced, child
    # env scrubbed, model list asserted. The binary is stubbed; the plumbing is real.
    import json
    import harness.substrate.mount as driver
    from scripts import verify_opencode_mount as rig
    monkeypatch.setattr(rig, "installed_version", lambda: "1.18.25")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    def fake_sync(ws, mount, **kw):
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "opencode.json").write_text(json.dumps(
            {"provider": {"gate-local": {"models": {m: {} for m in _declared()}}}}))
    monkeypatch.setattr(driver, "sync_mount", fake_sync)
    monkeypatch.setattr(rig, "list_models", lambda ws, env, timeout=300: (0, ADVERSARIAL_MODELS))
    problems, evidence = rig.verify_mount(ws=tmp_path, live=True)
    assert evidence["live"] is True
    assert any("amazon-bedrock" in p for p in problems), problems
    assert evidence["behavioural"]["catalog_cache_after"]["path"].endswith("models.json")
    # the child env the rig handed the binary was the scrubbed one, not the parent's
    assert evidence["child_env_bearer_keys"] == [], evidence["child_env_bearer_keys"]
