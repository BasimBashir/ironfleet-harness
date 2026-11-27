"""Model settings -> Test: a cloud row must prove its KEY, not just its model list.
NVIDIA NIM's /models answers without a key, so the Mac 1.0.1 tester saw "full ·
verified" on a keyless row and then 162 failed calls."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import harness.providers.http_fetch as hf
import harness.providers.probe as probe
from harness.service import settings

SPEC = {"base_url": "https://nim.example/v1", "model": "m", "engine": "cloud",
        "kind": "chat", "declared": {}}


def _admitted(monkeypatch):
    async def fake_register(*a, **k):
        return SimpleNamespace(reachable=True, auth_ok=True, admission="full",
                               provenance=SimpleNamespace(verified=True), models=["m"])
    monkeypatch.setattr(probe, "register_provider", fake_register)


def test_cloud_test_refuses_a_rejected_key_and_says_why(monkeypatch):
    _admitted(monkeypatch)
    monkeypatch.setattr("harness.keychain._kv", {"nim": "bad"})

    async def rejecting(url, headers, payload=None, errors=None, **kw):
        errors.append("HTTP 401: unauthorized")
        return None
    monkeypatch.setattr(hf, "openai_fetch", rejecting)
    r = asyncio.run(settings._probe_one("nim", SPEC))
    assert r["admission"] == "refused" and r["error"] == "HTTP 401: unauthorized"


def test_cloud_test_with_no_key_says_so(monkeypatch):
    _admitted(monkeypatch)
    monkeypatch.setattr("harness.keychain._kv", {})
    r = asyncio.run(settings._probe_one("nim", SPEC))
    assert r["admission"] == "refused" and r["error"] == "no API key set"


def test_cloud_test_with_a_working_key_stays_admitted(monkeypatch):
    _admitted(monkeypatch)
    monkeypatch.setattr("harness.keychain._kv", {"nim": "good"})

    async def ok(url, headers, payload=None, errors=None, **kw):
        assert headers["Authorization"] == "Bearer good" and payload["max_tokens"] == 1
        return {"choices": [{"message": {"content": "p"}}]}
    monkeypatch.setattr(hf, "openai_fetch", ok)
    r = asyncio.run(settings._probe_one("nim", SPEC))
    assert r["admission"] == "full" and "error" not in r
