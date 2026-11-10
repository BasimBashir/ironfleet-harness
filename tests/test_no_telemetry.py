# tests/test_no_telemetry.py — M11 T4: the no-telemetry promise, enforced by drift.
"""02 §15: nothing leaves the machine. This test is a tripwire, not a security
boundary: it scans every .py under src/harness for telemetry tokens (allowing
only mount.py's OPENCODE_DISABLE_TELEMETRY=1 defense env) and for URL literals
(allowing only loopback and the XML namespaces the court-pack exporter writes
into documents — neither is an egress). Any new dependency or literal here must
come through this test's allowlists, visibly."""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "harness"

BANNED = re.compile(
    r"(?i)(posthog|sentry|mixpanel|amplitude|segment\.io|google\.analytics"
    r"|track_event|send_telemetry)")
URL = re.compile(r"https?://[^\s'\"')]+")
URL_ALLOW = ("127.0.0.1", "localhost", "schemas.openxmlformats.org")


def test_no_telemetry_tokens_outside_the_disable_env():
    offenders = []
    for p in sorted(SRC.rglob("*.py")):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if "OPENCODE_DISABLE_TELEMETRY" in line:
                continue  # the defense itself: the env that turns opencode's off
            if BANNED.search(line):
                offenders.append(f"{p.relative_to(SRC)}:{n}: {line.strip()[:80]}")
    assert not offenders, "telemetry tokens in src/harness:\n" + "\n".join(offenders)


def test_disable_telemetry_env_hardening_stays():
    # positive control: opencode's own telemetry must stay switched off in the
    # mount env — removing this line is the regression this suite exists to catch
    mount = (SRC / "substrate" / "mount.py").read_text(encoding="utf-8")
    assert '"OPENCODE_DISABLE_TELEMETRY": "1"' in mount


def test_url_literals_are_loopback_or_xml_namespaces_only():
    offenders = []
    for p in sorted(SRC.rglob("*.py")):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for m in URL.findall(line):
                host = re.sub(r"^https?://", "", m).split("/")[0].split(":")[0]
                if host.startswith("{"):  # f-string template; resolved at runtime
                    continue
                if host not in URL_ALLOW:
                    offenders.append(f"{p.relative_to(SRC)}:{n}: {m}")
    assert not offenders, "non-loopback URL literals in src/harness:\n" + \
        "\n".join(offenders)
