import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { SettingsView } from "./screens/Settings.jsx";

// M13.7 — model settings admin; same rules as Users: without user.admin the controls
// are hidden but the reason stays visible, and a stored key is never echoed back.
const data = {
  providers: [
    { name: "ollama-local", base_url: "http://127.0.1:11434/v1", model: "thomson1-chat:latest",
      engine: "ollama", kind: "chat", tier: "local", context_window: 32768, has_key: false },
    { name: "nvidia-nim", base_url: "https://integrate.api.nvidia.com/v1", model: "step-5",
      engine: "cloud", kind: "chat", tier: "cloud", context_window: 128000, has_key: true },
  ],
  stages: [
    { task_class: "drafting", local_only: ["ollama-local", "nvidia-nim"],
      local_preferred: ["ollama-local", "nvidia-nim"], cloud_permitted: ["nvidia-nim", "ollama-local"], assign: "nvidia-nim" },
    { task_class: "embedding", local_only: ["ollama-embed"], local_preferred: ["ollama-embed"],
      cloud_permitted: ["ollama-embed"], assign: null },
  ],
};
const st = { busy: false, pending: false, error: null };
const v = (over = {}) => renderToString(<SettingsView data={data} canAdmin st={st} tested={{}} onSave={() => {}} onTest={() => {}} onAssign={() => {}} {...over} />);

describe("SettingsView", () => {
  it("lists providers with tier, write-only key placeholder, Save and Test", () => {
    const h = v();
    expect(h).toContain("ollama-local");
    expect(h).toContain("thomson1-chat:latest");
    expect(h).toContain("nvidia-nim");
    expect(h).toContain("key set");
    expect(h).toContain("replace key");
    expect(h).toContain(">Test<");
    expect(h).toContain(">Save<");
    expect(h).toContain('aria-label="API key for ollama-local"');
  });
  it("shows per-stage assignment with auto + candidates", () => {
    const h = v();
    expect(h).toContain('aria-label="Assign for drafting"');
    expect(h).toMatch(/<option value="nvidia-nim" selected="">nvidia-nim · step-5<\/option>/);
    expect(h).toContain(">auto<");
    expect(h).toContain("ollama-embed");
  });
  it("offers every provider to every stage, but no cloud one to a local-only stage", () => {
    const d = { ...data, stages: [...data.stages, { ...data.stages[1], task_class: "rerank", local_only_task: true }] };
    const h = v({ data: d });
    const opts = (tc) => h.split(`aria-label="Assign for ${tc}"`)[1].split("</select>")[0];
    expect(opts("embedding")).toContain('value="nvidia-nim"');   // not in its YAML list, still offered
    expect(opts("rerank")).toContain('value="ollama-local"');
    expect(opts("rerank")).not.toContain('value="nvidia-nim"');
  });
  it("offers Delete and a checkbox only on providers the admin added", () => {
    const d = { ...data, providers: [...data.providers, { ...data.providers[1], name: "my-groq", custom: true }] };
    const h = v({ data: d });
    expect(h).toContain('aria-label="Select my-groq"');
    expect(h).not.toContain('aria-label="Select nvidia-nim"');
    expect(h.match(/>Delete</g)).toHaveLength(1);
  });
  it("has a + Add provider button", () => {
    expect(v()).toContain("+ Add provider");
  });
  it("never echoes a stored key", () => {
    expect(v()).not.toContain("sk-");
  });
  it("without user.admin shows a lock row, no controls", () => {
    const h = v({ canAdmin: false, data: undefined });
    expect(h).toContain("requires the user.admin permission");
    for (const w of [">Test<", ">Save<", "<select"]) expect(h).not.toContain(w);
  });
  it("shows the probe verdict", () => {
    expect(v({ tested: { "ollama-local": "reachable · full · " } })).toContain("reachable · full · ");
  });
});
