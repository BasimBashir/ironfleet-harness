"""M8 contract gate: the web client talks ONLY to the API + SSE (no in-process
access, no other origin). Every API path the client calls — written as
get/post/put/patch/del/page/upload(`/...`) or the literal /api/v1/events —
must be an operation in the committed openapi-v1.json."""
from __future__ import annotations

import json
import re
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
SRC = CORE / "web" / "src"
CALL = re.compile(r"\b(?:get|post|put|patch|del|page|upload|blob|useApi)\(\s*[`\"'](/[^`\"'?]*)")
EVENTS = re.compile(r"[`\"']/api/v1(/[^`\"'?]*)")


def _norm(path: str) -> str:
    return re.sub(r"\$\{[^}]*\}|\{[^}]*\}", "{}", path.rstrip("/"))


def _sources():
    return [p for p in SRC.rglob("*.js*") if ".test." not in p.name]


def _api_paths() -> set[str]:
    spec = json.loads((CORE / "docs" / "enterprise" / "openapi-v1.json").read_text(encoding="utf-8"))
    return {_norm(p[len("/api/v1"):]) for p in spec["paths"] if p.startswith("/api/v1")}


def test_every_client_path_is_an_api_operation():
    ops = _api_paths()
    used: dict[str, str] = {}
    for f in _sources():
        text = f.read_text(encoding="utf-8")
        for m in list(CALL.finditer(text)) + list(EVENTS.finditer(text)):
            used[_norm(m.group(1))] = f.name
    assert used, "no API calls found — the gate would pass vacuously"
    unknown = {p: f for p, f in used.items() if p not in ops}
    assert not unknown, f"client calls paths missing from openapi-v1.json: {unknown}"


def test_artifact_review_decisions_are_ones_the_api_accepts():
    # 2026-11-12: Drafts sent "approved" (a state) where the API takes "approve" -> 422
    sent = {m for f in _sources() for m in re.findall(
        r"/review`,\s*\{\s*decision:\s*\"(\w+)\"", f.read_text(encoding="utf-8"))}
    assert sent, "no artifact review call found — the gate would pass vacuously"
    assert sent <= {"approve", "reject", "request_changes"}, sent


def test_no_other_origin_and_fetch_only_in_the_two_client_modules():
    for f in _sources():
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"https?://", text), f"{f.name} names an origin"
        if f.name not in ("api.js", "sse.js"):
            assert "fetch(" not in text, f"{f.name} calls fetch directly"
