import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { MetricsView } from "./screens/Oversight.jsx";
import { AuditView, highlight, viewMode } from "./screens/Workspace.jsx";

// M13.5 — retrieved words marked in the passage view, regex chars taken literally
describe("highlight", () => {
  it("marks every case-insensitive match and nothing for an empty query", () => {
    expect(renderToString(<p>{highlight("Cat sat; a cat.", "cat")}</p>)).toBe("<p><mark>Cat</mark> sat; a <mark>cat</mark>.</p>");
    expect(renderToString(<p>{highlight("s 7(1)", "7(1)")}</p>)).toBe("<p>s <mark>7(1)</mark></p>");
    expect(highlight("x", "  ")).toEqual(["x"]);
  });
});

// M13.4 — which viewer a document gets
describe("viewMode", () => {
  it("text inline, PDF native, the rest server-extracted", () => {
    expect(["a.TXT", "b.md", "c.csv", "d.json"].map(viewMode)).toEqual(["text", "text", "text", "text"]);
    expect(viewMode("brief.PDF")).toBe("pdf");
    expect(["e.docx", "f.html", "g.doc", "noext"].map(viewMode)).toEqual(["extracted", "extracted", "extracted", "extracted"]);
  });
});

// M13.3 — admin oversight: firm-wide metrics + audit across every matter
// as GET /metrics returns it (service/usage.py metrics())
const m = { dispatches: { total: 7, errors: 1, by_engine: { local: 5, cloud: 2 } },
  tasks: { pending: 3, running: 1 }, executions: { done: 4 },
  latency: [{ provider: "ollama", model: "thomson1-chat", n: 5, p50_ms: 120, p95_ms: 480 }] };
const rows = [{ audit_id: "a1", ts: "2026-11-11T00:00:00Z", matter_id: "m-9", actor: "rita",
  action: "doc.upload", target: "d1", hash: "abcdef0123456789" }];

describe("MetricsView", () => {
  it("renders totals, engine split, tasks and per-model latency", () => {
    const h = renderToString(<MetricsView m={m} />).replaceAll("<!-- -->", "");
    expect(h).toContain("7 (1 errors)");
    expect(h).toContain("local: 5 · cloud: 2");
    expect(h).toContain("3 pending · 1 running");
    expect(h).toContain("done: 4");
    expect(h).toContain("thomson1-chat");
    expect(h).toContain(">480<");
  });
  it("copes with no dispatches yet", () => {
    const h = renderToString(<MetricsView m={{ ...m, dispatches: { total: 0, errors: 0, by_engine: {} },
      executions: {}, latency: [] }} />);
    expect(h).toContain("none");
  });
});

describe("AuditView firm-wide", () => {
  it("adds a Matter column and Load more only in the all-matters view", () => {
    const all = renderToString(<AuditView chain={{ ok: true }} items={rows} allMatters onMore={() => {}} />);
    expect(all).toContain(">Matter<");
    expect(all).toContain(">m-9<");
    expect(all).toContain(">Load more<");
    const one = renderToString(<AuditView chain={{ ok: true }} items={rows} />);
    expect(one).not.toContain(">Matter<");
    expect(one).not.toContain("Load more");
  });
});
