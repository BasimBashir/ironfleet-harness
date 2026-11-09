import { describe, expect, it } from "vitest";
import { createParser, subscribe } from "./sse.js";

const collect = () => {
  const got = [];
  return { got, feed: createParser((e) => got.push(e)) };
};

describe("SSE frame parser", () => {
  it("parses id/event/data frames like the API's frame()", () => {
    const { got, feed } = collect();
    feed('id: 7\nevent: task.running\ndata: {"a": 1}\n\n');
    expect(got).toEqual([{ id: "7", event: "task.running", data: '{"a": 1}' }]);
  });

  it("joins multi-line data and survives frames split across chunks", () => {
    const { got, feed } = collect();
    feed("id: 1\nevent: x\nda");
    feed("ta: line1\ndata: line2\r");
    feed("\n\n");
    expect(got).toEqual([{ id: "1", event: "x", data: "line1\nline2" }]);
  });

  it("ignores heartbeat comments and keeps the last id across events", () => {
    const { got, feed } = collect();
    feed(": hb\n\nid: 3\nevent: a\ndata: 1\n\n: hb\n\nevent: b\ndata: 2\n\n");
    expect(got.map((e) => [e.id, e.event])).toEqual([["3", "a"], ["3", "b"]]);
  });
});

describe("subscribe", () => {
  const stream = (text) => new Response(text, { status: 200 });

  it("sends Bearer + Last-Event-ID on reconnect, never the token in the URL", async () => {
    const calls = [];
    const events = [];
    const statuses = [];
    let n = 0;
    const fetchImpl = async (url, init) => {
      calls.push({ url, headers: init.headers });
      n += 1;
      if (n === 1) return stream('id: 41\nevent: a\ndata: {"k": 1}\n\n');
      if (n === 2) return stream('id: 42\nevent: b\ndata: {"k": 2}\n\n');
      return new Promise(() => {});
    };
    const stop = subscribe(["board"], (e) => events.push(e),
      { fetchImpl, token: () => "tok", retryMs: 1, onStatus: (s) => statuses.push(s) });
    await new Promise((r) => setTimeout(r, 30));
    stop();
    expect(calls[0].url).toBe("/api/v1/events?channels=board");
    expect(calls[0].url).not.toContain("tok");
    expect(calls[0].headers.Authorization).toBe("Bearer tok");
    expect(calls[0].headers["Last-Event-ID"]).toBeUndefined();
    expect(calls[1].headers["Last-Event-ID"]).toBe("41");
    expect(events.map((e) => e.data.k)).toEqual([1, 2]);
    expect(statuses).toContain("reconnecting");
  });
});
