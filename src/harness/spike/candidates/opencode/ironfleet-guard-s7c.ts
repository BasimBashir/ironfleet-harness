// IronFleet grounding-guard port — S7c Module E mount for OpenCode, generalized from the
// S4 adopt-spike mount (SPIKE_PROTOCOL P0-5).
//
// This file contains NO guard logic: every check goes through guard_cli.py to the real
// portable guard (src/harness/spike/guard_port.py, OpenCodeHookAdapter). A JS
// re-implementation would not be a port of the guard and would break spike parity.
//
// Mount points (criterion (a) — guard fires on every tool-execution and model-output path):
//   "tool.execute.before"         — scans serialised tool ARGS; the block-decision surface
//   "tool.execute.after"          — DETECTS + BLOCKS on EVERY tool; annotates tool RESULT text
//                                   ([UNGROUNDED — not confirmed]) on whitelisted paths only
//   "experimental.text.complete"  — annotates MODEL OUTPUT text (EXPERIMENTAL hook in
//                                   opencode 1.18.25 — a stability seam, recorded in SEAM_COUNT)
//
// ENVELOPE-AWARE (M0 costed hazard 2): the spike's tool.execute.after mutated output.output
// unconditionally, and that blanket mutation corrupted a built-in tool's structured JSON
// envelope, killing a session with SchemaError (observed live). Detection and blocking still
// run on EVERY tool — a block never mutates content, so it is envelope-safe — but ANNOTATION
// mutates only whitelisted free-text paths: the custom tools (by name, from tools.yaml) and
// `task`, whose result IS a subagent's prose. An unknown tool is detected and blocked but
// never has its bytes rewritten — the fail-safe direction.
//
// Template note: this is a TEMPLATE (never executed directly). The driver is Module E Task 9's
// sync_mount — not the spike's run_spike_opencode.py — which renders it into
// <ws>/.opencode/plugins/ironfleet-guard.ts, substituting __SPIKE_WS__ / __PYTHON__ /
// __GUARD_CLI__ / __ANNOTATE__ with real paths and the whitelisted tool names.
// Per-case authorities: <ws>/allowed.json  {"allowed": [..], "block": bool} (annotate-only
// for parity runs; block=true demonstrates the deny decision on the tool path).
import { spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import { readFileSync, writeFileSync, appendFileSync, rmSync } from "node:fs"
import { join } from "node:path"

const WS = "__SPIKE_WS__"
const PYTHON = "__PYTHON__"
const GUARD_CLI = "__GUARD_CLI__"
const ANNOTATE = new Set<string>(__ANNOTATE__)

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

// R1 D6 transport (2026-10-14): the verbatim-quote referee needs the turn's corpus
// authorities. tool.execute.after captures a corpus tool's JSON envelope "authorities"
// into <ws>/passages.json; every guard payload then carries them as allowed_passages.
// MISSING file = no corpus this session (referee skipped — the pre-R1 behaviour every
// existing driver is pinned to); PRESENT file = the referee's allowance (an EMPTY file
// plus any quotation = block, the D6 contract). This file still holds NO guard logic:
// capture and transport only — guard_cli decides.
function passagesPath(): string { return join(WS, "passages.json") }

function loadPassages(): string[] | null {
  try {
    const raw = JSON.parse(readFileSync(passagesPath(), "utf8"))
    return Array.isArray(raw) ? raw.map(String) : []
  } catch {
    return null
  }
}

function captureAuthorities(outputText: unknown): void {
  if (typeof outputText !== "string" || outputText.length === 0) return
  try {
    const auth = JSON.parse(outputText)?.authorities
    if (!Array.isArray(auth) || auth.length === 0) return
    const merged = [...(loadPassages() ?? []),
                    ...auth.map((a) => String(a).slice(0, 4000))].slice(-64)
    writeFileSync(passagesPath(), JSON.stringify(merged), "utf8")
  } catch { /* a result that is not a corpus envelope transports nothing */ }
}

// Guard calls are SERIALIZED: during task delegation the primary and subagent streams
// interleave and hooks can fire concurrently — concurrent python spawns were observed
// failing (status=null) where serialized calls succeed (2026-09-01).
let guardChain: Promise<unknown> = Promise.resolve()

function guardOnce(text: string, allowed: string[], tag: string): GuardDecision {
  // FILE transport: Bun's spawnSync on Windows deadlocks when stdin exceeds the pipe
  // buffer (~64 KB) — status=null, empty stderr, hook timeout (observed live with long
  // completions). Payload and result ride temp files instead; only short paths use argv.
  const seq = Date.now() + "-" + Math.floor(Math.random() * 1e9)
  const inFile = join(WS, `guard-in-${seq}.json`)
  const outFile = join(WS, `guard-out-${seq}.json`)
  const passages = loadPassages()
  const payload = passages === null
    ? { output: text, allowed }
    : { output: text, allowed, allowed_passages: passages }
  writeFileSync(inFile, JSON.stringify(payload), "utf8")
  try {
    const proc = spawnSync(PYTHON, [GUARD_CLI, inFile, outFile], { timeout: 60_000 })
    if (proc.status !== 0)
      throw new Error(`ironfleet-guard: guard_cli failed (${tag}) status=${proc.status} `
        + `signal=${proc.signal} error=${JSON.stringify(proc.error ?? null)} `
        + `stderr=${proc.stderr}`)
    return JSON.parse(readFileSync(outFile, "utf8"))
  } finally {
    for (const f of [inFile, outFile]) { try { rmSync(f) } catch { /* best effort */ } }
  }
}

// GUARD DECISION LOG (S7c spec §3.3: "<ws>/guard-log.jsonl — JSONL: hook, tool, decision,
// reason"; acceptance check 2 asserts against it). One line per hook call, written inside the
// serialized chain so lines are ordered and never interleaved. sha256_16 identifies the text
// EXAMINED (pre-annotation), which is what lets the acceptance driver prove the 1:1
// correspondence between the assistant completions in a session transcript and the
// text.complete decisions recorded here — without a per-decision line this log carries only
// retries and event summaries, and check 2 has nothing to assert. Text itself is NOT logged:
// it already lives in the transcript, and the log stays small enough to read whole.
function logDecision(d: GuardDecision, tag: string, text: string, authorities: number): GuardDecision {
  appendFileSync(join(WS, "guard-log.jsonl"), JSON.stringify({
    tag, decision: d.decision, reason: d.reason.slice(0, 200), chars: text.length,
    sha256_16: createHash("sha256").update(text).digest("hex").slice(0, 16),
    // The ANNOTATED text is what actually leaves the hook into the session, and the transcript
    // records that — so coverage matches on sha256_out, and sha256_16 (what was examined)
    // doubles as the annotation detector (annotated = the two digests differ).
    sha256_out: createHash("sha256").update(d.output).digest("hex").slice(0, 16),
    annotated: d.output !== text,
    authorities,
  }) + "\n")
  return d
}

function guard(text: unknown, tag: string): GuardDecision {
  if (typeof text !== "string" || text.length === 0)
    return { decision: "approve", reason: "no text", output: typeof text === "string" ? text : "" }
  const { allowed, block } = authorities()
  const work = guardChain.then(async (): Promise<GuardDecision> => {
    try {
      return logDecision(guardOnce(text, allowed, tag), tag, text, allowed.length)
    } catch (first) {
      // One logged retry: transient spawn contention (observed on the subagent path).
      await new Promise((r) => setTimeout(r, 250))
      appendFileSync(join(WS, "guard-log.jsonl"),
        JSON.stringify({ tag, retry: true, first_error: String(first).slice(0, 300) }) + "\n")
      return logDecision(guardOnce(text, allowed, tag), tag, text, allowed.length)
    }
  })
  guardChain = work.catch(() => {})            // never break the chain on a failed call
  return work as unknown as GuardDecision     // hooks await the returned value
}

const eventCounts = new Map<string, number>()

export const IronFleetGuard = async (_ctx: unknown) => {
  return {
    "tool.execute.before": async (input: { tool: string; sessionID: string; callID: string },
                                   output: { args: unknown }) => {
      const res = await guard(JSON.stringify(output.args ?? {}), `tool.execute.before:${input.tool}`)
      if (authorities().block && res.decision === "block") throw new Error(res.reason)
    },
    "tool.execute.after": async (input: { tool: string; sessionID: string; callID: string },
                                  output: { title: string; output: string; metadata: unknown }) => {
      captureAuthorities(output.output)   // R1 D6: corpus envelope -> the quote referee
      const res = await guard(output.output, `tool.execute.after:${input.tool}`)
      // ENVELOPE-AWARE (M0 hazard 2): blanket text annotation corrupts built-in tools'
      // structured JSON envelopes (SchemaError, session killed — observed live). Detection and
      // blocking run on EVERY tool (a block never mutates content, so it is envelope-safe);
      // annotation mutates ONLY whitelisted free-text paths — the custom tools and `task`,
      // whose result IS a subagent's prose answer. An unknown tool is detected and blocked but
      // never rewritten. This is the fail-safe direction.
      if (ANNOTATE.has(input.tool)) output.output = res.output
      if (authorities().block && res.decision === "block") throw new Error(res.reason)
    },
    "experimental.text.complete": async (_input: unknown, output: { text: string }) => {
      // DEFENSIVE: with some models (thomson1 observed 2026-09-02) text parts can arrive
      // with an undefined/empty text field during reasoning-phase streaming — touching
      // them feeds opencode's part-cleanup a shape it rejects (SchemaError at
      // part.text). Only annotate when a non-empty string is actually present.
      if (typeof output.text !== "string" || output.text.length === 0) return
      const res = await guard(output.text, "text.complete")
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
