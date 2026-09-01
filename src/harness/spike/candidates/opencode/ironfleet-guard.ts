// IronFleet grounding-guard port — S4 adopt-spike mount for OpenCode (SPIKE_PROTOCOL P0-5).
//
// This file contains NO guard logic: every check goes through guard_cli.py to the real
// portable guard (src/harness/spike/guard_port.py, OpenCodeHookAdapter). A JS
// re-implementation would not be a port of the guard and would break spike parity.
//
// Mount points (criterion (a) — guard fires on every tool-execution and model-output path):
//   "tool.execute.before"         — scans serialised tool ARGS; the block-decision surface
//   "tool.execute.after"          — annotates tool RESULT text  ([UNGROUNDED — not confirmed])
//   "experimental.text.complete"  — annotates MODEL OUTPUT text (EXPERIMENTAL hook in
//                                   opencode 1.18.25 — a stability seam, recorded in SEAM_COUNT)
//
// Template note: the driver (scripts/run_spike_opencode.py) syncs this file into the spike
// workspace, substituting __SPIKE_WS__ / __PYTHON__ / __GUARD_CLI__ with real paths.
// Per-case authorities: <ws>/allowed.json  {"allowed": [..], "block": bool} (annotate-only
// for parity runs; block=true demonstrates the deny decision on the tool path).
import { spawnSync } from "node:child_process"
import { readFileSync, writeFileSync, appendFileSync, rmSync } from "node:fs"
import { join } from "node:path"

const WS = "__SPIKE_WS__"
const PYTHON = "__PYTHON__"
const GUARD_CLI = "__GUARD_CLI__"

type GuardDecision = { decision: string; reason: string; output: string }

function authorities(): { allowed: string[]; block: boolean } {
  try {
    const raw = JSON.parse(readFileSync(join(WS, "allowed.json"), "utf8"))
    return { allowed: raw.allowed ?? [], block: !!raw.block }
  } catch {
    // Fail CLOSED: no readable authority list means nothing may pass unexamined.
    return { allowed: [], block: false }
  }
}

function guard(text: unknown, tag: string): GuardDecision {
  if (typeof text !== "string" || text.length === 0)
    return { decision: "approve", reason: "no text", output: typeof text === "string" ? text : "" }
  const { allowed, block } = authorities()
  // FILE transport: Bun's spawnSync on Windows deadlocks when stdin exceeds the pipe
  // buffer (~64 KB) — status=null, empty stderr, hook timeout (observed live with long
  // completions). Payload and result ride temp files instead; only short paths use argv.
  const seq = Date.now() + "-" + Math.floor(Math.random() * 1e9)
  const inFile = join(WS, `guard-in-${seq}.json`)
  const outFile = join(WS, `guard-out-${seq}.json`)
  writeFileSync(inFile, JSON.stringify({ output: text, allowed }), "utf8")
  try {
    const proc = spawnSync(PYTHON, [GUARD_CLI, inFile, outFile], { timeout: 60_000 })
    if (proc.status !== 0)
      throw new Error(`ironfleet-guard: guard_cli failed (${tag}) status=${proc.status} stderr=${proc.stderr}`)
    const res: GuardDecision = JSON.parse(readFileSync(outFile, "utf8"))
    appendFileSync(
      join(WS, "guard-log.jsonl"),
      JSON.stringify({ tag, decision: res.decision, reason: res.reason, block_armed: block }) + "\n",
    )
    return res
  } finally {
    for (const f of [inFile, outFile]) { try { rmSync(f) } catch { /* best effort */ } }
  }
}

const eventCounts = new Map<string, number>()

export const IronFleetGuard = async (_ctx: unknown) => {
  return {
    "tool.execute.before": async (input: { tool: string; sessionID: string; callID: string },
                                   output: { args: unknown }) => {
      const res = guard(JSON.stringify(output.args ?? {}), `tool.execute.before:${input.tool}`)
      if (authorities().block && res.decision === "block") throw new Error(res.reason)
    },
    "tool.execute.after": async (input: { tool: string; sessionID: string; callID: string },
                                  output: { title: string; output: string; metadata: unknown }) => {
      const res = guard(output.output, `tool.execute.after:${input.tool}`)
      output.output = res.output                     // annotation rides the result text
      if (authorities().block && res.decision === "block") throw new Error(res.reason)
    },
    "experimental.text.complete": async (_input: unknown, output: { text: string }) => {
      const res = guard(output.text, "text.complete")
      output.text = res.output                       // annotation rides the model output
    },
    event: async ({ event }: { event: { type: string } }) => {
      eventCounts.set(event.type, (eventCounts.get(event.type) ?? 0) + 1)
      if (event.type === "session.idle" || event.type === "session.error") {
        appendFileSync(
          join(WS, "guard-log.jsonl"),
          JSON.stringify({ tag: "event-summary", on: event.type,
                           events: Object.fromEntries(eventCounts) }) + "\n",
        )
      }
    },
  }
}
