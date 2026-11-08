# tests/test_moot_eval_platform.py — M6 platform: the seeded-flaw eval runs ON THE
# PLATFORM. Ingest the harbour-freight dummy corpus into a temp CorpusStore, register
# the two kernel deadlines through lifecycle.deadlines.register into a temp
# platform.db, seed the evidence register (Exhibits A/B/C), run the platform
# moot_check over all 34 docs of ironfleet-legal/tests/moot-eval/ (read BY PATH,
# never copied — the accept_m5 rule), and hold the plugin's line: detection >= 0.90
# overall with 0 false positives on the controls, and >= the plugin's 30/30.
# Offline: fake embeddings, no Ollama, no Claude, no network.
import json
import sys
from pathlib import Path

import pytest

HARNESS_CORE = Path(__file__).resolve().parents[1]
PLUGIN = HARNESS_CORE.parent / "ironfleet-legal"
MEVAL = PLUGIN / "tests" / "moot-eval"
CORPUS = PLUGIN / "dummy-case-harbour-freight" / "docs"
MATTER = "harbour-freight"

sys.path.insert(0, str(HARNESS_CORE / "src"))

from harness.corpus import CorpusStore, DocRecord, chunk_text  # noqa: E402
from harness.lifecycle import deadlines, dossier  # noqa: E402
from harness.moot import gate  # noqa: E402
from harness.workflow.db import connect  # noqa: E402


def _fake_embed(texts):
    return [[float((ord(t[i % len(t) or 1]) + i) % 17) for i in range(1024)]
            for t in texts]


@pytest.fixture(scope="module")
def eval_env(tmp_path_factory):
    """The platform store (dummy corpus ingested with fake vectors), a temp
    platform.db with both kernel computations registered, and the evidence
    register — everything the gate sees, registered mechanically."""
    root = tmp_path_factory.mktemp("moot-eval-platform")
    store = CorpusStore(root / "corpus.sqlite3")
    ingested = 0
    for f in sorted(CORPUS.iterdir()):
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            if len(text.split()) < 10:
                continue
            doc = DocRecord(doc_id=f"doc-{f.stem}", text=text, source_name=f.name)
            texts = chunk_text(doc.doc_id, text)
            store.ingest(MATTER, doc, vectors=_fake_embed(texts), model="fake",
                         provider="fake")
            ingested += len(texts)
    assert ingested > 0, "dummy corpus did not chunk"
    con = connect(root / "platform.db")
    # The two kernel computations, seeded into the deadlines register exactly as the
    # plugin's eval logged them as tool_result events (2026-04-24 for 15 days from
    # service 2026-04-03) — the seeded docs were authored against those values, so
    # the platform register carries the same rows (source=kernel) rather than
    # re-deriving a different date through the calendar.
    dossier.append(con, MATTER, "deadlines",
                   {"what": "filing deadline for the proceeding",
                    "due": "2026-04-24",
                    "rule": "court_filing_deadline: 15 working days from service "
                            "2026-04-03 (nz)",
                    "source": "kernel", "service_date": "2026-04-03",
                    "kind": "filing", "status": "open"})
    dossier.append(con, MATTER, "deadlines",
                   {"what": "statutory demand compliance",
                    "due": "2026-04-24",
                    "rule": "statutory demand compliance period: 15 working days "
                            "from service 2026-04-03 (nz)",
                    "source": "kernel", "service_date": "2026-04-03",
                    "kind": "statutory_demand", "status": "open"})
    for label in ("Exhibit A", "Exhibit B", "Exhibit C"):
        dossier.append(con, MATTER, "evidence",
                       {"op": "add", "label": label, "file": f"{label}.pdf",
                        "sha256": "0" * 64})
    yield {"root": root, "store": store, "con": con}
    con.close()


def test_seeded_flaws_meet_the_bar_on_the_platform(eval_env):
    """30 seeded critical flaws (6 per class x 5 classes) + 4 clean controls:
    detection >= 0.90 overall, 0 controls blocked — and at or above the plugin's
    30/30. The table prints on failure."""
    manifest = json.loads((MEVAL / "manifest.json").read_text(encoding="utf-8"))
    results = {}
    for doc in manifest["docs"]:
        p = MEVAL / doc["file"]
        assert p.exists(), f"eval doc missing: {doc['file']}"
        results[doc["file"]] = gate.moot_check(eval_env["con"], MATTER, str(p),
                                               store=eval_env["store"])
    s = gate.score(manifest, results)
    lines = [f"{c:17s} {pc['detected']:>2}/{pc['docs']:<2}"
             for c, pc in s["per_class"].items()]
    table = (f"overall {s['overall']['detected']}/{s['overall']['docs']} "
             f"= {s['overall']['rate']:.2f} (bar {s['bar']}); "
             f"controls FP {s['controls']['false_positives']}/{s['controls']['docs']}; "
             + "  ".join(lines))
    assert s["meets_bar"], table
    assert s["controls"]["false_positives"] == 0, table
    # at or above the plugin's detection rate (30/30 = 1.00)
    assert s["overall"]["rate"] >= 1.00, table


def test_compare_keep_if_better():
    assert gate.compare({"critical": 1, "material": 0, "minor": 2},
                        {"critical": 0, "material": 0, "minor": 2})["verdict"] == "KEEP"
    assert gate.compare({"critical": 1, "material": 0, "minor": 2},
                        {"critical": 1, "material": 0, "minor": 2})["verdict"] == "ROLLBACK"
    assert gate.compare({"critical": 0, "material": 0, "minor": 2},
                        {"critical": 1, "material": 0, "minor": 2})["verdict"] == "ROLLBACK"
    assert gate.compare({"critical": 1},
                        {"critical": 0, "material": 0, "minor": 0})["verdict"] == "REFUSED"


def test_record_verdict_lands_in_audit(eval_env):
    con = eval_env["con"]
    con.execute("BEGIN IMMEDIATE")
    aid = gate.record_verdict(con, matter_id=MATTER, execution_id="exec-test",
                              verdict="PASSED", rounds=2, run_id="run-test",
                              docs=["filings-roadmap.md"])
    con.execute("COMMIT")
    assert aid.startswith("aud-")
    v = gate.last_verdict(con, MATTER, "exec-test")
    assert v["verdict"] == "PASSED" and v["rounds"] == 2
    assert gate.last_verdict(con, MATTER, "exec-other") is None
