import { describe, expect, it } from "vitest";
import { ApiError, request } from "./api.js";

const json = (status, body) => new Response(JSON.stringify(body), {
  status, headers: { "content-type": "application/json" } });

describe("api request", () => {
  it("GET sends the bearer token and no Idempotency-Key", async () => {
    let seen;
    const fetchImpl = async (url, init) => { seen = { url, init }; return json(200, { ok: 1 }); };
    const r = await request("GET", "/matters", undefined, { fetchImpl, token: () => "t" });
    expect(seen.url).toBe("/api/v1/matters");
    expect(seen.init.headers.Authorization).toBe("Bearer t");
    expect(seen.init.headers["Idempotency-Key"]).toBeUndefined();
    expect(r).toEqual({ status: 200, data: { ok: 1 }, pending: false });
  });

  it("POST carries a fresh Idempotency-Key and a JSON body", async () => {
    const keys = [];
    const fetchImpl = async (url, init) => {
      keys.push(init.headers["Idempotency-Key"]);
      expect(JSON.parse(init.body)).toEqual({ note: "x" });
      return json(202, { state: "pending" });
    };
    const a = await request("POST", "/x", { note: "x" }, { fetchImpl, token: () => "t" });
    await request("POST", "/x", { note: "x" }, { fetchImpl, token: () => "t" });
    expect(keys[0]).toBeTruthy();
    expect(keys[0]).not.toBe(keys[1]);
    expect(a.pending).toBe(true);           // 202 = accepted, never shown as success
  });

  it("an error envelope becomes an ApiError with the stable code and message", async () => {
    const fetchImpl = async () => json(409, { error: { code: "invalid_transition",
      message: "cannot go from DRAFT to COURT", details: {}, trace_id: "x" } });
    const err = await request("POST", "/x", {}, { fetchImpl, token: () => "t" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect([err.status, err.code, err.message]).toEqual(
      [409, "invalid_transition", "cannot go from DRAFT to COURT"]);
  });

  it("a non-envelope failure still yields a readable ApiError", async () => {
    const fetchImpl = async () => new Response("boom", { status: 502 });
    const err = await request("GET", "/x", undefined, { fetchImpl, token: () => "t" }).catch((e) => e);
    expect([err.status, err.code]).toEqual([502, "http_error"]);
  });
});
