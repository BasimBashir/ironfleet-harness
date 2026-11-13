# src/harness/service/documents.py — upload/ingest/list/bytes (M7, 04 §5.3)
"""Upload = raw request body + ?filename=&doc_type=&jurisdiction= query params
(plan §0.1 — no python-multipart). The bytes land under the store root's
documents/ tree; the row carries sha256 + size + relative path. Ingest is the
existing service.ingest.ingest_source, run synchronously here and reported via
the document row's ingest_status (202 + run row per plan §3)."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from harness.service import authz, ingest
from harness.workflow import audit

WRITE = "matter.write"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc_row(r) -> dict:
    return dict(r)


def upload(con, principal: dict, matter_id: str, body: bytes, *, filename: str,
           doc_type: str = "", jurisdiction: str = "",
           store_root: Path | None = None) -> dict:
    authz.require(con, principal, WRITE, matter_id)
    if not filename or not body:
        raise authz.ServiceError(422, "validation_failed",
                                 "filename and a non-empty body are required")
    doc_id = f"doc-{uuid.uuid4().hex[:12]}"
    sha = hashlib.sha256(body).hexdigest()
    rel = Path("documents") / matter_id / f"{doc_id}-{Path(filename).name}"
    if store_root is not None:
        dest = Path(store_root) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    now = _now()
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            "INSERT INTO documents(doc_id, matter_id, filename, doc_type,"
            " jurisdiction, sha256, size, path, ingest_status, created_by, created_at)"
            " VALUES(?,?,?,?,?,?,?,?, 'pending',?,?)",
            (doc_id, matter_id, filename, doc_type, jurisdiction, sha, len(body),
             str(rel), principal["user_id"], now))
        audit.append(con, matter_id=matter_id, actor=principal["username"],
                     action="document.uploaded", target=doc_id,
                     inputs_digest=f"{filename} {sha[:12]}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    row = con.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    return _doc_row(row)


def ingest_doc(con, principal: dict, matter_id: str, body: dict,
               store_root: Path | None = None) -> dict:
    """POST /matters/{mid}/documents/ingest {source_spec}: run the existing
    ingest pipeline over the source and mark every document of the matter
    ingested. Returns 202 + the run report."""
    authz.require(con, principal, WRITE, matter_id)
    source = (body or {}).get("source")
    if not source:
        # UI "Ingest documents" — no path given: the matter's own uploads.
        if store_root is None:
            raise authz.ServiceError(422, "validation_failed", "source required")
        n = con.execute("SELECT COUNT(*) FROM documents WHERE matter_id=?",
                        (matter_id,)).fetchone()[0]
        if not n:
            raise authz.ServiceError(422, "validation_failed",
                                     "no uploaded documents to ingest")
        source = str(Path(store_root) / "documents" / matter_id)
        if not Path(source).is_dir():
            raise authz.ServiceError(422, "validation_failed",
                                     "uploaded document files are missing on disk")
    report = ingest.ingest_source(matter_id, source)
    # UX-5: each upload's status from what the report says happened to ITS stored file
    # (ingest names sources by file name), never "ingested" for a file it skipped
    names = lambda v: [v] if isinstance(v, str) else list(v or [])  # noqa: E731
    done = {Path(n).name for n in names(report.get("ingested")) + names(report.get("skipped_by_resume"))}
    skipped = {s.split(":", 1)[0].strip() for s in names(report.get("skipped"))}
    con.execute("BEGIN IMMEDIATE")
    try:
        for d in con.execute("SELECT doc_id, path FROM documents WHERE matter_id=?",
                             (matter_id,)).fetchall():
            name = Path(d["path"]).name
            st = "ingested" if name in done else "skipped" if name in skipped else None
            if st:
                con.execute("UPDATE documents SET ingest_status=? WHERE doc_id=?", (st, d["doc_id"]))
        audit.append(con, matter_id=matter_id, actor=principal["username"],
                     action="documents.ingested", target=source[:200])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"ingest_run": report}


def list_docs(con, principal: dict, matter_id: str, *, limit: int = 50,
              cursor: int = 0) -> dict:
    authz.require(con, principal, authz.READ, matter_id)
    rows = con.execute(
        "SELECT * FROM documents WHERE matter_id=? ORDER BY created_at, doc_id",
        (matter_id,)).fetchall()
    total = len(rows)
    page = [_doc_row(r) for r in rows[cursor:cursor + limit]]
    next_cursor = cursor + limit if cursor + limit < total else None
    return {"items": page, "next_cursor": next_cursor}


def evidence(con, principal: dict, matter_id: str, *, q: str = "",
             limit: int = 50, cursor: int = 0) -> dict:
    from harness.lifecycle import dossier
    authz.require(con, principal, authz.READ, matter_id)
    rows = dossier.read(con, matter_id, "evidence")["events"]
    if q:
        rows = [r for r in rows if q.lower() in (r.get("label") or "").lower()]
    # UX-5: the upload this row records, by exact full SHA-256 of the file in the same
    # matter — the only identifier the register carries (no name or prefix matching)
    by_sha = {(d["sha256"] or "").lower(): d["doc_id"] for d in con.execute(
        "SELECT doc_id, sha256 FROM documents WHERE matter_id=? ORDER BY created_at DESC, doc_id DESC",
        (matter_id,))}                                    # newest first: the earliest upload wins
    rows = [{**r, "doc_id": by_sha.get((r.get("sha256") or "").lower())
             if len(r.get("sha256") or "") == 64 else None} for r in rows]
    nxt = cursor + limit if cursor + limit < len(rows) else None
    return {"items": rows[cursor:cursor + limit], "next_cursor": nxt}


def list_artifacts(con, principal: dict, matter_id: str, *, review_state: str = "",
                   limit: int = 50, cursor: int = 0) -> dict:
    authz.require(con, principal, authz.READ, matter_id)
    rows = [dict(r) for r in con.execute(
        "SELECT artifact_id, matter_id, execution_id, kind, title, review_state,"
        " created_at, updated_at FROM artifacts WHERE matter_id=?"
        " ORDER BY created_at, artifact_id", (matter_id,))
        if not review_state or r["review_state"] == review_state]
    nxt = cursor + limit if cursor + limit < len(rows) else None
    return {"items": rows[cursor:cursor + limit], "next_cursor": nxt}


def _artifact(con, principal, aid: str, perm: str) -> dict:
    row = con.execute("SELECT * FROM artifacts WHERE artifact_id=?", (aid,)).fetchone()
    if row is None:
        raise authz.not_found("artifact_not_found", f"artifact {aid!r} not found")
    authz.require(con, principal, perm, row["matter_id"])
    return dict(row)


def get_artifact(con, principal: dict, aid: str) -> dict:
    return _artifact(con, principal, aid, authz.READ)


def artifact_sources(con, principal: dict, aid: str, *, store_root: Path | None = None) -> dict:
    """GET /api/v1/artifacts/{aid}/sources (UX-5): every quotation in a deliverable run
    through the existing citation guard (moot.verify — byte containment against this
    matter's corpus), each tied to the uploaded document + passage index it was found in.
    doc_id/chunk are set only when the deciding corpus chunk came from an upload of this
    matter (the stored file name the ingest recorded); otherwise they stay null."""
    import re as _re

    from harness.moot.verify import MIN_QUOTE_WORDS, _QUOTE, _locate, _norm, load_chunks
    row = _artifact(con, principal, aid, authz.READ)
    db = Path(store_root or ".") / "corpus.sqlite3"
    chunks = load_chunks(row["matter_id"], db) if store_root is not None else []
    uploads = {Path(d["path"]).name: d for d in con.execute(
        "SELECT doc_id, filename, path FROM documents WHERE matter_id=?", (row["matter_id"],))}
    text = row["content"] or ""
    starts = [0] + [m.end() for m in _re.finditer(r"\n", text)]
    quotes = []
    for m in _QUOTE.finditer(text):
        span = _norm(m.group(1))
        if len(span.split()) < MIN_QUOTE_WORDS:
            continue                                   # the guard's own threshold
        hit, quotable = _locate(chunks, span)
        up = uploads.get(hit["source_name"]) if hit else None
        # chunk = the passage id GET /documents/{id}/chunks returns as `i` (the corpus rowid);
        # passage = its 1-based position in that document's list (same sha, rowid order)
        passage = ([c["rowid"] for c in chunks if c["sha256"] == hit["sha256"]].index(hit["rowid"]) + 1
                   if up else None)
        quotes.append({"quote": span, "line": sum(s <= m.start() for s in starts),
                       "verdict": "VERIFIED" if quotable else ("PRIVILEGED" if hit else "NOT_IN_CORPUS"),
                       "source_name": hit["source_name"] if hit else None,
                       "doc_id": up["doc_id"] if up else None, "filename": up["filename"] if up else None,
                       "chunk": hit["rowid"] if up else None, "passage": passage})
    return {"artifact_id": aid, "execution_id": row["execution_id"],
            "corpus_chunks": len(chunks), "quotes": quotes}


def review_artifact(con, principal: dict, aid: str, body: dict) -> dict:
    row = _artifact(con, principal, aid, "approval.decide")
    decision = (body or {}).get("decision")
    states = {"approve": "approved", "reject": "rejected",
              "request_changes": "changes_requested"}
    if decision not in states:
        raise authz.ServiceError(422, "validation_failed",
                                 "decision must be approve|reject|request_changes")
    note = (body or {}).get("note") or ""
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("UPDATE artifacts SET review_state=?, review_note=?, updated_at=?"
                    " WHERE artifact_id=?", (states[decision], note, _now(), aid))
        audit.append(con, matter_id=row["matter_id"], actor=principal["username"],
                     action="artifact.reviewed", target=aid,
                     inputs_digest=states[decision], outputs_digest=note[:500])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return get_artifact(con, principal, aid)


def delete_artifact(con, principal: dict, aid: str) -> None:
    row = _artifact(con, principal, aid, WRITE)
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("DELETE FROM artifacts WHERE artifact_id=?", (aid,))
        audit.append(con, matter_id=row["matter_id"], actor=principal["username"],
                     action="artifact.deleted", target=aid, inputs_digest=row["title"] or "")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def forget_retrieval(store_root: Path, matter_id: str, text: str | None = None) -> int:
    """Remove passages + vectors from search: one document's (by its extracted text) or,
    text=None, the whole matter's. Returns the passage-doc count removed."""
    from harness.corpus import CorpusStore, chunk_text
    root = Path(store_root)
    if not (root / "corpus.sqlite3").is_file():
        return 0
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None
    ids = CorpusStore(root / "corpus.sqlite3").forget(matter_id, sha)
    if (root / "vectors.sqlite3").is_file() and (ids or text is None):
        from harness.vectors import VectorStore
        VectorStore(root / "vectors.sqlite3").delete(
            matter_id, None if text is None else [t for d in ids for t in chunk_text(d, text)])
    return len(ids)


def delete_document(con, principal: dict, doc_id: str, *, store_root: Path | None = None) -> None:
    """Hard delete (user ruling 2026-11-13): the file, its row, and its passages/vectors so
    search stops surfacing it; the audit chain keeps a document.deleted entry."""
    from harness.ingest_generic import extract_text
    row = con.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if row is None:
        raise authz.not_found("document_not_found", f"document {doc_id!r} not found")
    authz.require(con, principal, WRITE, row["matter_id"])
    p = Path(store_root or ".") / row["path"]
    twin = con.execute("SELECT 1 FROM documents WHERE matter_id=? AND sha256=? AND doc_id<>?",
                       (row["matter_id"], row["sha256"], doc_id)).fetchone()
    # an identical upload still in the matter shares the passages: leave them searchable
    if store_root is not None and p.is_file() and twin is None:
        try:
            forget_retrieval(store_root, row["matter_id"], extract_text(p))
        except (TimeoutError, RuntimeError, UnicodeDecodeError):
            pass      # unreadable -> never ingested as text, so nothing indexed to remove
    if store_root is not None:
        p.unlink(missing_ok=True)
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
        audit.append(con, matter_id=row["matter_id"], actor=principal["username"],
                     action="document.deleted", target=doc_id,
                     inputs_digest=f"{row['filename']} {(row['sha256'] or '')[:12]}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def get_bytes(con, principal: dict, doc_id: str, *,
              store_root: Path | None = None) -> tuple[dict, bytes]:
    """GET /api/v1/documents/{doc_id} — authz via the parent matter (fails
    closed: no membership on the parent matter -> 404)."""
    row = con.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if row is None:
        raise authz.not_found("document_not_found", f"document {doc_id!r} not found")
    authz.require(con, principal, authz.READ, row["matter_id"])
    data = b""
    if store_root is not None:
        p = Path(store_root) / row["path"]
        if not p.is_file():   # UX-5: say so, never serve an empty body as the document
            raise authz.not_found("document_file_missing",
                                  f"document {doc_id!r} has no stored file")
        data = p.read_bytes()
    return _doc_row(row), data


def get_meta(con, principal: dict, doc_id: str) -> dict:
    """GET /api/v1/documents/{doc_id}/meta (UX-5) — the document row, same authz as the
    bytes (parent matter read; no membership -> 404), so a deep link needs no list page."""
    row = con.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if row is None:
        raise authz.not_found("document_not_found", f"document {doc_id!r} not found")
    authz.require(con, principal, authz.READ, row["matter_id"])
    return _doc_row(row)


def get_text(con, principal: dict, doc_id: str, *, store_root: Path | None = None) -> dict:
    """GET /api/v1/documents/{doc_id}/text (M13.4) — reading text for formats a browser
    cannot show (DOCX, HTML, ...) via the same killable parser chain ingest uses."""
    from harness.ingest_generic import extract_text
    doc, _ = get_bytes(con, principal, doc_id, store_root=store_root)   # authz + existence
    p = Path(store_root or ".") / doc["path"]
    if store_root is None or not p.is_file():
        raise authz.not_found("document_not_found", f"document {doc_id!r} has no stored file")
    try:
        return {"doc_id": doc_id, "text": extract_text(p)}
    except TimeoutError:
        raise authz.ServiceError(422, "unreadable_document",
                                 "reading the file took too long and was stopped") from None
    except (RuntimeError, UnicodeDecodeError):
        # UX-5: the parser's stderr/traceback is internal detail, never shown to a user
        raise authz.ServiceError(422, "unreadable_document",
                                 "the file is damaged or in a format the server cannot read") from None


def get_chunks(con, principal: dict, doc_id: str, *, store_root: Path | None = None) -> dict:
    """GET /api/v1/documents/{doc_id}/chunks (M13.5) — the passages retrieval sees, matched
    to the corpus by the same extracted text's sha256; [] when never corpus-ingested."""
    from harness.corpus import CorpusStore
    doc, _ = get_bytes(con, principal, doc_id, store_root=store_root)
    sha = hashlib.sha256(get_text(con, principal, doc_id, store_root=store_root)["text"]
                         .encode("utf-8")).hexdigest()
    db = Path(store_root) / "corpus.sqlite3"
    chunks = CorpusStore(db).doc_chunks(doc["matter_id"], sha) if db.is_file() else []
    return {"doc_id": doc_id, "chunks": chunks}
