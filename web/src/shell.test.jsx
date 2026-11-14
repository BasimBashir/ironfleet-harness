import { describe, expect, it } from "vitest";
import { pageTitle } from "./App.jsx";
import { parseRoute } from "./router.js";

// UX-6: every view names itself in the tab/window title (WCAG 2.4.2)
describe("pageTitle", () => {
  it.each([
    ["", "Matters — IronFleet"],
    ["#/board", "Matters — IronFleet"],
    ["#/approvals", "Approvals — IronFleet"],
    ["#/m/m-1", "Overview · m-1 — IronFleet"],
    ["#/m/m-1/workplan", "Work plan · m-1 — IronFleet"],
    ["#/runs/ex-9/t2", "Run ex-9 — IronFleet"],
    ["#/case/m-2/dates", "Dates · m-2 — IronFleet"],
    ["#/case/m-2", "Case home · m-2 — IronFleet"],
    ["#/nowhere", "Page not found — IronFleet"],
  ])("%s", (hash, want) => expect(pageTitle(parseRoute(hash))).toBe(want));
});
