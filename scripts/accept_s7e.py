"""S7e acceptance — A-4 mechanical slot + local embeddings (spec 08, section 5).

Five strict checks; exit 0 ONLY if all pass; a failure names the check and exits 1.
No partial mode (S7c user decision 4: keep docs).

  C1 embedding routes local-only, positively — gate/embedding resolves to the
     embedding class and routes to EXACTLY [ollama-embed] (local, mechanical-only)
  C2 the egress invariant under ADVERSARIAL config — a cloud embedder the routing
     table EXPLICITLY permits under cloud_permitted is still refused. THE LOAD-
     BEARING CHECK: this is the module's reason to exist
  C3 a live embed is traced completely — honest CR-3 values, tokens_out=0, dim 1024
  C4 round-trip retrieval + matter isolation in the vector store
  C5 fail-closed still traced — a table with no embedding rule refuses + GateRefusal

No opencode and no proxy: bge-m3 is not a chat model and embeddings are a harness-
internal dispatch path, so the gate is driven directly (like S7d's C3, without a
session). No new mount surface means no SEAM_COUNT change.

Usage: .venv/Scripts/python.exe scripts/accept_s7e.py [--keep-ws]
"""
from __future__ import annotations

import argparse, asyncio, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))   # scripts.* imports (stand_up_opencode.py:33-38 lesson)

from harness.alias import load_aliases, resolve_alias
from harness.gate import EmbeddingRequest, GateRefusal
from harness.policy import MatterPolicy, RoutingTable
from harness.providers.config import ProviderConfig
from harness.vectors import VectorStore
from scripts.stand_up_opencode import ROUTING, build_gate

WS = Path.home() / "spike-ws-a1" / "opencode-a1-s7e-accept"
MATTER_REF = "m-s7e-accept"
MATTER_OTHER = "m-s7e-other"
EMBED_MODEL = "bge-m3:567m"

TEXTS = [
    "The defendant breached the settlement agreement dated 3 March 2026.",
    "Section 9 of the Contract and Commercial Law Act 2017 applies to this transaction.",
    "Without prejudice correspondence is inadmissible as evidence of a concession.",
]
TEXTS_2 = [
    "The court ordered specific performance of the easement over Lot 2 DP 12345.",
    "The GST adjustment was calculated on the settlement date.",
    "The trust's vesting date passed without an appointment of trustees.",
]

# Adversarial: a cloud embedder the table EXPLICITLY permits under cloud_permitted, listed
# alongside the local one so the check can also prove the local embedder survives the filter.
ADVERSARIAL_ROUTING = """rules:
  - task_class: embedding
    local_only: [ollama-embed]
    local_preferred: [ollama-embed]
    cloud_permitted: [cloud-embed, ollama-embed]   # misconfigured on purpose (C2)
defaults:
  local_only: []
  local_preferred: []
  cloud_permitted: []
"""

# C5: no embedding rule at all -> the class falls to the empty defaults and refuses.
NO_EMBEDDING_RULE = """rules: []
defaults:
  local_only: []
  local_preferred: []
  cloud_permitted: []
"""


def check_c1(gate) -> list[str]:
    """gate/embedding resolves to the embedding class and routes to exactly the local
    mechanical embedder. Reads the COMMITTED routing-a1.yaml (the driver's own table is
    built from the same file, so this is the same object either way)."""
    problems: list[str] = []
    aliases = load_aliases(ROUTING)
    try:
        tc = resolve_alias("gate/embedding", aliases)
    except Exception as ex:                       # noqa: BLE001
        return [f"C1: gate/embedding does not resolve: {ex}"]
    if tc != "embedding":
        problems.append(f"C1: gate/embedding resolves to {tc!r}, not 'embedding'")
    rt = RoutingTable.from_yaml(ROUTING)
    picks = rt.route("embedding",
                     MatterPolicy(matter_ref=MATTER_REF, classification="CLOUD_PERMITTED"),
                     gate.registry)
    names = [c.name for c in picks]
    if names != ["ollama-embed"]:
        problems.append(f"C1: embedding class routed to {names}, expected exactly [ollama-embed]")
    # The registered provider, not the picks: a cloud-tier ollama-embed is already filtered
    # out of picks, so reading the shape from picks would leave the misregistration unnamed.
    emb = next((c for c in gate.registry.list() if c.name == "ollama-embed"), None)
    if emb is None:
        problems.append("C1: ollama-embed is not registered — the class has no local embedder")
    else:
        if emb.tier != "local":
            problems.append(f"C1: ollama-embed tier={emb.tier!r}, expected tier=local")
        if emb.admitted != "mechanical-only":
            problems.append(f"C1: ollama-embed admitted={emb.admitted!r}, expected "
                            "mechanical-only (the honest CR-3 reading for Ollama)")
    return problems


def check_c2(gate) -> list[str]:
    """The load-bearing check. A cloud embedder is registered as fully admitted AND named
    in the adversarial fixture's cloud_permitted — routing must still refuse it.

    The provider is upserted only when absent, so a caller may pre-place a differently
    configured one: the check must test the routing filter, not the upsert.
    """
    problems: list[str] = []
    if "cloud-embed" not in {c.name for c in gate.registry.list()}:
        gate.registry.upsert(ProviderConfig(
            name="cloud-embed", base_url="https://fake.example.invalid/v1",
            engine="cloud", tier="cloud", model="cloud-embed-1", admitted="full"))
    WS.mkdir(parents=True, exist_ok=True)
    p = WS / "adversarial.yaml"
    p.write_text(ADVERSARIAL_ROUTING)
    rt = RoutingTable.from_yaml(p)
    # The fixture must genuinely be adversarial, else the check is vacuous.
    rule = next((r for r in rt._rules if r.get("task_class") == "embedding"), None)
    permitted = (rule or {}).get("cloud_permitted") or []
    if "cloud-embed" not in permitted:
        problems.append("C2: the adversarial fixture does not name cloud-embed in "
                        "cloud_permitted — the check is not testing anything")
        return problems
    if "cloud-embed" not in {c.name for c in gate.registry.list()}:
        problems.append("C2: no cloud-embed provider in the registry — the check is "
                        "not testing anything")
        return problems
    picks = rt.route("embedding",
                     MatterPolicy(matter_ref=MATTER_REF, classification="CLOUD_PERMITTED"),
                     gate.registry)
    names = [c.name for c in picks]
    if "cloud-embed" in names:
        problems.append(f"C2: cloud-embed was REACHED for embedding under "
                        f"CLOUD_PERMITTED — the egress invariant FAILED: {names}")
    if names != ["ollama-embed"]:
        problems.append(f"C2: expected only [ollama-embed] after the filter, got {names}")
    return problems


async def check_c3(gate):
    """A live embed through the gate on real privileged-shaped text; one traced row with
    the honest CR-3 values. Returns (problems, response)."""
    problems: list[str] = []
    try:
        res = await gate.embed(EmbeddingRequest(matter_ref=MATTER_REF, texts=TEXTS))
    except Exception as ex:                       # noqa: BLE001
        return [f"C3: live embed raised {ex!r}"], None
    if len(res.vectors) != len(TEXTS):
        problems.append(f"C3: expected {len(TEXTS)} vectors, got {len(res.vectors)}")
        return problems, res
    dims = {len(v) for v in res.vectors}
    if dims != {1024}:
        problems.append(f"C3: expected 1024-dim bge-m3 vectors, got dims {dims}")
    rows = [r for r in gate.trace.by_matter(MATTER_REF) if r.task_class == "embedding"]
    ok = [r for r in rows if r.status == "ok"]
    if len(ok) != 1:
        problems.append(f"C3: expected exactly 1 ok embedding row, got {len(ok)} "
                        f"of {len(rows)} rows")
        return problems, res
    r = ok[0]
    expected = {"provider": "ollama-embed", "model": EMBED_MODEL, "tokens_out": 0,
                "backend": "", "verified": 0, "status": "ok"}
    for attr, want in expected.items():
        got = getattr(r, attr)
        if got != want:
            problems.append(f"C3: trace row {attr}={got!r}, expected {want!r}")
    if not r.tokens_in:
        problems.append("C3: tokens_in empty — the embed's prompt tokens were not traced")
    if not res.vectors or not res.vectors[0]:
        problems.append("C3: empty vector returned")
    return problems, res


async def check_c4(gate, res) -> list[str]:
    """Round-trip: the query's own text is the top hit at cosine ~1.0, and a second
    matter's search never sees the first matter's texts."""
    problems: list[str] = []
    if res is None:
        return ["C4: no embedding result from C3 to store"]
    try:
        res2 = await gate.embed(EmbeddingRequest(matter_ref=MATTER_OTHER, texts=TEXTS_2))
    except Exception as ex:                       # noqa: BLE001
        return [f"C4: second live embed raised {ex!r}"]
    store = VectorStore(WS / "vectors.db")
    n1 = store.add(MATTER_REF, TEXTS, res.vectors, model=EMBED_MODEL, provider="ollama-embed")
    n2 = store.add(MATTER_OTHER, TEXTS_2, res2.vectors, model=EMBED_MODEL, provider="ollama-embed")
    if n1 != len(TEXTS) or n2 != len(TEXTS_2):
        return [f"C4: add returned {n1}/{n2}, expected {len(TEXTS)}/{len(TEXTS_2)}"]
    hits = store.search(MATTER_REF, res.vectors[0], k=3)
    if not hits:
        return ["C4: search returned no hits for an exact stored vector"]
    if hits[0].text != TEXTS[0]:
        problems.append(f"C4: top hit was {hits[0].text!r}, expected {TEXTS[0]!r}")
    elif hits[0].score < 0.999:
        problems.append(f"C4: self-match cosine {hits[0].score:.6f} < 0.999")
    if any(h.text not in TEXTS for h in hits):
        problems.append("C4: the other matter's texts leaked into this matter's results")
    other = store.search(MATTER_OTHER, res2.vectors[0], k=3)
    if not other or other[0].text != TEXTS_2[0]:
        problems.append("C4: the other matter's own vector did not retrieve its own text")
    if any(h.text in TEXTS for h in other):
        problems.append("C4: this matter's texts leaked into the other matter's results")
    return problems


def check_c5() -> list[str]:
    """A table with no embedding rule: the class falls to the empty defaults, no
    candidate qualifies, and embed() traces a refusal and raises — the SAME refusal
    semantics dispatch() uses.

    Synchronous: build_gate() probes Ollama via asyncio.run internally, so this check
    must not itself run inside an event loop (main calls it directly, not via
    asyncio.run). Only the single embed() call needs a loop.
    """
    problems: list[str] = []
    p = WS / "no-embedding.yaml"
    p.write_text(NO_EMBEDDING_RULE)
    gate, _rt, _aliases = build_gate(WS / "trace-c5.db", routing=p)
    try:
        asyncio.run(gate.embed(EmbeddingRequest(matter_ref=MATTER_REF, texts=["a"])))
        problems.append("C5: embed against a table with no embedding rule did not raise")
    except GateRefusal:
        pass
    except Exception as ex:                        # noqa: BLE001
        return [f"C5: expected GateRefusal, got {type(ex).__name__}: {ex}"]
    rows = [r for r in gate.trace.by_matter(MATTER_REF) if r.status == "refused"]
    if not rows:
        problems.append("C5: no refusal row was traced")
    elif rows[-1].provider != "-":
        problems.append(f"C5: refusal row provider={rows[-1].provider!r}, expected '-'")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keep-ws", action="store_true",
                    help="keep the acceptance workspace for evidence inspection")
    args = ap.parse_args(argv)

    shutil.rmtree(WS, ignore_errors=True)          # failure-tolerant (S7d Task 5 fix)
    WS.mkdir(parents=True, exist_ok=True)

    gate, rt, aliases = build_gate(WS / "trace.db")
    print(f"[accept-s7e] aliases: {sorted(aliases)}", file=sys.stderr)

    problems: list[str] = []
    problems += check_c1(gate)
    problems += check_c2(gate)
    c3, res = asyncio.run(check_c3(gate))
    problems += c3
    problems += asyncio.run(check_c4(gate, res))
    problems += check_c5()

    print("", file=sys.stderr)
    if problems:
        for p in problems:
            print(f"  FAIL  {p}", file=sys.stderr)
        print(f"[accept-s7e] REJECTED: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    print("[accept-s7e] ACCEPTED: C1 embedding routes local-only; C2 cloud embedder "
          "configured-but-refused; C3 live embed traced (backend='', verified=0, "
          "tokens_out=0); C4 round-trip retrieval + matter isolation; C5 fail-closed "
          "traced.", file=sys.stderr)
    if not args.keep_ws:
        shutil.rmtree(WS, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
