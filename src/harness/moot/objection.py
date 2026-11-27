# src/harness/moot/objection.py — M6 platform port of ironfleet-legal/mcp/harness/objection.py
# (G5): the adversary's failure modes as a mechanical, offline check. (a) a cited
# authority not in corpus, (b) a quoted span not in corpus — reuse verify's core 1:1;
# (c) a date/period not matching the kernel's computation for this matter; (d) a
# statutory demand drafted but never kernel-computed.
# PLATFORM DIFFERENCE: the plugin read the run's kernel computations and evidence table
# from its run-ledger trace.jsonl. Here they come from the platform dossier registers:
# kernel dates from `deadlines` (source=kernel, kind filing|statutory_demand) and
# exhibit labels from `evidence` — zero new storage.
"""shortcut: dates are matched as whole calendar days in deadline-context lines only —
a date the draft states outside deadline language is a fact, not an assertion to check.
Upgrade to per-sentence attribution when a drafting stage emits structured dates."""
from __future__ import annotations

import bisect
import re
from pathlib import Path

from harness.corpus import _REF_TOKEN
from harness.moot.verify import (MIN_QUOTE_WORDS, _QUOTE, _locate, _norm,
                                 load_chunks, verify_document)

# platform deadlines register kind -> (deadline key, days key) in the comp dict
_KERNEL_KINDS = {"filing": ("deadline", "days"),
                 "statutory_demand": ("compliance_deadline", "compliance_period_days")}
_TOOL_FOR_KIND = {"filing": "ironfleet_filing_deadline",
                  "statutory_demand": "ironfleet_statutory_demand"}
_CTX = re.compile(r"(?i)deadline|complian|no later than|working days")
_CTX_STRICT = re.compile(r"(?i)deadline|compl")        # for periods: _PERIOD already
                                                       # guarantees a days phrase
_PERIOD = re.compile(r"(?i)within (\d+) (?:working )?days?")
_SD_DECLINED = re.compile(r"(?i)\b(?:defer(?:red|s)?|do not|don't|not (?:to )?serv|no demand|"
                          r"not recommended|instead of|rather than|avoid|premature)")
_MONTHS = {m: i for i, m in enumerate(
    ("jan feb mar apr may jun jul aug sep oct nov dec").split(), 1)}
_PROSE_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*\s+(\d{4})\b", re.I)
_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")   # NZ day-first
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _store_path(store: object | None) -> Path:
    if store is not None:
        return Path(store.db_path)
    from harness.paths import resolve_store_root
    root, _source = resolve_store_root()
    return Path(root) / "corpus.sqlite3"


def _kernel_computations(con, matter: str) -> list[dict]:
    """The kernel computations for this matter, from the deadlines register — the
    platform's replacement for the plugin's run-ledger tool_result events."""
    comps = []
    try:
        rows = con.execute(
            "SELECT what, due, rule, service_date, kind FROM deadlines"
            " WHERE matter_id=? AND source='kernel' ORDER BY ts, rowid",
            (matter,)).fetchall()
    except Exception:                                  # noqa: BLE001 — no register, still object
        return []
    for r in rows:
        kind = r["kind"]
        if kind not in _KERNEL_KINDS:
            continue
        dkey, pkey = _KERNEL_KINDS[kind]
        if not r["due"]:
            continue
        comps.append({"tool": _TOOL_FOR_KIND[kind], "deadline": str(r["due"])[:10],
                      "days": r["rule"].split(":")[1].split(" ")[0] if ":" in (r["rule"] or "") else None,
                      "service": str(r["service_date"])[:10] if r["service_date"] else None,
                      "kind": kind})
    # the days value: parse it out of the rule text only when numeric, else None
    out = []
    for c in comps:
        days = c["days"]
        if isinstance(days, str):
            m = re.match(r"\s*(\d+)", days)
            days = m.group(1) if m else None
        out.append({**c, "days": days})
    return out


def _dates(text: str) -> dict[str, int]:
    """Every date the draft states -> ISO, mapped to its first offset. A date stated
    twice counts once (first occurrence wins the context check)."""
    out: dict[str, int] = {}
    for m in _ISO_DATE.finditer(text):
        out.setdefault(m.group(1), m.start())
    for m in _PROSE_DATE.finditer(text):
        out.setdefault(f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-"
                       f"{int(m.group(1)):02d}", m.start())
    for m in _SLASH_DATE.finditer(text):
        out.setdefault(f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}",
                       m.start())
    return out


def _pin(evidence: dict[str, str], chunks: list[dict], text: str,
         refs: list[dict]) -> None:
    """Upgrade ref verdicts in place from borrowed (nearest preceding quote) to pinned
    (the matter's own evidence table). A table sentence nowhere in the corpus is loud;
    a draft quote that differs from its pinned sentence is the MISMATCH G1 deferred."""
    spans: list[str] = []
    ends: list[int] = []
    for m in _QUOTE.finditer(text):
        span = _norm(m.group(1))
        if len(span.split()) >= MIN_QUOTE_WORDS:
            spans.append(span)
            ends.append(m.end())
    for row, m in zip(refs, _REF_TOKEN.finditer(text)):
        pinned = evidence.get(row["ref"])
        if pinned is None:
            continue
        hit, quotable = _locate(chunks, pinned)
        if hit is None:
            row.update(verdict="NOT_IN_CORPUS", found_in=None,
                       pinned="the evidence table's sentence is nowhere in this corpus")
            continue
        i = bisect.bisect_right(ends, m.start()) - 1
        owner = spans[i] if i >= 0 else None
        if owner is not None and owner != pinned:
            row.update(verdict="MISMATCH", found_in=hit["source_name"],
                       pinned=f'the draft quotes "{owner[:80]}" but the evidence table '
                              f'pins "{pinned[:80]}"')
        else:
            row.update(verdict="VERIFIED", found_in=hit["source_name"], pinned=True)


def objection(con, matter: str, path: str, store: object | None = None) -> dict:
    """The adversary's failure modes over one draft. Never raises; ok=false means
    objections stand. `con` is the platform.db connection (deadlines register); the
    evidence table comes from the evidence register."""
    out = {"matter": matter, "path": str(path), "objections": [], "ok": True,
           "kernel": {"computations": 0, "deadlines_matched": 0}}
    v = verify_document(matter, path, store=store)
    out["corpus_chunks"] = v.get("corpus_chunks", 0)
    if v.get("error"):
        out["ok"] = False
        out["error"] = v["error"]
        return out

    f = Path(path)
    sp = _store_path(store)
    if store is not None and not f.is_absolute():
        f = sp.parent / f
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as ex:
        out["ok"] = False
        out["error"] = f"deliverable not readable: {ex}"
        return out

    # evidence table: the register's label -> pinned sentence, when the register
    # carries one (op=add rows with a `sentence`); refs pin against it when present
    evidence: dict[str, str] = {}
    try:
        from harness.lifecycle import dossier
        for e in dossier.read(con, matter, "evidence")["events"]:
            if e.get("label") and e.get("sentence"):
                evidence[str(e["label"]).strip()] = _norm(str(e["sentence"]))
    except Exception:                                  # noqa: BLE001 — no register, still object
        evidence = {}
    chunks = load_chunks(matter, sp)
    if evidence:
        _pin(evidence, chunks, text, v["refs"])

    # (a) + (b): every ungrounded verify row is an objection
    for q in v["quotes"]:
        if q["verdict"] != "VERIFIED":
            out["objections"].append({"kind": "quote_not_in_corpus",
                                      "verdict": q["verdict"],
                                      "quote": q["quote"][:120], "line": q["line"]})
    for row in v["refs"]:
        if row["verdict"] != "VERIFIED":
            out["objections"].append({"kind": "authority_not_in_corpus",
                                      "verdict": row["verdict"], "ref": row["ref"],
                                      "found_in": row.get("found_in"),
                                      "line": row["line"], "note": row.get("pinned")})

    # (c): dates/periods vs the kernel's computation for this matter
    comps = _kernel_computations(con, matter)
    out["kernel"]["computations"] = len(comps)
    if comps:
        dates = _dates(text)
        want = {c["deadline"] for c in comps}
        served = {str(c["service"]) for c in comps if c.get("service")}
        # a draft that never speaks of deadlines (an attack brief) cannot omit one;
        # a deadline-speaking draft must state the kernel's computation or it is
        # stating something else in its place
        talks_deadlines = bool(_CTX.search(text))
        for c in comps:
            if c["deadline"] in dates:
                out["kernel"]["deadlines_matched"] += 1
            elif talks_deadlines:
                out["objections"].append({
                    "kind": "date_not_matching_kernel",
                    "detail": f"{c['tool']} computed deadline {c['deadline']}"
                              + (f" ({c['days']} days from service "
                                 f"{c['service']})" if c.get("service") else "")
                              + " but the draft never states it"})
        starts = [0] + [mm.end() for mm in re.finditer(r"\n", text)]
        lines = text.splitlines()
        for iso, off in dates.items():
            if iso in want or iso in served:
                continue
            ln = bisect.bisect_right(starts, off)
            if ln <= len(lines) and _CTX.search(lines[ln - 1]):
                out["objections"].append({
                    "kind": "date_not_matching_kernel", "line": ln,
                    "detail": f"the draft asserts {iso} in a deadline context; no "
                              f"kernel computation registered for this matter produced it"})
        periods = {str(c["days"]) for c in comps if c.get("days")}
        if periods:
            for m in _PERIOD.finditer(text):
                ln = bisect.bisect_right(starts, m.start())
                if (ln <= len(lines) and _CTX_STRICT.search(lines[ln - 1])
                        and m.group(1) not in periods):
                    out["objections"].append({
                        "kind": "date_not_matching_kernel", "line": ln,
                        "detail": f"the draft states \"{m.group(0)}\"; the kernel "
                                  f"computed {sorted(periods)} days for this matter"})
    else:
        out["kernel"]["note"] = ("no kernel computations registered for this matter "
                                 "(deadlines register, source=kernel)")

    # (d): a draft that raises a statutory demand must have a kernel row — found live
    # 2026-10-26 in the plugin; the platform register is the same enforcement point.
    # A line that defers or declines the demand does not raise one (Mac 1.0.1 retest:
    # "Defer the s 289 statutory demand (do NOT serve now)" capped the moot 4 rounds).
    # shortcut: the decline cue must sit on the same line as the mention; upgrade to
    # sentence-level parsing if a draft splits "statutory demand" and "do not" across lines.
    raises_sd = any(re.search(r"(?i)statutory demand", ln) and not _SD_DECLINED.search(ln)
                    for ln in text.splitlines())
    if raises_sd and not any(c["kind"] == "statutory_demand" for c in comps):
        out["objections"].append({
            "kind": "statutory_demand_not_computed",
            "detail": "the draft raises a statutory demand but this matter has no "
                      "statutory_demand kernel row registered — register it via "
                      "lifecycle.deadlines.register (amount vs the $1,000 minimum; "
                      "the compliance deadline) and state its result"})

    out["refs"] = v["refs"]
    out["quotes"] = v["quotes"]
    out["verify_summary"] = v["summary"]
    out["summary"] = {k: sum(1 for o in out["objections"] if o["kind"] == k)
                      for k in ("authority_not_in_corpus", "quote_not_in_corpus",
                                "date_not_matching_kernel",
                                "statutory_demand_not_computed")}
    out["ok"] = not out["objections"]
    if not out["ok"]:
        out["remedy"] = ("fix each objection in the draft or answer it in the "
                         "adversary's prose")
    return out
