# A — Collapsible run-drawer stages (design)

Sub-project A of the 2026-11-11 nine-ask request (order A→F ruled by the owner).
Implements the "collapse-completed" intent of `docs/enterprise/05-product-and-ux-specification.md` §105
for the drawer stage list.

## Goal
The run drawer's stage list prints every stage's full output, so long runs bury the
current stage. Make each stage collapsible; open only the one that needs attention.

## Scope
One component: `RunDrawer` in `web/src/screens/RunPage.jsx` (Stages list). It renders in
the Workspace side drawer and on the full `#/runs/{rid}` page — both get the change.
Out: swarm lanes, persisting open state across reloads, animation.

## Design
- Each stage `<li>` wraps its content in a native `<details>`.
  - `<summary>`: `key · agent · status chip · total tokens`.
  - Body: in/out/think breakdown, `result_summary`, attempt count, Redirect button.
- Open by default: the **current** stage only — the parked approval stage
  (existing `parkedTask()`), else the first non-completed stage. If every stage is
  completed, none is open.
- Expand all / Collapse all: one state value `force` (`null` | `true` | `false`).
  Row `key` = `${task_id}-${force}-${isCurrent}`, `open = force ?? isCurrent`, so a row
  remounts (and takes the new default) only when a button is pressed or it becomes /
  stops being current. Manual toggles survive polling re-renders.
- Accessibility: native details/summary gives keyboard + screen-reader disclosure.
- Read-only users: unchanged — Redirect stays hidden for them (accept_m10 asserts
  `count == 0`, unaffected by collapse).

## Testing
One vitest case: completed stage closed, current stage open, Collapse all closes all,
Expand all opens all. Existing suites: no assertion depends on drawer stage output
being visible (checked: `swarm.test.jsx`, `scripts/accept_m10.py`).
