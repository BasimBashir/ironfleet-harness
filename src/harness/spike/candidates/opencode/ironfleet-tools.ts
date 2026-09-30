// IronFleet tool shim — S7c Module E mount for OpenCode, modelled on ironfleet-guard-s7c.ts.
//
// This file holds NO tool logic. For every `ported` row in data/module-e/tools.yaml it declares a
// `tool()` whose execute spawns the venv Python
//     <python> -m harness.module_e.dispatch <toolName> <argsJsonFile> <outFile>
// and returns stdout. Manifest lookup, the ported-status gate, the `module:fn` import and the JSON
// transport all live in src/harness/module_e/dispatch.py, where pytest reaches them. A JS
// re-implementation would not be a port and would break spike parity.
//
// FAILURE SURFACING (Task 7 obligation): a non-zero child exit returns the child's stderr as the
// tool result, prefixed so the model can tell a failed call from a real result. Nothing here
// converts a Python KeyError/TypeError into a silent empty string — the exception text reaches
// the model verbatim.
//
// Template note: this is a TEMPLATE (never executed directly). Module E Task 10's sync_mount
// renders it into <ws>/.opencode/plugins/ironfleet-tools.ts, substituting __SPIKE_WS__ /
// __PYTHON__ / __MANIFEST__ / __TOOLS__ (the manifest's ported {name, description} rows). There
// are no other placeholders, and this file must not gain one — the renderer substitutes exactly
// these four.
import { spawnSync } from "node:child_process"
import { readFileSync, writeFileSync, rmSync } from "node:fs"
import { join } from "node:path"
import { tool, type Plugin } from "@opencode-ai/plugin"

const WS = "__SPIKE_WS__"
const PYTHON = "__PYTHON__"
// The manifest is the single source of truth for what is callable, so the workspace names the
// copy that governs it — a mount cannot silently point at a different tool surface than the one
// its tools and guard whitelist were rendered from.
const MANIFEST = "__MANIFEST__"

// Rendered from ported_tools(load_manifest(tools.yaml)) by sync_mount — never hand-typed. The
// manifest is the single source of truth for what is callable, so the shim cannot advertise a
// tool the manifest does not declare (S7c spec §3.5).
const TOOLS: { name: string; description: string }[] = __TOOLS__

// SERIALIZED dispatch, same discipline as the guard: hooks and tool calls interleave during task
// delegation, and concurrent Python spawns were observed failing (status=null) where serialized
// calls succeed (2026-09-01).
let dispatchChain: Promise<unknown> = Promise.resolve()

function dispatchOnce(name: string, args: unknown): string {
  // FILE transport, same reason as the guard: Bun's spawnSync on Windows deadlocks once stdin
  // exceeds the pipe buffer (~64 KB; observed live 2026-09-01). Payload and result ride temp
  // files; only short argv (tool name + two paths) crosses the process boundary.
  const seq = Date.now() + "-" + Math.floor(Math.random() * 1e9)
  const inFile = join(WS, `tool-in-${seq}.json`)
  const outFile = join(WS, `tool-out-${seq}.json`)
  writeFileSync(inFile, JSON.stringify(args ?? {}), "utf8")
  try {
    const proc = spawnSync(PYTHON,
      ["-m", "harness.module_e.dispatch", MANIFEST, name, inFile, outFile], { timeout: 180_000 })
    if (proc.status !== 0)
      return `ironfleet-tools: ${name} FAILED (status=${proc.status} signal=${proc.signal} `
        + `error=${JSON.stringify(proc.error ?? null)})\n${proc.stderr}`
    return readFileSync(outFile, "utf8")
  } finally {
    for (const f of [inFile, outFile]) { try { rmSync(f) } catch { /* best effort */ } }
  }
}

// Every export must be a plugin function — opencode's loader treats each module export as one and
// throws on a non-function export, so TOOLS stays module-private.
export const IronFleetTools: Plugin = async () => ({
  tool: Object.fromEntries(TOOLS.map(({ name, description }) => [
    name,
    tool({
      description,
      // PASSTHROUGH args — the Python side owns the schema. `tool()` takes a z.ZodRawShape
      // (verified against opencode 1.18.25's packages/plugin/src/tool.ts), so `args` must be a
      // field map and a bare `z.record(z.unknown())` is not assignable; an EMPTY shape validates
      // any JSON object and puts no property list in the model-facing schema, which is the
      // per-tool passthrough this mount means.
      args: {},
      async execute(args) {
        const work = dispatchChain.then(() => dispatchOnce(name, args))
        dispatchChain = work.then(() => undefined, () => undefined)   // never break the chain
        return work
      },
    }),
  ])),
})
