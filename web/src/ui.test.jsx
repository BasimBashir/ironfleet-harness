import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { AGENT_STATES, Btn, MATTER_STATES, StatusChip, allowed, fmtTokens } from "./ui.jsx";

describe("StatusChip: colour + icon + word, never colour alone (05 §0)", () => {
  it.each(Object.entries(MATTER_STATES))("matter %s", (state, [cls, icon, word]) => {
    const html = renderToString(<StatusChip state={state} />);
    expect(html).toContain(`chip--${cls}`);
    expect(html).toContain(`data-icon="${icon}"`);
    expect(html).toContain(word);
  });

  it.each(Object.entries(AGENT_STATES))("agent %s", (state, [cls, icon, word]) => {
    const html = renderToString(<StatusChip kind="agent" state={state} />);
    expect(html).toContain(`chip--${cls}`);
    expect(html).toContain(`data-icon="${icon}"`);
    expect(html).toContain(word);
  });

  it("covers the nine matter states (02 §4) and the agent states (02 §5)", () => {
    expect(Object.keys(MATTER_STATES)).toHaveLength(9);
    expect(Object.keys(AGENT_STATES).length).toBeGreaterThanOrEqual(9);
  });

  it("an unknown state still shows a word, never a blank chip", () => {
    expect(renderToString(<StatusChip state="mystery_state" />)).toContain("mystery state");
  });
});

describe("permission affordances (05 §12)", () => {
  const perms = ["matter.read"];
  it("approval.decide missing: disabled WITH the reason, still in the tab order", () => {
    const html = renderToString(
      <Btn why={allowed(perms, "approval.decide") ? "" : "requires approval.decide"}>Approve</Btn>);
    expect(html).toContain('aria-disabled="true"');
    expect(html).toContain("requires approval.decide");
    expect(html).not.toContain("disabled=\"\"");
  });

  it("allowed: an ordinary button with no reason line", () => {
    const html = renderToString(<Btn why="">Approve</Btn>);
    expect(html).not.toContain("aria-disabled");
    expect(html).not.toContain("btn__why");
  });

  it("admin's wildcard and explicit grants both count", () => {
    expect(allowed(["approval.decide"], "approval.decide")).toBe(true);
    expect(allowed(["*"], "audit.read")).toBe(true);
    expect(allowed([], "audit.read")).toBe(false);
  });
});

describe("token formatting", () => {
  it.each([[0, "0"], [999, "999"], [132400, "132.4k"], [1500000, "1.50M"]])("%i", (n, s) =>
    expect(fmtTokens(n)).toBe(s));
});
