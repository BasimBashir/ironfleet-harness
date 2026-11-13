# A — Collapsible run-drawer stages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each stage in the run drawer collapses; only the current stage is open by default; Expand all / Collapse all in the Stages header.

**Architecture:** Lift the stage `<ol>` out of `RunDrawer` into an exported, hook-free `StageList` so it renders under `renderToString` (the suite has no DOM). `RunDrawer` keeps the `force` state and the two buttons. Spec: `docs/superpowers/specs/2026-11-11-a-collapsible-drawer-stages-design.md`.

**Tech Stack:** React 19, vitest 5 (`renderToString`; no jsdom/testing-library installed, none added).

## Global Constraints
- No new dependencies. Native `<details>`/`<summary>`.
- Redirect stays gated by `canAct && t.state === "pending" && live` (05 §12: hidden, not disabled).
- User commits; no co-author trailer.

---

### Task 1: StageList with default-open current stage + force override

**Files:**
- Modify: `web/src/screens/RunPage.jsx:39-59` (stage list), add `currentTask` beside `parkedTask`
- Test: `web/src/swarm.test.jsx`

**Interfaces:**
- Produces: `currentTask(tasks, runState) -> task_id | null`;
  `StageList({ tasks, runState, byAgent, canAct, live, onRedirect, force })` where
  `force` is `null` or `{ open: boolean, n: number }` (`n` bumps per button press so a repeat press re-applies).

- [ ] **Step 1: Failing test** (append to `swarm.test.jsx`)

```jsx
describe("drawer stage list (A: collapsible stages)", () => {
  const list = (over = {}) => renderToString(<StageList tasks={plan(5, 5)} runState="executing" byAgent={{}}
    canAct live onRedirect={() => {}} force={null} {...over} />);
  const opens = (h) => (h.match(/<details open=""/g) || []).length;
  it("opens only the current stage: the parked approval stage, else the first unfinished", () => {
    expect(currentTask(plan(5, 5), "executing")).toBe("t5");
    expect(currentTask(plan(7), "waiting_human")).toBe("t6");
    expect(currentTask(plan(10), "completed")).toBe(null);
    expect(opens(list())).toBe(1);
    expect(list()).toContain('<details open=""><summary><b>assess</b>');
  });
  it("Expand all / Collapse all override the default", () => {
    expect(opens(list({ force: { open: true, n: 1 } }))).toBe(10);
    expect(opens(list({ force: { open: false, n: 2 } }))).toBe(0);
  });
  it("keeps finished output in the DOM and Redirect gated by matter.dispatch", () => {
    expect(list()).toContain("intake done");
    expect(list()).toContain(">Redirect<");
    expect(list({ canAct: false })).not.toContain(">Redirect<");
  });
});
```

- [ ] **Step 2:** `cd web && npx vitest run src/swarm.test.jsx` → FAIL (`StageList` not exported).
- [ ] **Step 3:** Implement `currentTask` + `StageList` (summary = key · agent · chip · total tokens; body = breakdown, result_summary, attempts, Redirect; `key={`${t.task_id}-${force?.n ?? 0}-${isCur}`}`, `open={force ? force.open : isCur}`), and in `RunDrawer` replace lines 39-59 with a `hdr` row holding the two buttons + `<StageList … />`.
- [ ] **Step 4:** `npx vitest run` → all pass.
- [ ] **Step 5:** Browser check on `#/runs/{rid}`; user commits.
