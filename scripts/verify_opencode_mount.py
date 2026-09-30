"""Upgrade regression rig for the OpenCode mount (precheck §5 requirement 1).

Run before ANY opencode version bump. A non-empty problem list means the bump does not ship;
the fallback is always 'pin-hold' — stay on the pinned version and re-verify the guard hooks
against the new one before trying again.

The three guard seams below are what S7c's grounding guard hangs on. experimental.* hooks
are experimental: if 1.18.26 renames or withdraws experimental.text.complete, that is a
problem this rig must report, not a silent degradation.

Two levels:

  python scripts/verify_opencode_mount.py            static: version pin + child env
  python scripts/verify_opencode_mount.py --live     adds the behavioural provider check

The static tier checks the version pin and the child env the driver builds (bearer scrub +
precheck §5 hardening), and records what provider credentials this machine actually carries and
that the scrub removed them. GUARD_SEAMS is carried as a MANIFEST of names only: no tier probes
those seams against the binary (that is live-only work, deferred to close-out), so this header
does not claim them.

The behavioural check is what the S7b review asked for and what the trace store can never
give: it syncs the real mount into a throwaway workspace and asks the pinned BINARY what it
resolves, then asserts the resolved provider/model set is ONLY gate-local/*. `opencode models`
is the union of every activation path — bearer credentials in the env, credentials in
opencode's own auth store, and the keyless builtin catalog — so a provider that becomes
selectable by ANY means shows up there, and the assertion needs no enumeration of providers
or variables. (`opencode debug config` would NOT do: it echoes the config file and does not
surface env- or auth-activated builtins — verified live 2026-10-01, where it reported a
single provider while `opencode models` resolved 275 models.)

NEVER fetch https://opencode.ai/config.json and validate the mount against it. The binary
patches additionalProperties on AgentConfig and ProviderConfig.options at schema-generation
time, so the published schema is looser than the runtime structs and would pass configs the
runtime rejects — a check that is actively worse than none. This rig validates behaviourally,
against the binary, and imports no HTTP client at all (test_rig_never_fetches_the_published_schema
pins that).
"""
from __future__ import annotations

import json, os, shutil, subprocess, sys
from pathlib import Path

EXPECTED_VERSION = "1.18.25"
FALLBACK = "pin-hold"          # named fallback per Jonathan's 2026-09-16 requirement
GUARD_SEAMS = ("tool.execute.before", "tool.execute.after", "experimental.text.complete")
GATE_PROVIDER = "gate-local"
ROOT = Path(__file__).resolve().parents[1]
MOUNT = ROOT / "data" / "opencode-a1"
# The models-fetch cache (precheck F1: its presence proves the catalog fetch ran). Recorded
# as evidence, never asserted on: a FRESH cache is not rewritten even with the fetch enabled,
# so an unchanged mtime does not prove absence of a fetch (verified live 2026-10-01).
CATALOG_CACHE = Path.home() / ".cache" / "opencode" / "models.json"


def installed_version() -> str:
    # On Windows, subprocess.run with a bare name does not apply PATHEXT, so the npm shim
    # (opencode.CMD) is never found and the rig reports a false "not found" — fail-closed
    # against a phantom problem, and the pin is never actually checked. shutil.which resolves
    # the shim. Deliberately no shell=True: the resolved absolute path runs directly, so no
    # shell ever interprets it.
    exe = shutil.which("opencode") or "opencode"
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=30)
        return out.stdout.strip() or out.stderr.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def verify_version() -> list[str]:
    v = installed_version()
    if not v:
        return ["opencode not found on PATH — mount cannot be verified"]
    if EXPECTED_VERSION not in v:
        return [f"version drift: expected {EXPECTED_VERSION}, found {v} "
                f"(fallback: {FALLBACK} — do not ship the bump)"]
    return []


def opencode_cmd() -> list[str]:
    """Same shim resolution as installed_version: PATHEXT is not applied to a bare name."""
    exe = shutil.which("opencode") or "opencode"
    if exe.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", exe]
    return [exe]


def parse_models(raw: str) -> tuple[set[str], list[str]]:
    """Split `opencode models` output into (model ids, unparsed non-empty lines).

    Observed 1.18.25 output is one "provider/model" per line with no header. Anything that
    does not look like that is returned to the caller rather than dropped, so a format change
    in a future version is visible as evidence instead of silently reading as an empty set."""
    models, unparsed = set(), []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        head = line.split("/", 1)
        if len(head) == 2 and head[0] and head[1]:
            models.add(line)
        else:
            unparsed.append(line)
    return models, unparsed


def list_models(ws: Path, env: dict[str, str], timeout: int = 300) -> tuple[int, str]:
    """Ask the real binary what it can select, in ws, under env. No network beyond the
    binary's own catalog behaviour; the gate is NOT needed — the model list is resolved
    from config, not from a successful dispatch."""
    proc = subprocess.run(opencode_cmd() + ["models"], cwd=str(ws), env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    return proc.returncode, proc.stdout or ""


def catalog_cache_state() -> dict:
    try:
        st = CATALOG_CACHE.stat()
    except OSError:
        return {"path": str(CATALOG_CACHE), "exists": False}
    return {"path": str(CATALOG_CACHE), "exists": True,
            "mtime": st.st_mtime, "size": st.st_size}


def verify_child_env(env: dict[str, str]) -> list[str]:
    """The env half of finding S1: no provider credential may survive into the child, and the
    precheck §5 hardening must still be set. Uses the scrub's own predicate (bearer_keys), so
    this check and the scrub cannot drift apart."""
    from scripts.stand_up_opencode import HARDEN_ENV, bearer_keys
    problems = [f"{k} is still set in the child env — it can activate a builtin provider "
                f"opencode can select without ever touching the gate"
                for k in bearer_keys(env)]
    problems += [f"{k} not set in the child env — the precheck §5 hardening was lost"
                 for k, v in HARDEN_ENV.items() if env.get(k) != v]
    return problems


def verify_models(ws: Path, env: dict[str, str]) -> tuple[list[str], dict]:
    """Behavioural check: the resolved provider/model set must be ONLY gate-local/*.

    Returns (problems, evidence). The provider set here is the union of every activation
    path, so this single assertion covers env credentials, the auth store, and the keyless
    builtin catalog at once."""
    declared = sorted(json.loads((MOUNT / "opencode.json").read_text(encoding="utf-8"))
                      ["provider"][GATE_PROVIDER]["models"])
    evidence = {"declared_gate_local_models": declared,
                "models_fetch_disabled": env.get("OPENCODE_DISABLE_MODELS_FETCH"),
                "catalog_cache_before": catalog_cache_state()}
    problems: list[str] = []
    try:
        rc, raw = list_models(ws, env)
    except (OSError, subprocess.SubprocessError) as ex:
        return [f"opencode models failed to run: {type(ex).__name__}: {ex}"], evidence
    models, unparsed = parse_models(raw)
    providers: dict[str, list[str]] = {}
    for model in models:
        providers.setdefault(model.split("/", 1)[0], []).append(model)
    gate = providers.get(GATE_PROVIDER, [])
    evidence.update({"exit_code": rc, "resolved_models": sorted(models),
                     "providers": {p: sorted(m) for p, m in sorted(providers.items())},
                     "unparsed_output_lines": unparsed,
                     "catalog_cache_after": catalog_cache_state()})
    if rc != 0:
        problems.append(f"opencode models exited {rc} — the mount may not even load")
    if unparsed:
        problems.append(f"could not parse {len(unparsed)} line(s) of `opencode models` "
                        f"output — the parser must be re-pointed before this check means "
                        f"anything: {unparsed[:3]}")
    if not gate:
        problems.append(f"no {GATE_PROVIDER}/* model resolved — the gate provider is "
                        f"suppressed or the mount's provider block is broken; nothing can "
                        f"dispatch through the gate")
    strangers = {p: m for p, m in providers.items() if p != GATE_PROVIDER}
    if strangers:
        problems.append(
            "non-gate providers are selectable: " + "; ".join(
                f"{p} ({len(m)} model(s), e.g. {m[0]})" for p, m in sorted(strangers.items()))
            + " — a dispatch to any of them never touches the gate (finding S1)")
    if gate and sorted(m.split("/", 1)[1] for m in gate) != declared:
        problems.append(f"{GATE_PROVIDER} models drifted: mount declares {declared}, "
                        f"binary resolves {sorted(gate)}")
    return problems, evidence


def verify_mount(ws: Path | None = None, live: bool = False) -> tuple[list[str], dict]:
    """All checks. The version pin and the child env run on BOTH tiers; the behavioural check
    needs the pinned binary and a synced workspace, so it is behind live=True and its absence is
    REPORTED, never silent. GUARD_SEAMS is probed on no path (see the module docstring)."""
    # verify_child_env imports the scrub from the driver module, so the import has to resolve on
    # the STATIC tier too: as a CLI, sys.path[0] is scripts/ itself, not the repo root. Hoisting
    # this above the static return is what makes the child-env check reachable without --live.
    for p in (str(ROOT / "src"), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from scripts.stand_up_opencode import bearer_keys, child_env
    problems = list(verify_version())

    workspace = ws
    owned = False
    if live:
        from scripts.stand_up_opencode import PORT, sync_mount
        if workspace is None:
            import tempfile
            workspace = Path(tempfile.mkdtemp(prefix="verify-opencode-mount-"))
            owned = True
        sync_mount(workspace, MOUNT, matter_ref="verify-mount",
                   classification="LOCAL_PREFERRED", port=PORT)
        env = child_env(workspace)
    else:
        # Nothing is synced on the static tier, and nothing needs to be: the workspace argument
        # only sets PWD, which verify_child_env does not inspect.
        env = child_env(ws if ws is not None else Path.cwd())

    evidence: dict = {"version": installed_version(), "live": live,
                      "child_env_bearer_keys": bearer_keys(env)}
    problems += verify_child_env(env)
    # What the machine carries and what the scrub removed from the child — evidence, not a
    # problem: a box holding provider keys is exactly the case the scrub exists for. Recorded so
    # the static tier shows the scrub did something, not merely that it exists.
    evidence["parent_bearer_keys_scrubbed"] = bearer_keys(dict(os.environ))

    if not live:
        evidence["behavioural_check"] = "NOT RUN (pass --live)"
        print(f"[rig] behavioural check NOT RUN — the positive gate-local-only assertion "
              f"needs --live (and the pinned binary); the child env WAS checked "
              f"({len(evidence['parent_bearer_keys_scrubbed'])} provider variable(s) scrubbed "
              f"from the parent)", file=sys.stderr)
        return problems, evidence

    evidence["workspace"] = str(workspace)
    try:
        model_problems, model_evidence = verify_models(workspace, env)
    finally:
        if owned:
            shutil.rmtree(workspace, ignore_errors=True)
    problems += model_problems
    evidence["behavioural"] = model_evidence
    return problems, evidence


def main(argv: list[str] | None = None) -> int:
    live = "--live" in (argv or [])
    problems, evidence = verify_mount(live=live)
    for p in problems:
        print(f"[rig] {p}", file=sys.stderr)
    if evidence.get("behavioural"):
        beh = evidence["behavioural"]
        print(f"[rig] resolved {len(beh.get('resolved_models', []))} model(s) from "
              f"{sorted({m.split('/')[0] for m in beh.get('resolved_models', [])})}", file=sys.stderr)
        cache = beh.get("catalog_cache_after", {})
        before = beh.get("catalog_cache_before", {})
        rewritten = (before.get("mtime"), before.get("size")) != (cache.get("mtime"), cache.get("size"))
        print(f"[rig] models-fetch: OPENCODE_DISABLE_MODELS_FETCH="
              f"{beh.get('models_fetch_disabled')}; catalog cache {cache.get('path')} "
              f"exists={cache.get('exists')} rewritten_by_this_check={rewritten} "
              f"(recorded only — a fresh cache is not rewritten even when the fetch is on)",
              file=sys.stderr)
    if problems:
        print(f"[rig] {len(problems)} problem(s). Fallback is '{FALLBACK}': stay on "
              f"{EXPECTED_VERSION}.", file=sys.stderr)
        return 1
    print(f"[rig] mount verified: opencode {EXPECTED_VERSION}, child env scrubbed"
          + (", providers resolve to gate-local only" if live else "")
          + f"; guard seams carried but NOT probed: {list(GUARD_SEAMS)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
