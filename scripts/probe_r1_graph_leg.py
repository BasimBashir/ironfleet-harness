"""R1 retrieval probe: doc↔doc / passage↔passage link expansion vs the C4 baseline.

Evidence probe, not product code (M13.8: adopt into corpus.py ONLY if the link leg
beats the shipped hybrid top-5 needle-supply — 14/69 all / 14 present-set on the
2026-11-05 clean store — else the item closes "measured, not adopted").

Hypothesis under test: passages the ranker misses are linked to passages it does
return — same document (chunk adjacency) or shared citation keys (the cites_<m>
join table) — so expanding the baseline top-5 through those links could pull
PRESENT_NOT_RETRIEVED needles into the final window.

Arms, all at the exact C4 measure (k=5, candidates=50, prompt[:1200]):
  baseline   — store.search, the shipped hybrid (RRF fusion of the three legs)
  doc_link   — baseline hits + same-doc neighbour chunks (fts rowid ±2), merged
  cite_link  — baseline hits + passages sharing a citation key (cites join),
               scored by shared-key count, merged
Merged arms re-cut to 5 after scoring (baseline rank + link credit), i.e. links
must EARN a window slot — replacement, not addition.

Writes JSON evidence to data/eval/R1-ACCEPT/graph_leg_probe.json.
One embed per case; no LLM dispatch, no rerank (server down on 2026-11-11).
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MATTER = "m-r1-accept"


def main_sync() -> None:
    from harness.corpus import CorpusStore, _mtable
    from harness.eval.golden_case import load_cases
    from harness.eval.scorers import citation_hit
    from harness.gate import EmbeddingRequest
    from harness.paths import resolve_store_root
    from harness.vectors import VectorStore
    from scripts.corpus_ingest import build_live_stack

    root, _ = resolve_store_root()
    store = CorpusStore(root / "corpus.sqlite3",
                        vectors=VectorStore(root / "vectors.sqlite3"))
    gate, _ = build_live_stack("graph_probe_trace.sqlite3", MATTER)
    cases = load_cases(REPO / "data/golden_cases")

    # corpus-present denominator, exactly as accept_r1.check_c4_live reads it
    fr = REPO / "data/eval/R1-ACCEPT/retrieval_failure_report.json"
    present = ({(r["case"], r["needle"]) for r in json.loads(fr.read_text(encoding="utf-8"))
                ["needles_detail"] if r["present"]} if fr.exists() else None)

    def _rowid(doc_id: str, heading: str, body: str) -> int | None:
        with store._c() as c:
            r = c.execute(
                f"SELECT rowid FROM {_mtable(MATTER, 'fts')} "
                "WHERE doc_id=? AND heading=? AND body=? LIMIT 1",
                (doc_id, heading, body)).fetchone()
        return r[0] if r else None

    def _doc_neighbours(rid: int) -> list[tuple[str, str, str]]:
        with store._c() as c:
            doc = c.execute(f"SELECT doc_id FROM {_mtable(MATTER, 'fts')} "
                            "WHERE rowid=?", (rid,)).fetchone()
            if not doc:
                return []
            rows = c.execute(
                f"SELECT f.rowid, f.doc_id, f.heading, f.body FROM "
                f"{_mtable(MATTER, 'fts')} f WHERE f.doc_id=? AND f.rowid BETWEEN ? AND ? "
                "AND f.rowid<>? ORDER BY ABS(f.rowid-?)",
                (doc[0], rid - 2, rid + 2, rid, rid)).fetchall()
        return [(d, h, b) for _r, d, h, b in rows]

    def _cite_linked(rid: int) -> list[tuple[str, str, str, int]]:
        """Passages sharing ≥1 citation key with the referrer, scored by key count."""
        with store._c() as c:
            rows = c.execute(
                f"SELECT c2.fts_rowid, COUNT(DISTINCT c2.key) n FROM "
                f"{_mtable(MATTER, 'cites')} c1 JOIN {_mtable(MATTER, 'cites')} c2 "
                "ON c2.key=c1.key WHERE c1.fts_rowid=? AND c2.fts_rowid<>? "
                "GROUP BY c2.fts_rowid ORDER BY n DESC LIMIT 12", (rid, rid)).fetchall()
            out = []
            for lid, n in rows:
                r = c.execute(f"SELECT f.doc_id, f.heading, f.body FROM "
                              f"{_mtable(MATTER, 'fts')} f WHERE f.rowid=?",
                              (lid,)).fetchone()
                if r:
                    out.append((r[0], r[1], r[2], n))
        return out

    def linked_window(hits, mode: str) -> list[str]:
        """Re-cut to 5 with link credit: baseline score 1/(rank+1); a linked passage
        earns referrer/2 (doc) or a key-count-scaled referrer share (cite). Links
        must EARN a slot — replacement, not addition. Deterministic tiebreak."""
        texts: list[str] = [h.text for h in hits]
        scores: dict[str, float] = {h.text: 1.0 / (i + 1) for i, h in enumerate(hits)}
        for i, h in enumerate(hits):
            rid = _rowid(h.doc_id, h.heading, h.text)
            if rid is None:
                continue
            if mode == "doc":
                cand = [(d, hd, b, 0) for d, hd, b in _doc_neighbours(rid)]
            else:
                cand = _cite_linked(rid)
            for d, hd, b, n in cand:
                if b in scores or len(b.split()) < 25:
                    continue
                g = (0.5 if mode == "doc" else min(1.0, n / 3.0)) / (i + 1)
                scores[b] = scores.get(b, 0.0) + g
                if b not in texts:
                    texts.append(b)
        ordered = sorted(texts, key=lambda t: -scores.get(t, 0.0))
        return ordered[:5]

    def supply_count(blob: str, needles: list[str]) -> int:
        return sum(1 for n in needles if citation_hit(blob, n))

    out: dict = {"cases": [], "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    tot = {"baseline": 0, "doc_link": 0, "cite_link": 0}
    tot_p = {"baseline": 0, "doc_link": 0, "cite_link": 0}
    for i, c in enumerate(cases):
        t0 = time.time()
        prompt = c.prompt[:1200]
        needles = c.expected_citations
        res = asyncio.run(gate.embed(EmbeddingRequest(matter_ref=MATTER, texts=[prompt])))
        v = res.vectors[0]
        hits = store.search(MATTER, prompt, v, k=5, candidates=50)
        rec: dict = {"case": c.id, "needles": needles, "elapsed_s": 0.0}
        for arm, blob in [("baseline", "\n".join(h.text for h in hits)),
                          ("doc_link", "\n".join(linked_window(hits, "doc"))),
                          ("cite_link", "\n".join(linked_window(hits, "cite")))]:
            n = supply_count(blob, needles)
            tot[arm] += n
            if present is not None:
                tot_p[arm] += sum(1 for nd in needles
                                  if citation_hit(blob, nd) and (c.id, nd) in present)
            rec[arm] = n
        rec["elapsed_s"] = round(time.time() - t0, 1)
        out["cases"].append(rec)
        print(f"  [{i+1}/30] {c.id}: base {rec['baseline']} doc {rec['doc_link']} "
              f"cite {rec['cite_link']} ({rec['elapsed_s']}s)", flush=True)

    n_all = sum(len(c.expected_citations) for c in cases)
    out["totals"] = {"needles_all": n_all,
                     "needles_present": len(present) if present else None,
                     **{f"supply_{a}": tot[a] for a in tot},
                     **({f"supply_present_{a}": tot_p[a] for a in tot_p}
                        if present else {})}
    dest = REPO / "data/eval/R1-ACCEPT/graph_leg_probe.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("WROTE", dest, out["totals"])


if __name__ == "__main__":
    main_sync()
