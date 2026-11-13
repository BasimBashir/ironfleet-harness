import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { ApiError } from "./api.js";
import { parseRoute } from "./router.js";
import { sourceHref } from "./screens/RunPage.jsx";
import { DocView, DocViewer, DraftSources, EvidenceRow, VerifyChip, docHref, draftHref, hits, passageAt } from "./screens/Workspace.jsx";

// UX-5 (NEXT_STEPS §9B.5) — fixtures in the API's real shapes: a GET /matters/{mid}/documents row,
// GET /documents/{id}/chunks items {i, heading, text}, and an evidence register row
// (evidence_id, op, label, file, sha256, actor, ts — workflow/db.py).
const SHA = "a".repeat(64);
const DOC = { doc_id: "doc-1", matter_id: "m-1", filename: "lease.docx", doc_type: "contract", jurisdiction: "",
  sha256: SHA, size: 2048, ingest_status: "ingested", created_by: "rita", created_at: "2026-11-10T09:00:00Z" };
const PDF = { ...DOC, doc_id: "doc-2", filename: "brief.pdf" };
const TXT = { ...DOC, doc_id: "doc-3", filename: "notes.txt", ingest_status: "pending" };
const CHUNKS = [{ i: 7, heading: "Parties", text: "The landlord and the tenant." },
  { i: 9, heading: "", text: "Rent is due monthly. Late rent attracts interest." }];
const NO = { items: [], loaded: true, err: null };
const OK = { text: null, url: null, err: null };
const text = (h) => h.replace(/<!-- -->/g, "").replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/\s+/g, " ");
const view = (p) => renderToString(<DocView mid="m-1" doc={DOC} content={OK} passages={NO} {...p} />);

describe("viewer per format", () => {
  it("PDF opens in the browser's own viewer, with a download", () => {
    const h = view({ doc: PDF, content: { ...OK, url: "blob:x" } });
    expect(h).toContain('<iframe class="card" src="blob:x" title="brief.pdf (PDF viewer)"');
    expect(text(h)).toContain("Original PDF in your browser's viewer.");
    expect(h).toContain('download="brief.pdf"');
  });
  it("plain text shows as stored, highlighted for the query", () => {
    const h = view({ doc: TXT, content: { ...OK, text: "Late rent. late fee." }, q: "late" });
    expect(h).toContain("<mark>Late</mark> rent. <mark>late</mark> fee.");
    expect(text(h)).toContain("Plain-text file, shown as stored.");
    expect(text(h)).toContain("2 matches");
  });
  it("Office files are an extracted-text reading view, never claimed as faithful rendering", () => {
    const t = text(view({ content: { ...OK, url: "blob:y", text: "Clause 1" } }));
    expect(t).toContain("layout and formatting are not preserved");
    expect(t).toContain("Clause 1");
    expect(t).toContain("Download lease.docx");
  });
  it("header carries provenance the API returned and nothing it did not", () => {
    const t = text(view({}));
    expect(t).toContain("Type contract");
    expect(t).not.toContain("Jurisdiction");          // empty in the row → no field
    expect(t).toContain("upload by rita");
    expect(t).toContain("Document ID doc-1");
    expect(t).not.toMatch(/version|author/i);        // no version history or authorship exists in the API
  });
});

describe("unreadable and missing files", () => {
  it("an unreadable file says so and how to recover, without a second passages error", () => {
    const err = new ApiError(422, "unreadable_document", "parser timed out");
    const h = view({ content: { ...OK, url: "blob:z", err }, passages: { items: [], loaded: true, err } });
    const t = text(h);
    expect(h).toContain('role="alert"');
    expect(t).toContain("could not extract readable text from this file (parser timed out)");
    expect(t).toContain("Download the original");
    expect(t).not.toContain("Passages unavailable");
    expect(t).not.toContain("Reading view");
  });
  it("a missing stored file (404 document_file_missing) is explicit, with no empty viewer", () => {
    const err = new ApiError(404, "document_file_missing", "document 'doc-2' has no stored file");
    const h = view({ doc: PDF, content: { ...OK, err }, passages: { items: [], loaded: true, err } });
    expect(text(h)).not.toContain("Passages unavailable");
    expect(text(h)).toContain("stored file for this document is missing");
    expect(h).not.toContain("<iframe");
    expect(h).not.toContain("doc-find");
  });
  it("never-ingested and unindexed documents explain the empty passage list", () => {
    expect(text(view({ doc: TXT, content: { ...OK, text: "x" } }))).toContain("Not ingested — agents cannot retrieve passages");
    expect(text(view({ content: { ...OK, text: "x" } }))).toContain("No indexed passages match this file's current text");
    const skipped = text(view({ doc: { ...TXT, ingest_status: "skipped" }, content: { ...OK, text: "x" } }));
    expect(skipped).toContain("Skipped by ingest");
    expect(skipped).toContain("The last ingest skipped this file");
  });
});

describe("passage navigation", () => {
  it("rail lists every passage; the selected one is marked in rail and text", () => {
    const h = view({ content: { ...OK, text: "x" }, passages: { ...NO, items: CHUNKS }, sel: "9" });
    expect(h).toContain('aria-label="Passages"');
    expect(text(h)).toContain("2 passages — as agents retrieve them");
    expect(h).toContain('<li id="chunk-9" class="card passage" aria-current="true">');
    expect(h).toContain('<li id="chunk-7" class="card passage">');
    expect(h).toMatch(/<button type="button" aria-current="true">Passage 2/);
    expect(text(h)).not.toContain("showing the whole document");
  });
  it("query highlighting marks matches inside passages and counts them per passage", () => {
    const h = view({ passages: { ...NO, items: CHUNKS }, q: "rent" });
    expect(h).toContain("<mark>Rent</mark> is due monthly. Late <mark>rent</mark>");
    expect(text(h)).toContain("2 matches");
    expect(h).toMatch(/Passage 2<span class="pill">2<span class="sr-only"> matches/);
  });
  it("a deep link to a passage that is not there opens the document with a fallback note", () => {
    for (const sel of ["8", "abc", "-1"]) {   // ids are corpus rowids: 8 is not this document's
      const t = text(view({ passages: { ...NO, items: CHUNKS }, sel }));
      expect(t).toContain(`The linked passage (ref ${sel}) is not one of this document's indexed passages — it may have been re-ingested — showing the whole document instead.`);
    }
    const err = new ApiError(500, "internal", "boom");
    expect(text(view({ passages: { items: [], loaded: true, err }, sel: "1" })))
      .toContain("The linked passage (ref 1) cannot be shown because this document's passages could not be loaded");
  });
  it("passageAt and hits take identifiers literally", () => {
    expect(passageAt(CHUNKS, "9")).toBe(CHUNKS[1]);
    expect(passageAt(CHUNKS, 7)).toBe(CHUNKS[0]);
    expect([passageAt(CHUNKS, "9.0"), passageAt(CHUNKS, ""), passageAt(CHUNKS, null), passageAt(CHUNKS, "1")]).toEqual([null, null, null, null]);
    expect(hits("a.b a.b", "a.b")).toBe(2);
    expect(hits("x", " ")).toBe(0);
  });
});

describe("authorization and matter isolation", () => {
  const meta = (data, error = null) => ({ data, loading: false, error });
  it("a document of another matter is 'not available' here, with nothing about it shown", () => {
    // GET /documents/{id}/meta succeeded (the user may read matter m-2) but this is m-1's workspace
    const h = renderToString(<DocViewer mid="m-1" docId="doc-9" meta={meta({ ...DOC, doc_id: "doc-9", matter_id: "m-2", filename: "other.pdf" })} />);
    expect(text(h)).toContain("Document not available");
    expect(text(h)).toContain("It is not in this matter, it was deleted, or you cannot read it.");
    expect(h).not.toContain("doc-9");
    expect(h).not.toContain("other.pdf");
  });
  it("a denied or unknown document (404) reads exactly like one from another matter", () => {
    const h = renderToString(<DocViewer mid="m-1" docId="doc-x" meta={meta(undefined, new ApiError(404, "document_not_found", "document 'doc-x' not found"))} />);
    expect(text(h)).toContain("Document not available");
    expect(h).not.toContain("doc-x");
  });
  it("any other failure is an error with retry, not an empty viewer", () => {
    const h = renderToString(<DocViewer mid="m-1" docId="doc-1" meta={meta(undefined, new ApiError(500, "internal", "store offline"))} />);
    expect(text(h)).toContain("store offline");
    expect(h).not.toContain("<iframe");
  });
  it("a document of this matter opens the viewer", () => {
    expect(text(renderToString(<DocViewer mid="m-1" docId="doc-1" meta={meta(DOC)} />))).toContain("lease.docx");
  });
});

describe("evidence → source", () => {
  const row = { evidence_id: "ev-1", op: "add", label: "E1", file: "lease.docx", sha256: SHA, actor: "hunter", ts: "2026-11-10T10:00:00Z" };
  it("a server-resolved doc_id renders View source; without one the file stays plain text", () => {
    const ok = renderToString(<table><tbody><EvidenceRow mid="m-1" r={{ ...row, doc_id: "doc-1" }} /></tbody></table>);
    expect(ok).toContain(`href="${docHref("m-1", "doc-1")}"`);
    expect(text(ok)).toContain("View source · lease.docx");
    const bad = renderToString(<table><tbody><EvidenceRow mid="m-1" r={{ ...row, doc_id: null }} /></tbody></table>);
    expect(bad).not.toContain("href=");
    expect(text(bad)).toContain("lease.docx · no upload in this matter has this file's SHA-256");
  });
  it("verification shows exactly what was supplied; absence is never 'unverified' or 'verified'", () => {
    const chip = (v) => text(renderToString(<VerifyChip v={v} />));
    expect([true, "VERIFIED"].map(chip).every((t) => t.includes("Verified quote"))).toBe(true);
    expect(chip(false)).toContain("Unverified");
    expect(chip("NOT_IN_CORPUS")).toContain("Not in corpus");
    expect(chip("MISMATCH")).toContain("Mismatch");
    expect(chip("PRIVILEGED")).toContain("Privileged source");
    for (const v of [undefined, null, "yes", 1]) expect(chip(v)).toContain("Not supplied");
  });
});

// GET /artifacts/{aid}/sources — the citation guard's verdicts tied to upload + passage by the server
describe("draft sources", () => {
  const src = (data) => renderToString(<DraftSources mid="m-1" s={{ data, loading: false, error: null }} />);
  const Q = (o) => ({ quote: "the tenant shall pay rent monthly in advance", line: 3, verdict: "VERIFIED", source_name: null, doc_id: null, filename: null, chunk: null, ...o });
  it("a resolved quote links to the exact document and passage", () => {
    const h = src({ corpus_chunks: 4, quotes: [Q({ source_name: "doc-1-lease.docx", doc_id: "doc-1", filename: "lease.docx", chunk: 41, passage: 2 })] });
    expect(h).toContain(`href="${docHref("m-1", "doc-1", 41)}"`);
    expect(text(h)).toContain("View source · lease.docx, passage 2");
    expect(text(h)).toContain("Verified quote");
  });
  it("a quote found only in a law source, or nowhere, gets no link", () => {
    const h = src({ corpus_chunks: 4, quotes: [Q({ source_name: "Companies Act 1993, s 289" }), Q({ verdict: "NOT_IN_CORPUS" })] });
    expect(h).not.toContain("href=");
    expect(text(h)).toContain("Found in Companies Act 1993, s 289 — a law source, not an uploaded document.");
    expect(text(h)).toContain("Not in corpus");
  });
  it("with nothing ingested, no verdict is claimed", () => {
    const t = text(src({ corpus_chunks: 0, quotes: [Q({ verdict: "NOT_IN_CORPUS" })] }));
    expect(t).toContain("these quotations could not be checked");
    expect(t).toContain("Not supplied");
    expect(t).not.toContain("Not in corpus");
    expect(text(src({ corpus_chunks: 3, quotes: [] }))).toContain("quotes no passage of six or more words");
  });
});

describe("chat citations", () => {
  it("validated refs map to their screens; a stage or unknown kind stays a label", () => {
    expect(sourceHref("m-1", "document:doc-1")).toBe(docHref("m-1", "doc-1"));
    expect(sourceHref("m-1", "deliverable:a-1")).toBe(draftHref("m-1", "a-1"));
    expect(sourceHref("m-1", "run:exe-1")).toBe("#/runs/exe-1");
    expect(sourceHref("m-1", "approval:ap-1")).toBe("#/m/m-1/decisions");
    expect(sourceHref("m-1", "deadline:dl-1")).toBe("#/m/m-1/deadlines");
    expect([sourceHref("m-1", "stage:intake"), sourceHref("m-1", "bogus"), sourceHref(null, "document:doc-1")]).toEqual([null, null, null]);
  });
});

describe("deep links and back navigation", () => {
  it("document and passage links are real hash routes (a history entry, so Back returns to the origin)", () => {
    expect(docHref("m 1", "doc-1", 3)).toBe("#/m/m%201/documents/doc-1/3");
    expect(parseRoute(docHref("m 1", "doc-1", 3))).toEqual({ name: "workspace", params: { mid: "m 1", tab: "documents", item: "doc-1", part: "3" } });
    expect(parseRoute(docHref("m-1", "doc-1"))).toEqual({ name: "workspace", params: { mid: "m-1", tab: "documents", item: "doc-1" } });
    expect(parseRoute(draftHref("m-1", "a-1"))).toEqual({ name: "workspace", params: { mid: "m-1", tab: "drafts", item: "a-1" } });
  });
  it("the viewer links back to this matter's document list", () => {
    expect(view({})).toContain('href="#/m/m-1/documents"');
  });
});
