# tests/test_env_scrub.py
"""S1 (S7b final review): run_opencode builds the child env from the FULL parent env, so on
a machine holding ANTHROPIC_API_KEY / OPENAI_API_KEY / similar, opencode's builtin providers
activate and become selectable. Verified live 2026-10-01 against the pinned binary in a
synced mount workspace: with fake keys present, `opencode models` resolves 275 models
(anthropic 19, openai 61, amazon-bedrock 178) where a scrubbed env resolves only
gate-local (9). The scrub is the env half of the fix; `disabled_providers` in the mount is
the config half (it closes the keyless `opencode/*` catalog models no env scrub can reach),
and the rig's behavioural check asserts the composition (test_verify_opencode_mount.py)."""
import os
from pathlib import Path

import pytest

BEARERS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_GENERATIVE_AI_KEY",
           "AZURE_OPENAI_API_KEY", "AWS_BEDROCK_API_KEY", "DEEPSEEK_API_KEY"]

# The names that ACTUALLY activate a builtin provider (observed live 2026-10-01: the AWS
# pair is what lights up amazon-bedrock — there is no AWS_BEDROCK_API_KEY). The scrub must
# cover the real names, not just the ones that read like bearer keys.
ACTIVATING = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_GENERATIVE_AI_KEY",
              "AZURE_OPENAI_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
              "AWS_SESSION_TOKEN", "DEEPSEEK_API_KEY"]


@pytest.fixture
def fake_keys(monkeypatch):
    for k in BEARERS:
        monkeypatch.setenv(k, f"fake-{k}")
    return BEARERS


@pytest.fixture
def fake_activating_keys(monkeypatch):
    for k in ACTIVATING:
        monkeypatch.setenv(k, f"fake-{k}")
    return ACTIVATING


def test_the_child_env_scrubs_bearer_keys(fake_keys):
    from scripts.stand_up_opencode import child_env
    env = child_env(ws="/tmp/ws")
    for k in BEARERS:
        assert k not in env, f"{k} would activate opencode's builtin provider"
    assert env["PWD"] == "/tmp/ws"


def test_the_scrub_covers_the_names_that_activate_a_provider(fake_activating_keys):
    # amazon-bedrock activated on AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (178 models
    # resolved live) — a scrub keyed only on *_API_KEY-shaped names leaves it open.
    from scripts.stand_up_opencode import child_env
    env = child_env(ws="/tmp/ws")
    for k in ACTIVATING:
        assert k not in env, f"{k} activates a builtin provider"


def test_the_scrub_preserves_the_hardening_vars():
    from scripts.stand_up_opencode import child_env
    env = child_env(ws="/tmp/ws")
    assert env["OPENCODE_DISABLE_MODELS_FETCH"] == "1"
    assert env["OPENCODE_DISABLE_TELEMETRY"] == "1"


def test_the_scrub_does_not_touch_the_parent_env(fake_keys):
    from scripts.stand_up_opencode import child_env
    child_env(ws="/tmp/ws")
    for k in BEARERS:
        assert os.environ[k] == f"fake-{k}"   # scrub is copy-on-write, never destructive


def test_the_scrub_does_not_write_the_hardening_into_the_parent_env(monkeypatch):
    # The other half of copy-on-write. The pre-Task-12 hardening path wrote HARDEN_ENV into
    # os.environ and left it there for the rest of the process — exactly the destructive
    # behaviour this task retired, applied to the hardening keys instead of the bearers. A
    # regression to that shape passes the bearer pin above and still leaks into the parent.
    from scripts.stand_up_opencode import HARDEN_ENV, child_env
    for k in HARDEN_ENV:
        monkeypatch.delenv(k, raising=False)
    child_env(ws="/tmp/ws")
    for k in HARDEN_ENV:
        assert k not in os.environ, \
            f"{k} was written into the parent env — the scrub is no longer copy-on-write"


def test_accept_s7b_run_case_passes_the_scrubbed_env(monkeypatch, tmp_path):
    # The SECOND caller of run_opencode_session. Task 12 threaded the scrub through the driver
    # and missed this one: the A-1 acceptance path still inherited the full parent env, with a
    # comment asserting the old (no-longer-true) mechanism. This pins the reach, not the prose.
    import scripts.accept_s7b as acc
    seen = {}

    def fake_session(ws, model, prompt, timeout, env=None):
        seen["env"], seen["model"] = env, model
        return 0, "tail text"

    class _Store:
        def by_matter(self, matter):
            return ["row"]

    class _Gate:
        trace = _Store()

    monkeypatch.setattr(acc, "run_opencode_session", fake_session)
    monkeypatch.setattr(acc, "sync_mount", lambda *a, **k: None)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-attacker")
    res = acc.run_case("extraction", "prompt", _Gate(), None, tmp_path, 10)
    assert res["rows"] == ["row"] and res["rc"] == 0
    assert seen["model"] == "gate/extraction"
    env = seen["env"]
    assert env["PWD"] == str(tmp_path)
    for k in ("AWS_REGION", "ANTHROPIC_API_KEY"):
        assert k not in env, f"the acceptance child inherited {k}"


def test_accept_s7b_never_mutates_its_own_process_env():
    # The mutate-then-run pattern Task 12 retired must not come back in the acceptance path: it
    # would leave the hardening (and any bearer-key scrub) in the accept process permanently.
    src = (Path(__file__).resolve().parents[1] / "scripts" / "accept_s7b.py").read_text(
        encoding="utf-8")
    assert "os.environ[" not in src, "the retired os.environ mutation is back in accept_s7b"
    assert "os.environ[k] = v" not in src


def test_the_scrub_keeps_the_vars_opencode_needs_to_start(monkeypatch):
    # Deleting bearer keys must not take PATH/APPDATA/USERPROFILE with them: opencode is
    # resolved on PATH and reads the profile/data dirs. A scrub that kept only the
    # hardening vars would fail the run for a reason unrelated to the one it fixes.
    from scripts.stand_up_opencode import child_env
    # UPPERCASE names: os.environ uppercases keys on Windows, so "SystemRoot" would come
    # back as "SYSTEMROOT" and the assertion would fail on a name, not a value.
    for k, v in (("PATH", r"C:\some\bin"), ("APPDATA", r"C:\Users\u\AppData\Roaming"),
                 ("USERPROFILE", r"C:\Users\u"), ("SYSTEMROOT", r"C:\WINDOWS"),
                 ("TEMP", r"C:\Temp")):
        monkeypatch.setenv(k, v)
    env = child_env(ws="/tmp/ws")
    for k, v in (("PATH", r"C:\some\bin"), ("APPDATA", r"C:\Users\u\AppData\Roaming"),
                 ("USERPROFILE", r"C:\Users\u"), ("SYSTEMROOT", r"C:\WINDOWS"),
                 ("TEMP", r"C:\Temp")):
        assert env[k] == v, k


def _load_run_spike():
    # Same loader as test_run_spike_opencode.py: the driver importlib-loads two sibling
    # scripts at import time, so it is loaded by spec, not by package import.
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_spike_opencode.py"
    spec = importlib.util.spec_from_file_location("run_spike_opencode", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_run_opencode_honours_a_caller_supplied_env(monkeypatch):
    # The seam: a caller that hands an env gets exactly that env (the scrubbed one), not a
    # rebuild from os.environ. Default behaviour (env=None) is unchanged.
    mod = _load_run_spike()
    # M3: shutil/subprocess are used inside harness.substrate.run now, so the patches go there.
    import harness.substrate.run as run_mod
    seen = {}

    class _Proc:
        def __init__(self, *a, **kw):
            seen["env"] = kw.get("env")
            self.pid = 4242
            self.returncode = 0
            # the runner reads pipes on threads and proc.wait()s now: a fake
            # needs read()+close() pipes and a wait() that returns immediately
            self.stdout = type("P", (), {"read": lambda s: "", "close": lambda s: None})()
            self.stderr = type("P", (), {"read": lambda s: "", "close": lambda s: None})()
        def wait(self, timeout=None):
            return 0
        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(run_mod.shutil, "which", lambda name: "C:/npm/opencode.CMD")
    monkeypatch.setattr(run_mod.subprocess, "Popen", _Proc)
    ws = Path("C:/real/ws")
    rc, _ = mod.run_opencode(ws, ["run"], env={"PATH": "kept", "PWD": "C:/other"})
    assert rc == 0
    # PATH survives verbatim; only PWD is re-pinned (to the workspace, as str(Path(ws))).
    assert seen["env"]["PATH"] == "kept"
    assert set(seen["env"]) == {"PATH", "PWD"}, \
        "a caller-supplied env must be used verbatim, not merged with os.environ"
    assert seen["env"]["PWD"] == str(ws)


def test_run_opencode_repins_pwd_even_for_a_caller_supplied_env(monkeypatch):
    # PWD steers project/instance resolution (observed live 2026-09-01: an inherited PWD
    # pointing elsewhere attached the WRONG repo's instance). A caller env that forgets it —
    # or carries a stale one — must not resurrect that failure, so run_opencode always
    # re-pins PWD to the workspace the process actually runs in.
    mod = _load_run_spike()
    import harness.substrate.run as run_mod
    seen = {}

    class _Proc:
        def __init__(self, *a, **kw):
            seen["env"] = kw.get("env")
            seen["cwd"] = kw.get("cwd")
            self.pid = 4242
            self.returncode = 0
            # the runner reads pipes on threads and proc.wait()s now: a fake
            # needs read()+close() pipes and a wait() that returns immediately
            self.stdout = type("P", (), {"read": lambda s: "", "close": lambda s: None})()
            self.stderr = type("P", (), {"read": lambda s: "", "close": lambda s: None})()
        def wait(self, timeout=None):
            return 0
        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(run_mod.shutil, "which", lambda name: "C:/npm/opencode.CMD")
    monkeypatch.setattr(run_mod.subprocess, "Popen", _Proc)
    mod.run_opencode(Path("C:/real/ws"), ["run"], env={"PATH": "kept", "PWD": "C:/stale"})
    assert seen["env"]["PWD"] == str(Path("C:/real/ws"))
    assert seen["cwd"] == str(Path("C:/real/ws"))


def test_run_opencode_default_still_builds_from_parent_env(monkeypatch):
    # Existing callers (the spike driver's own modes) build no env of their own: keep the
    # historical {**os.environ, "PWD": ws} shape so this change cannot alter their behaviour.
    mod = _load_run_spike()
    import harness.substrate.run as run_mod
    monkeypatch.setenv("SCRUB_PROBE_VAR", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    seen = {}

    class _Proc:
        def __init__(self, *a, **kw):
            seen["env"] = kw.get("env")
            self.pid = 4242
            self.returncode = 0
            # the runner reads pipes on threads and proc.wait()s now: a fake
            # needs read()+close() pipes and a wait() that returns immediately
            self.stdout = type("P", (), {"read": lambda s: "", "close": lambda s: None})()
            self.stderr = type("P", (), {"read": lambda s: "", "close": lambda s: None})()
        def wait(self, timeout=None):
            return 0
        def communicate(self, timeout=None):
            return "", ""

    monkeypatch.setattr(run_mod.shutil, "which", lambda name: "C:/npm/opencode.CMD")
    monkeypatch.setattr(run_mod.subprocess, "Popen", _Proc)
    ws = Path("C:/real/ws")
    mod.run_opencode(ws, ["run"])
    assert seen["env"]["SCRUB_PROBE_VAR"] == "1"
    assert seen["env"]["PWD"] == str(ws)


def test_run_opencode_session_threads_the_env(monkeypatch):
    # run_opencode_session resolves run_opencode by a local import, so the patch goes on the
    # module it is imported from — and the assertion is that the env arrives at all: an env
    # argument that stops at the session wrapper would leave the child running on the full
    # parent env, which is the exact defect this task closes.
    # M3: run_opencode_session imports run_opencode from harness.substrate.run, so the
    # patch goes on that module (a patch on the spike script's re-export would not reach it).
    import harness.substrate.run as run_mod
    import harness.substrate.mount as driver
    calls = {}

    def fake_run(ws, argv, timeout, env=None):
        calls["argv"], calls["env"] = argv, env
        return 0, '{"type":"text","part":{"type":"text","messageID":"m","text":"ok"}}'

    monkeypatch.setattr(run_mod, "run_opencode", fake_run)
    code, text = driver.run_opencode_session(Path("C:/ws"), "gate/extraction", "p", 10,
                                            env={"OPENCODE_DISABLE_MODELS_FETCH": "1"})
    assert code == 0 and text == "ok"
    assert calls["env"] == {"OPENCODE_DISABLE_MODELS_FETCH": "1"}, \
        "the scrubbed env must reach run_opencode, not stop at the session wrapper"
