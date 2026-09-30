# tests/test_accept_s7c.py
"""Task 13: the pure pieces of the S7c acceptance driver.

No live opencode, no network, no gate probe: case loading (exactly 30, top level only), the
authority construction (reused from the spike, envelopes included), the two sides' request
shapes, the sidecar shape (and that rescore_sidecars can consume it), the guard-coverage
correspondence against synthetic transcript+log pairs INCLUDING the must-FAIL case, and the
parity-bar reporting (deltas + variance note, never a silent pass).
"""
import json
import importlib.util

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "accept_s7c.py"
TEMPLATE = ROOT / "src" / "harness" / "spike" / "candidates" / "opencode" / "ironfleet-guard-s7c.ts"


def _load():
    spec = importlib.util.spec_from_file_location("accept_s7c", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _case(cid: str, task_class: str = "analysis", cites: list[str] | None = None,
          grounds: list[str] | None = None) -> dict:
    return {"id": cid, "matter_type": "m", "task_class": task_class, "prompt": f"prompt {cid}",
            "expected_citations": cites if cites is not None else [f"Cite {cid} [1994] UKPC 3"],
            "required_grounding": grounds if grounds is not None else ["some pin"],
            "persona_checks": {"ok": "ok"}}


# ── case loading: the acceptance number is 30 ────────────────────────────────

def test_the_real_cases_dir_yields_exactly_thirty():
    """The directory also holds REVIEW.md, references/, sources/ and archive/ (3 retired seeds).
    Any silent 27 or 33 corrupts the acceptance number."""
    mod = _load()
    cases = mod.load_golden_cases()
    assert len(cases) == 30
    assert not ({c.id for c in cases} & mod.RETIRED_IDS)
    assert all(not c.id.startswith("seed-") for c in cases)


def test_a_short_cases_dir_fails_loud(tmp_path):
    mod = _load()
    for cid in (f"gc-x-{i:03d}" for i in range(29)):
        (tmp_path / f"{cid}.yaml").write_text(yaml.safe_dump(_case(cid)), encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        mod.load_golden_cases(tmp_path)
    assert "29" in str(ex.value) and "30" in str(ex.value)


def test_a_retired_seed_at_the_top_level_fails_loud(tmp_path):
    mod = _load()
    cases = [_case(f"gc-x-{i:03d}") for i in range(29)]
    retired = _case("seed-imca-001")
    retired["id"] = "seed-imca-001"
    cases.append(retired)
    for c in cases:
        (tmp_path / f"{c['id']}.yaml").write_text(yaml.safe_dump(c), encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        mod.load_golden_cases(tmp_path)          # 30 files, one of them retired
    assert "retired" in str(ex.value)


def test_an_unroutable_mount_alias_fails_loud(tmp_path, monkeypatch):
    """Every case is dispatched on the mount alias, so if its class ever vanishes from the
    routing table all 30 mount-side dispatches refuse — that must not look like parity."""
    mod = _load()
    monkeypatch.setattr(mod, "MOUNT_MODEL", "gate/nonexistent")
    for i in range(1, 31):
        (tmp_path / f"gc-x-{i:03d}.yaml").write_text(
            yaml.safe_dump(_case(f"gc-x-{i:03d}")), encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        mod.load_golden_cases(tmp_path)
    assert "nonexistent" in str(ex.value)


def test_the_detection_case_is_why_the_house_routing_must_be_defaults_based():
    """routing-a1 (the mount's table) has no `detection` row, and the real corpus carries one
    `detection` case. The mount side never dispatches it (every case rides the persona alias),
    but a rules-only house routing would refuse that case and silently drop the pair — which is
    why the house gate is built from the reference script's defaults-based routing."""
    mod = _load()
    classes = {c.task_class for c in mod.load_golden_cases()}
    assert "detection" in classes
    assert "detection" not in mod.routing_classes()
    assert mod.MOUNT_MODEL.split("/", 1)[1] in mod.routing_classes()


# ── the authority construction is the spike's, envelopes included ─────────────

def test_authorities_are_reused_verbatim_not_rederived():
    mod = _load()
    from scripts import run_spike_opencode as spike
    assert mod.allowed_for is spike.allowed_for        # the same function object, not a copy


def test_the_opencode_primitives_are_the_spikes_too():
    """The driver must not grow its own invocation or authority writer: a local re-derivation is
    how the annotate-inside-a-needle failure (and a wrong-env child) would come back."""
    mod = _load()
    from scripts import run_spike_opencode as spike
    assert mod.write_allowed is spike.write_allowed
    assert mod.run_opencode is spike.run_opencode
    assert mod.spike is spike


def test_authorities_carry_expected_citations_and_their_bracket_envelopes():
    mod = _load()
    from harness.spike.guard_port import _citations
    cases = {c.id: c for c in mod.load_golden_cases()}
    case = cases["gc-ppsa-001-goldcorp"]
    out = mod.allowed_for(case)
    assert out[:2] == case.expected_citations
    envelopes = [c for c in out if c not in case.expected_citations]
    assert envelopes == ["[1994]"], envelopes
    for cite in case.expected_citations:
        for env in _citations(cite):
            assert env in out                          # every bracket envelope is authorised


def test_authorities_cover_every_case_and_the_guard_cannot_split_a_needle():
    """The priced seam (Task 10): an unauthorised bracket inside an expected citation gets
    annotated after ']', which breaks the scorer's exact-substring needle and fabricates a
    citation failure the unguarded house side cannot show."""
    mod = _load()
    from harness.spike.guard_port import portable_grounding_guard
    for case in mod.load_golden_cases():
        allowed = mod.allowed_for(case)
        for cite in case.expected_citations:
            res = portable_grounding_guard(cite, allowed)
            assert res.annotated == cite, (case.id, cite, res.annotated)


# ── the two sides' request shapes ────────────────────────────────────────────

def test_mount_side_drives_the_zero_tool_twin_on_the_research_alias():
    mod = _load()
    case = mod.GoldenCase.model_validate(_case("gc-x-001", cites=["A v B [2001] 1 NZLR 1"]))
    argv = mod.mount_argv(case)
    assert argv[0] == "run"
    assert argv[argv.index("--agent") + 1] == "hunter-drive"
    assert argv[argv.index("--model") + 1] == "gate-local/gate/research"
    assert argv[argv.index("--format") + 1] == "json"
    assert argv[-1] == "prompt gc-x-001"               # flattened: cmd.exe cuts at newlines


def test_mount_drive_twin_is_actually_toolless_in_the_mount(tmp_path):
    """The parity claim rests on the twin having every builtin off — check the shipped mount."""
    from scripts.stand_up_opencode import sync_mount
    ws = tmp_path / "ws"
    sync_mount(ws, ROOT / "data" / "opencode-a1", "m-test", "LOCAL_PREFERRED", 8123)
    body = (ws / ".opencode" / "agent" / "hunter-drive.md").read_text(encoding="utf-8")
    assert "mode: primary" in body and "model: gate/research" in body
    tools = body.split("tools:", 1)[1].split("---", 1)[0]
    assert len([l for l in tools.splitlines() if l.strip().endswith(": false")]) >= 10
    assert ": true" not in tools


def test_house_request_is_the_persona_dispatch_under_one_model_and_cap():
    mod = _load()
    case = mod.GoldenCase.model_validate(_case("gc-x-001"))
    req = mod.house_request(case, model="thomson1-chat:latest", max_tokens=mod.MAX_TOKENS)
    assert [m["role"] for m in req.messages] == ["system", "user"]
    assert req.messages[0]["content"] == mod.persona.PERSONA_PORT["system_prompt"]
    assert req.messages[1]["content"] == case.prompt
    assert req.task_class == case.task_class
    assert req.model == "thomson1-chat:latest"         # ONE model on both sides, never assumed
    assert req.max_tokens >= 16384                     # B1 floor: thomson1 reasons before content


# ── sidecar shape: re-scorable offline ───────────────────────────────────────

def _pair_record(mod):
    from harness.eval.scorers import score_case
    case = mod.GoldenCase.model_validate(_case("gc-x-001"))
    mount = mod.base.case_record(case.id, model="opencode:gate-local/gate/research",
                                 content="an answer citing Cite gc-x-001 [1994] UKPC 3 and some pin",
                                 sc=score_case("an answer citing Cite gc-x-001 [1994] UKPC 3 "
                                               "and some pin", case))
    mount.update({"run_id": case.id, "exit_code": 0, "latency_ms": 1234,
                  "guard_decisions": 1, "transcript_chars": 99, "error": ""})
    house = mod.base.case_record(case.id, model="thomson1-chat:latest",
                                 content="an answer citing Cite gc-x-001 [1994] UKPC 3 and some pin",
                                 sc=score_case("an answer citing Cite gc-x-001 [1994] UKPC 3 "
                                               "and some pin", case))
    house.update({"driver_latency_ms": 900, "max_tokens": 16384, "error": ""})
    return case, mod.sidecar_record(case, mount, house)


def test_sidecar_record_keeps_both_sides_and_the_house_side_rescorable(tmp_path):
    mod = _load()
    case, rec = _pair_record(mod)
    assert rec["case_id"] == case.id and rec["id"] == case.id
    assert rec["mount"]["model"].startswith("opencode:")
    for side in (rec, rec["mount"]):
        assert {"id", "passed", "citation_accuracy", "grounding_score", "checks", "status",
                "content"} <= set(side)
    # rescore_sidecars consumes the TOP-LEVEL record directly: no model re-run needed
    spec = importlib.util.spec_from_file_location("rescore_sidecars",
                                                  ROOT / "scripts" / "rescore_sidecars.py")
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "c.yaml").write_text(yaml.safe_dump(_case("gc-x-001")), encoding="utf-8")
    out = rs.rescore([rec], {c.id: c for c in rs.load_cases(cases_dir)})
    assert out[0]["new_citation_accuracy"] == 1.0 and out[0]["new_grounding_score"] == 1.0


def test_sidecar_records_a_failed_side_as_failed_not_silent(tmp_path):
    mod = _load()
    case = mod.GoldenCase.model_validate(_case("gc-x-002"))
    mount = mod.base.case_record(case.id, error="no assistant text in events (exit=1)")
    house = mod.base.case_record(case.id, error="dispatch failed (GateRefusal): no eligible")
    rec = mod.sidecar_record(case, mount, house)
    assert rec["status"] == "failed" and rec["mount"]["status"] == "failed"
    assert rec["content"] is None and rec["citation_accuracy"] is None


# ── check 2: the guard-coverage correspondence ────────────────────────────────

def _flat_events(*texts: str) -> str:
    return "\n".join(json.dumps({"type": "text", "part": {"messageID": "m1", "type": "text",
                                                          "text": t}})
                     for t in texts) + "\n"


def _decisions(*texts: str) -> list[dict]:
    return [{"tag": "text.complete", "decision": "approve", "reason": "grounded",
             "chars": len(t), "sha256_16": mod_sha16(t), "sha256_out": mod_sha16(t),
             "annotated": False, "authorities": 3}
            for t in texts]


def mod_sha16(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def mod_ungrounded() -> str:
    return "[UNGROUNDED — not confirmed]"


def test_coverage_passes_when_every_completion_has_a_decision():
    mod = _load()
    texts = ["First part of the answer.", "Second part."]
    out = mod.coverage({"gc-x-001": texts}, {"gc-x-001": _decisions(*texts)})
    assert out["passed"] is True
    assert out["completions"] == 2 and out["decisions"] == 2 and out["covered"] == 2


def test_coverage_fails_when_a_completion_lacks_a_decision():
    mod = _load()
    texts = ["covered completion.", "UNCOVERED completion."]
    out = mod.coverage({"gc-x-001": texts}, {"gc-x-001": _decisions(texts[0])})
    assert out["passed"] is False                       # the must-FAIL case
    assert out["covered"] == 1 and out["completions"] == 2
    assert out["missing"] == [{"run": "gc-x-001", "sha256_16": mod_sha16(texts[1]), "count": 1}]


def test_coverage_fails_when_the_log_records_text_the_session_never_shows():
    mod = _load()
    out = mod.coverage({"gc-x-001": ["the answer."]},
                       {"gc-x-001": _decisions("the answer.", "a phantom completion.")})
    assert out["passed"] is False
    assert out["unmatched"][0]["sha256_16"] == mod_sha16("a phantom completion.")


def test_coverage_matches_the_annotated_text_that_left_the_guard():
    """LIVE FINDING (smoke run 2026-10-01): the transcript records the ANNOTATED text — the hook
    writes its output back into the part — so the correspondence must be matched on the guard's
    OUTPUT digest. Matching the examined digest reads every annotated completion as uncovered
    (measured: 10 annotations in one mount-side answer)."""
    mod = _load()
    examined = "Per [Imaginary Act 2026, s 9] it applies."
    annotated = f"Per [Imaginary Act 2026, s 9] {mod_ungrounded()} it applies."
    decisions = [{"tag": "text.complete", "decision": "block",
                  "reason": "ungrounded: ['[Imaginary Act 2026, s 9]']", "chars": len(examined),
                  "sha256_16": mod_sha16(examined), "sha256_out": mod_sha16(annotated),
                  "annotated": True, "authorities": 1}]
    assert mod.coverage({"gc-x-001": [annotated]}, {"gc-x-001": decisions})["passed"] is True
    # an older log carrying only the examined digest cannot see the correspondence: documented
    # failure mode, not a silent pass
    only_in = [{**decisions[0], "sha256_out": None}]
    out = mod.coverage({"gc-x-001": [annotated]}, {"gc-x-001": only_in})
    assert out["passed"] is False and out["missing"]


def test_coverage_ignores_empty_reasoning_parts_but_counts_real_ones():
    """The plugin returns early on an empty text part (thomson1 streams empty reasoning parts),
    so an empty part is not a completion and must not read as a missing decision."""
    mod = _load()
    out = mod.coverage({"gc-x-001": ["", "  ", "the answer."]},
                       {"gc-x-001": _decisions("the answer.")})
    assert out["passed"] is True and out["completions"] == 1


def test_text_parts_reads_both_observed_event_shapes():
    mod = _load()
    flat = _flat_events("one ", "two")
    snap = json.dumps({"type": "message.updated", "properties": {
        "info": {"role": "assistant"},
        "parts": [{"type": "text", "text": "snap one"}, {"type": "reasoning", "text": "hmm"},
                  {"type": "text", "text": "snap two"}]}})
    assert mod.text_parts(flat) == ["one ", "two"]
    assert mod.text_parts(snap) == ["snap one", "snap two"]
    assert mod.text_parts("") == []


def test_guard_coverage_joins_transcripts_to_their_own_slices(tmp_path):
    """The real assembly, without opencode: transcripts/ + guard-slices/ in a workspace."""
    mod = _load()
    ws = tmp_path / "ws"
    (ws / "transcripts").mkdir(parents=True)
    (ws / "guard-slices").mkdir()
    texts = ["completion one.", "completion two."]
    (ws / "transcripts" / "gc-x-001.jsonl").write_text(_flat_events(*texts), encoding="utf-8")
    (ws / "guard-slices" / "gc-x-001.jsonl").write_text(
        "".join(json.dumps(d) + "\n" for d in _decisions(*texts)), encoding="utf-8")
    # a transcript whose run never wrote a slice -> its completions are uncovered
    (ws / "transcripts" / "gc-x-002.jsonl").write_text(_flat_events("orphan."), encoding="utf-8")
    out = mod.guard_coverage(ws)
    assert out["completions"] == 3 and out["decisions"] == 2
    assert out["passed"] is False
    assert out["missing"] == [{"run": "gc-x-002", "sha256_16": mod_sha16("orphan."), "count": 1}]


def test_guard_coverage_scopes_to_this_session(tmp_path):
    """An earlier attempt's transcripts (or a resumed run's already-scored cases) are evidence,
    not a false FAIL: only the runs THIS session made are asserted."""
    mod = _load()
    ws = tmp_path / "ws"
    (ws / "transcripts").mkdir(parents=True)
    (ws / "guard-slices").mkdir()
    texts = ["a completion."]
    (ws / "transcripts" / "gc-x-001.jsonl").write_text(_flat_events(*texts), encoding="utf-8")
    (ws / "guard-slices" / "gc-x-001.jsonl").write_text(
        "".join(json.dumps(d) + "\n" for d in _decisions(*texts)), encoding="utf-8")
    (ws / "transcripts" / "stale-earlier-attempt.jsonl").write_text(
        _flat_events("stale."), encoding="utf-8")
    out = mod.guard_coverage(ws, runs={"gc-x-001"})
    assert out["passed"] is True
    assert out["ignored_transcripts"] == ["stale-earlier-attempt"]


def test_the_plugin_logs_the_fields_coverage_reads():
    """If the plugin's decision line ever drops sha256_16 (or the tag), coverage reads nothing
    and check 2 fails — this pin turns that drift into a test failure instead."""
    mod = _load()
    body = TEMPLATE.read_text(encoding="utf-8")
    log_fn = body.split("function logDecision", 1)[1].split("}", 1)[0]
    for field in ("tag", "decision", "reason", "chars", "sha256_16", "sha256_out", "annotated",
                  "authorities"):
        assert field in log_fn, field
    assert 'createHash("sha256")' in body
    assert mod.GUARD_TAG == "text.complete"
    assert 'guard(output.text, "text.complete")' in body   # the hook tags its own decisions


# ── check 1 reporting: deltas + variance, never a silent pass ────────────────

def _rows(mod, scores: dict[str, tuple[float, float]]):
    """Per-case pair rows with the MOUNT side's scores forced to the given values, so delta
    arithmetic can be asserted exactly. (None, None) models a mount side that produced no text."""
    from harness.eval.scorers import score_case
    rows = []
    for cid, (mc, mg) in scores.items():
        text = "answer citing needle and pin"
        case = mod.GoldenCase.model_validate(_case(cid, cites=["needle"], grounds=["pin"]))
        sc = score_case(text, case)
        if mc is None:
            m = mod.base.case_record(cid, error="no assistant text in events (exit=1)")
            m.update({"run_id": cid, "exit_code": 1, "latency_ms": 1, "guard_decisions": 0,
                      "transcript_chars": 1, "error": "no assistant text in events (exit=1)"})
        else:
            sc.citation_accuracy, sc.grounding_score = mc, mg
            sc.passed = mc >= 0.999 and mg >= 0.999 and all(sc.checks.values())
            m = mod.base.case_record(cid, content=text, sc=sc)
            m.update({"run_id": cid, "exit_code": 0, "latency_ms": 1, "guard_decisions": 1,
                      "transcript_chars": 1, "error": ""})
        h = mod.base.case_record(cid, content=text, sc=score_case(text, case))
        h.update({"driver_latency_ms": 1, "max_tokens": 16384, "error": ""})
        rows.append(mod.sidecar_record(case, m, h))
    return rows


def test_parity_bar_reports_deltas_and_variance_and_never_passes_silently():
    mod = _load()
    rows = _rows(mod, {"gc-x-001": (1.0, 1.0), "gc-x-002": (0.5, 1.0)})
    variance = {"case": "gc-x-001", "repeat": {"citation_accuracy": 1.0, "grounding_score": 1.0,
                                               "latency_ms": 5, "error": ""},
                "note": "variance: a single repeat pair, temperature unpinned on both sides."}
    bar = mod.parity_bar(rows, variance)
    assert bar["pairs_scored"] == 2 and bar["verdict"] != "PASS"      # 2 of 30 is not parity
    assert bar["mount"]["citations"] == pytest.approx(0.75)
    assert bar["house"]["citations"] == pytest.approx(1.0)
    assert bar["delta_mean"]["citations"] == pytest.approx(-0.25)
    assert bar["delta_mean"]["citations_abs"] == pytest.approx(0.25)
    assert any("gc-x-003" not in r for r in bar["reasons"])
    for reason in bar["reasons"][:4]:                  # the numeric reasons name a measurement
        assert any(ch.isdigit() for ch in reason), reason
    assert bar["variance"]["note"] in bar["reasons"]   # the variance note is never dropped


def test_parity_bar_names_an_unscorable_pair_instead_of_passing():
    mod = _load()
    rows = _rows(mod, {"gc-x-001": (1.0, 1.0), "gc-x-002": (None, None)})
    bar = mod.parity_bar(rows, {"case": "-", "repeat": {}, "note": "n/a"})
    assert bar["verdict"] == "FAIL"
    assert "gc-x-002" in bar["pairs_broken"]
    assert any("gc-x-002" in r for r in bar["reasons"])
    assert bar["pairs_scored"] == 1


def test_parity_bar_flags_a_material_mount_regression_as_advisory():
    mod = _load()
    rows = _rows(mod, {f"gc-x-{i:03d}": (0.0, 1.0) for i in range(1, 31)})
    bar = mod.parity_bar(rows, {"case": "-", "repeat": {}, "note": "n/a"})
    assert bar["verdict"] == "PASS"                    # 30/30 pairs scored: the bar is met
    assert bar["regression_flag"], "a 0.0 mount mean against a 1.0 house mean must be flagged"
    assert all("advisory" in f for f in bar["regression_flag"])


def test_parity_bar_passes_only_on_thirty_scored_pairs():
    mod = _load()
    rows = _rows(mod, {f"gc-x-{i:03d}": (1.0, 1.0) for i in range(1, 31)})
    bar = mod.parity_bar(rows, {"case": "gc-x-001", "repeat": {"citation_accuracy": 1.0,
                                                               "grounding_score": 1.0,
                                                               "latency_ms": 1, "error": ""},
                                "note": "single repeat pair"})
    assert bar["verdict"] == "PASS" and bar["pairs_scored"] == 30


# ── check 4's static half: the tool surface opens no socket of its own ───────

def test_network_sweep_flags_a_new_network_import_and_allows_the_gate_client(tmp_path):
    mod = _load()
    (tmp_path / "refine.py").write_text("import urllib.request\n", encoding="utf-8")
    (tmp_path / "rogue.py").write_text("import socket\n", encoding="utf-8")
    (tmp_path / "clean.py").write_text("import json\n", encoding="utf-8")
    out = mod.network_sweep(tmp_path)
    assert [h["file"] for h in out["network_imports"]] == ["refine.py", "rogue.py"]
    assert out["problems"] and "rogue.py:1" in out["problems"][0]
    assert "refine.py:1" not in " ".join(out["problems"])


def test_the_shipped_tool_surface_sweeps_clean():
    mod = _load()
    out = mod.network_sweep(ROOT / "src" / "harness" / "module_e")
    assert out["network_imports"], "the sweep must actually see the gate client"
    assert out["problems"] == []


# ── check 3's diagnostic: where did the tool call go? ─────────────────────────

def test_request_capture_patches_and_restores_the_handler():
    import harness.egress_proxy as ep
    mod = _load()
    before = ep._Handler.do_POST
    with mod.RequestCapture() as cap:
        assert ep._Handler.do_POST is not before
        assert cap.body is None and cap.replay("m") == {"captured": False}
    assert ep._Handler.do_POST is before


def test_replay_reports_what_the_provider_does_with_the_identical_payload(monkeypatch):
    mod = _load()
    cap = mod.RequestCapture()
    cap.body = {"model": "gate/research", "tools": [{"type": "function"}] * 14}

    class _FakeResp:
        def __init__(self, doc): self._b = json.dumps(doc).encode()
        def read(self): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    doc = {"choices": [{"finish_reason": "tool_calls",
                        "message": {"tool_calls": [{"function": {"name": "bash"}},
                                                    {"function": {"name": "ironfleet_without_prejudice"}}]}}]}
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(doc)
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    out = cap.replay(model="thomson1-chat:latest")
    assert out["captured"] and out["replayed"]
    assert out["finish_reason"] == "tool_calls"
    assert out["tool_calls"] == ["bash", "ironfleet_without_prejudice"]
    assert out["tools_offered"] == 14
    assert seen["body"]["model"] == "thomson1-chat:latest"     # rewritten off the gate alias
    assert "stream" not in seen["body"] and "stream_options" not in seen["body"]


# ── the run date is the RUN date, not the plan's ─────────────────────────────

def test_no_plan_date_is_baked_into_the_driver():
    """The report directory carries the RUN date (datetime.now), never the plan's date."""
    assert "2026-09-23" not in SCRIPT.read_text(encoding="utf-8")
    mod = _load()
    assert mod.EXPECTED_CASES == 30 and mod.AGENT == "hunter-drive"
    assert mod.MOUNT_MODEL == "gate/research" and mod.MAX_TOKENS >= 16384
    assert "S7C-PARITY-" in SCRIPT.read_text(encoding="utf-8")
