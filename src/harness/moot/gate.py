# src/harness/moot/gate.py — M6 platform: the moot gate's deterministic pre-pass +
# the keep-if-better comparator + the seeded-flaw scorer + the verdict recorder.
# Ported from ironfleet-legal/mcp/moot.py; the pre-pass wraps the platform's
# objection + citator + checks, with kernel/evidence inputs from the dossier
# registers (deadlines, evidence). The verdict lands in the append-only audit chain
# as action="moot.verdict"; flaw rows go through dossier's flaws register.
# Agent-layer recall is reported from live moot rounds, never asserted here.
from __future__ import annotations

import json
from pathlib import Path

from harness.lifecycle import dossier
from harness.moot.checks import check
from harness.moot.citator import citator
from harness.moot.objection import objection
from harness.workflow import audit

SEVERITIES = ("critical", "material", "minor")
_BLOCKING = ("critical", "material")
_CLASSES = ("fabricated_case", "misquote", "wrong_deadline", "missing_exhibit",
            "wrong_form", "citator_later")
# objection kinds -> the seeded flaw class they detect (the eval's vocabulary)
_CLASS_FOR = {
    "authority_not_in_corpus": "fabricated_case",
    "quote_not_in_corpus": "misquote",
    "date_not_matching_kernel": "wrong_deadline",
    "statutory_demand_not_computed": "wrong_form",
}
_NON_BLOCKING = {"statutory_demand_not_computed"}


def _evidence_labels(con, matter: str) -> set[str]:
    out = set()
    for e in dossier.read(con, matter, "evidence")["events"]:
        if e.get("label"):
            out.add(str(e["label"]).strip().lower().removeprefix("exhibit ").strip())
    return out


def moot_check(con, matter: str, path, store=None) -> dict:
    """The deterministic pre-pass over one draft. Never raises; ok=false means
    blocking flaws stand and the gate cannot pass this draft as-is."""
    o = objection(con, matter, path, store=store)
    if o.get("error"):
        return {"matter": matter, "path": str(path), "flaws": [], "ok": False,
                "error": o["error"], "summary": {c: 0 for c in _CLASSES}}
    flaws = []
    for ob in o["objections"]:
        detail = "; ".join(str(ob.get(k)) for k in ("detail", "quote", "ref", "note")
                           if ob.get(k)) or ob.get("kind", "objection")
        flaws.append({
            "class": _CLASS_FOR.get(ob["kind"], "other"),
            # a PLANNED demand has no service date yet, and only the operator can register
            # the kernel row (no agent can) — so it is a note for the human approver, not a
            # block (1.0.2 Windows test: every "serve a demand" roadmap CAPPED). Wrong demand
            # numbers still block via check() -> form_rows (wrong_form, critical).
            "severity": "minor" if ob["kind"] in _NON_BLOCKING else "critical",
            "detector": "objection",
            "kind": ob.get("kind"),
            "detail": detail,
        })
        if ob.get("line"):
            flaws[-1]["line"] = ob["line"]
    # citator: informational by design — surfaced as minor rows, never blocks
    try:
        c = citator(matter, path=path, store=store)
        for a in c.get("authorities", []):
            if a.get("later_citing"):
                flaws.append({
                    "class": "citator_later",
                    "severity": "minor",
                    "detector": "citator",
                    "detail": 'authority "' + str(a.get("key")) + '" has '
                              + str(a["later_citing"]) + " later citing judgment(s)"
                              " — the good-law reading call is human",
                })
    except Exception:                                  # noqa: BLE001 — best effort
        pass
    f = Path(path)
    if not f.is_absolute() and not f.exists():
        # a relative path that misses from the CWD is store-root-relative (a
        # workspace deliverable); verify/objection read CWD-relative, match them
        if store is not None:
            f = Path(store.db_path).parent / f
        else:
            from harness.paths import resolve_store_root
            root, _source = resolve_store_root()
            f = Path(root) / f
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"matter": matter, "path": str(path), "flaws": [], "ok": False,
                "error": "deliverable not readable",
                "summary": {c: 0 for c in _CLASSES}}
    labels = _evidence_labels(con, matter)
    for r in check(text, labels):
        flaws.append({
            "class": r["class"],
            "severity": r["severity"],
            "detector": "moot-check",
            "detail": r["detail"],
            "line": r["line"],
        })
    counts = {}
    for c in _CLASSES:
        counts[c] = sum(1 for fl in flaws if fl["class"] == c)
    blocking = [fl for fl in flaws if fl["severity"] in _BLOCKING]
    return {"matter": matter, "path": str(path), "flaws": flaws, "ok": not blocking,
            "blocking_count": len(blocking), "summary": counts,
            "note": "ok=false means blocking flaws stand — fix each or answer it in "
                    "the adversary's prose, then re-run; agent attacks land via the "
                    "moot stage's rounds, this pass is the mechanical floor"}


def compare(baseline, candidate):
    """Keep-if-better, the S7i bar on three axes: keep iff <= on all and
    strictly < on >= 1; all-tie -> rollback; a worse axis -> rollback (naming it);
    counts that are not three integers -> refuse (unusable leg)."""
    try:
        b = [int(baseline[k]) for k in SEVERITIES]
        c = [int(candidate[k]) for k in SEVERITIES]
    except (KeyError, TypeError, ValueError):
        return {"keep": False, "verdict": "REFUSED",
                "reason": "unusable leg — both legs need integer critical/material/"
                          "minor counts"}
    if c == b:
        return {"keep": False, "verdict": "ROLLBACK",
                "reason": "all-tie on critical/material/minor — rollback, not keep"}
    better = []
    worse = []
    for name, cb, bb in zip(SEVERITIES, c, b):
        if cb < bb:
            better.append(name)
        if cb > bb:
            worse.append(name)
    if worse:
        return {"keep": False, "verdict": "ROLLBACK",
                "reason": "regression on " + repr(worse) + " — rollback"}
    return {"keep": True, "verdict": "KEEP",
            "reason": "better on " + repr(better) + ", worse on none"}


def score(manifest, results):
    """The seeded-flaw scorer: a seeded flaw is DETECTED when the gate produced a
    flaw row of the same class on that doc. Clean controls count false positives
    on blocking severities only (minor rows are noise, not misses)."""
    per_class = {}
    detected = 0
    total = 0
    controls = 0
    fp = 0
    for doc in manifest["docs"]:
        rows = results.get(doc["file"], {}).get("flaws", [])
        if doc["class"] == "clean":
            controls += 1
            if any(r.get("severity") in _BLOCKING for r in rows):
                fp += 1
            continue
        total += 1
        pc = per_class.setdefault(doc["class"], {"docs": 0, "detected": 0})
        pc["docs"] += 1
        if any(r.get("class") == doc["class"] for r in rows):
            pc["detected"] += 1
            detected += 1
    rate = (detected / total) if total else 0.0
    return {"per_class": per_class,
            "overall": {"docs": total, "detected": detected, "rate": rate},
            "controls": {"docs": controls, "false_positives": fp},
            "bar": 0.90, "meets_bar": total > 0 and rate >= 0.90}


def record_verdict(con, *, matter_id: str, execution_id: str, verdict: str,
                   rounds: int, run_id: str, docs: list[str],
                   actor: str = "moot-gate") -> str:
    """One audit event (action="moot.verdict") in the caller's open transaction —
    the append-only, hash-chained record that approvals.request requires before a
    filing approval can be created. `verdict` is PASSED | CAPPED."""
    payload = {"verdict": verdict, "rounds": rounds, "run_id": run_id,
               "docs": docs, "execution_id": execution_id}
    return audit.append(con, matter_id=matter_id, actor=actor,
                        action="moot.verdict", target=run_id,
                        inputs_digest=json.dumps(payload, sort_keys=True)[:500])


def last_verdict(con, matter_id: str, execution_id: str) -> dict | None:
    """The latest moot.verdict audit row for this execution, or None."""
    rows = con.execute(
        "SELECT inputs_digest FROM audit_events WHERE matter_id=? AND action="
        "'moot.verdict' ORDER BY rowid DESC", (matter_id,)).fetchall()
    for r in rows:
        try:
            d = json.loads(r["inputs_digest"])
        except (TypeError, ValueError):
            continue
        if d.get("execution_id") == execution_id:
            return d
    return None
