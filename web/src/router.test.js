import { describe, expect, it } from "vitest";
import { href, parseRoute } from "./router.js";

describe("hash router", () => {
  it.each([
    ["", { name: "home", params: {} }],
    ["#/board", { name: "board", params: {} }],
    ["#/approvals", { name: "approvals", params: {} }],
    ["#/m/m-1/documents", { name: "workspace", params: { mid: "m-1", tab: "documents" } }],
    ["#/m/m-1", { name: "workspace", params: { mid: "m-1", tab: "overview" } }],
    ["#/case/m-1", { name: "case", params: { mid: "m-1", view: "home" } }],
    ["#/case/m-1/debrief", { name: "case", params: { mid: "m-1", view: "debrief" } }],
    ["#/runs/r-9", { name: "run", params: { rid: "r-9" } }],
    ["#/nope/x", { name: "notfound", params: {} }],
  ])("%s", (hash, want) => expect(parseRoute(hash)).toEqual(want));

  it("href round-trips and encodes ids", () => {
    expect(parseRoute(href("workspace", { mid: "a b", tab: "audit" })))
      .toEqual({ name: "workspace", params: { mid: "a b", tab: "audit" } });
  });
});
