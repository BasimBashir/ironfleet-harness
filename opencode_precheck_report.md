# OpenCode 1.18.25 — supply-chain + confidentiality gate report (CR-4 / S7a)

**Gate:** CR-4 — no real matter data reaches A-1 until critical findings = 0
**or** each finding is adjudicated with an evidence trail (S1 lefthook-ruling style).
**Date:** 2026-09-04 · **Auditor:** Claude (S7a / A-8), for Jonathan
**Trees:** t1 (fresh npm fetch) · t2 (runtime-installed, `~/.config/opencode`) ·
t3 (global install, `%APPDATA%/npm`) · spike (proven wiring, no installed tree)
**Adopted version pinned:** `opencode-ai@1.18.25`
**Companion artifacts:** [`data/opencode-audit/`](./data/opencode-audit/) (scan.json,
mechanical-scan.md, sha256-manifest.txt, drift.md, adjudications.md, egress.md,
local-storage.md, scope-note.md, FETCH.md, binary-urls.txt, log-urls.txt)

---

## 1. Mechanical scan — at a glance

Scanner: `src/harness/security/opencode_precheck.py` (Tasks 1–4, suite 72/72).
Install trees scanned read-only; nothing executed; T1 fetched with `--ignore-scripts` and
proven scripts-never-ran three independent ways (FETCH.md).

| Metric | t1 | t2 | t3 | spike | Total |
|---|---:|---:|---:|---:|---:|
| packages | 3 | 50 | 3 | 0 | **56** |
| missing licence fields | 2 | 16 | 2 | 0 | **20** (non-distributed dirs per licences) |
| vendored | 0 | 0 | 0 | 0 | **0** |
| lifecycle criticals (unadjudicated) | 1 | 5 | 1 | 0 | **7** |
| floating runtime ranges | 0 | 1 | 0 | 1 | **2** |
| native binaries inventoried | 3 | 2 | 3 | 0 | **8** |
| native sha256s matching manifest | 3 | 2 | 3 | 0 | **8/8 verified** |

**Install-time execution surface (complete set, per `scope-note.md` §3):**
`preinstall` / `install` / `postinstall` / `prepare` / `prepublish` — a deliberate
superset that over-flags rather than misses. A full `scripts`-key sweep across all three
trees yields exactly these 7 findings and nothing more. npm publish-time-only hooks
(`prepublishOnly`, `prepack`, `postpublish` — 8 in t2, non-critical, documented in
`scope-note.md` §2) cannot run on a registry install and are excluded from the critical count.

---

## 2. Critical findings → adjudication (6/6 accept, 0 escalate)

`mechanical-scan.md` counts **7** lifecycle criticals; **6 distinct scripts** —
`t1 opencode-ai postinstall` and `t3 opencode-ai postinstall` are one script,
byte-identical (sha256 `5a7c990f…` on both trees, `diff` empty; verified in
`adjudications.md`).

| # | Tree | Package · script | Verdict | Evidence |
|---|---|---|---|---|
| 1 | t1 + t3 | `opencode-ai` · **postinstall** | **ACCEPT** | [`adjudications.md:51`](./data/opencode-audit/adjudications.md) |
| 2 | t2 | `msgpackr` · **prepare** | **ACCEPT** | [`adjudications.md:112`](./data/opencode-audit/adjudications.md) |
| 3 | t2 | `msgpackr-extract` · **install** | **ACCEPT** | [`adjudications.md:154`](./data/opencode-audit/adjudications.md) |
| 4 | t2 | `undici` · **prepare** | **ACCEPT** | [`adjudications.md:211`](./data/opencode-audit/adjudications.md) |
| 5 | t2 | `uuid` · **prepare** | **ACCEPT** | [`adjudications.md:255`](./data/opencode-audit/adjudications.md) |
| 6 | t2 | `which` · **prepublish** | **ACCEPT** | [`adjudications.md:291`](./data/opencode-audit/adjudications.md) |

Method: every script read **in full**, imports followed transitively, third-party commands
identified by name and characterized from the exact published artifacts. Read, never
executed; all trees untouched. **6/6 accept, 0 escalate.** No escalation line is owed from
this adjudication to the gate report.

Each accepted finding carries the S1-style trail: what runs, what it writes, what it
spawns, network reach (and the conditions under which a network branch becomes live, with
its guard), and why it is inert on this mount. The t3 live install corroborates the t1
code reading exactly: postinstall selected the AVX2 (`x64`) variant, replaced the 479-byte
publisher stub with the 179 MB platform binary, and nothing else in the tree changed
(`drift.md`: binary drift NONE).

**Residual (non-adjudication-blocking, for A-1's record):** install-time execution of the
platform binary means a compromised publisher build would run at `--version` privilege on
install — mitigated by the version pin, integrity digests (lockfile), and the fact that the
binary is the product itself.

---

## 3. Hazards (not criticals — A-1 / Task 10 input)

### 3.1 Floating runtime range
`@ai-sdk/openai-compatible` declared `^3.0.41` in t2's root `package.json` — a floating
range, resolved to `3.0.41` (the bottom of its range) in t2's own lockfile (verified).
**Hazard:** a minor bump to the range could pull a newer major with a breaking surface
change. Mitigation: pin in the harness config / re-verify on every upgrade (per §7 below).

### 3.2 `@ai-sdk/provider` — two majors in one runtime tree
`@ai-sdk/provider` is present at **3.0.8** (top-level) **and 4.0.9** (nested under
`@ai-sdk/openai-compatible` and under `@ai-sdk/provider-utils`) in t2. This is a direct
consequence of the floating range above: `3.0.41` resolved to the bottom of its range and
pulled its own `@ai-sdk/provider` 4.0.9, while the tree also carries a top-level 3.0.8. Two
majors of one package in a single runtime tree means the actually-loaded provider code path
cannot be determined from the manifest alone. **Escalate to A-1** (resolver picking is a
runtime behaviour, out of band for a manifest scanner).

### 3.3 Drift / tree-set findings (from `drift.md`)
- **Binary drift: NONE.** All 8 manifest sha256s recompute from disk; installed `opencode.exe`
  instances match their t1 fetches. t3/bin/opencode.exe (179,651,624 B, `ef06e41a…`) = the
  postinstall **output** (no t1 counterpart, because `--ignore-scripts` blocked it in T1).
- **Version drift: none** within the shared package set; every name in both a scanned tree and
  the T1 lockfile resolves to `1.18.25` on both sides. t2 is OpenCode's runtime-installed
  plugin/dep tree — its 31 `not-in-t1` entries are a **set difference, not a version conflict**.
- **t3b naming:** the brief expected the platform package as a sibling of `opencode-ai` in the
  global `node_modules`; on this host it nests **inside** `opencode-ai`. Nothing lost — the
  scanner walks recursively, so both were inventoried under t3. t3b is skipped as a separate label.

### 3.4 Egress findings (from `egress.md`) — rows **without** config-schema control
Four endpoints are default-on or unguarded at the config-schema level (the 4 findings, F1–F4):

- **F1 — `models.opencode.ai/api.json` catalog fetch is default-on and config-uncontrolled.**
  Runs at startup + every 60 min; disk cache stale after 5 min. Disable exists only as env vars
  (`OPENCODE_DISABLE_MODELS_FETCH`, `OPENCODE_MODELS_URL`, `OPENCODE_MODELS_PATH`) — there is
  **no `opencode.json` key**. Spike did not set the env var; the 4.4 MB
  `~/.cache/opencode/models.json` on disk proves it ran. `packages/core/src/models-dev.ts` @v1.18.25.
- **F2 — ripgrep downloaded from GitHub releases, no integrity check, no disable.** Lazy-triggered
  on first grep use; stored in `~/.cache/opencode/bin/`; only non-empty-size + extraction-success
  checks (no sha256/signature); **no config key and no env var**. Observed live (log line 146).
  `packages/core/src/ripgrep/binary.ts` @v1.18.25.
- **F3 — tree-sitter `.wasm` grammar downloads from GitHub releases (binary-only evidence).**
  URLs in the binary; no log evidence, no config control found. Lower confidence — stated as
  binary-only. Gate-deny; verify empirically in A-1.
- **F4 — `debug.bun.sh` (Bun runtime crash-report endpoint) compiled into the exe.** Crash-only
  path; no call evidence; no OpenCode config key. Gate-deny recommended (whether compiled Bun
  actually uploads on Windows is unverified here).

**Other egress rows** (16 total in `egress.md`) are config-gated: `autoupdate: false` and
`share: "disabled"` (both verified in the spike config against the schema and source), per-server
`lsp.*.disabled`, provider `enabled_providers`/`disabled_providers`, `permission` patterns,
and the command-gated GitHub integration. All model provider traffic is through-gate traffic by
definition. **Negative results:** zero telemetry/analytics endpoints across all 545 hosts /
1040 URLs; no sentry/posthog/statsig/segment/ingest hosts; the bundled Sentry JS SDK is
telemetry-capable but inactive (no DSN, no `Sentry.init`, no `sentry.io` host; the lone
`@sentry/` string is data in the SDK's module-name registry, not an import).

---

## 4. Local-storage confidentiality + Bun runtime (summary — see [`local-storage.md`](./data/opencode-audit/local-storage.md))

**Inventory** (`~/.local/share/opencode`): `opencode.db` 8.8 MB, `-wal` 4.1 MB, `-shm` 32 KB,
`log/` 404 KB, `snapshot/` 309 KB, `tool-output/` 828 KB, `repos/` empty. Live DB + WAL ≈ 12.9 MB.

**DB (read-only `mode=ro`, counts only — no content dumped):** 20 tables. Session/message TEXT
tables, by **name only**: `message` (197 rows), `part` (704), `event` (2043), `event_sequence`
(66), `session` (66), plus `session_input`/`session_message` (0 rows each). `credential` (0 rows)
is a potential auth-token holder. **Once A-1 runs, `message`/`part`/`event` will hold
user/assistant conversation text — that is matter data at rest.**

- **CR-7 posture required:** A-1 must place the DB in an encrypted/vaulted location, maintain
  encrypted backups, and enforce access control on the SQLite file.
- **WAL 4.1 MB is unflushed:** any backup taken while WAL is non-zero risks incomplete
  transactions; the WAL must be checkpointed (or backed with a consistent snapshot) before a
  trusted backup. CR-7 backup cadence must account for WAL growth between checkpoints.
- **Log retention:** `log/opencode.log` may carry operation metadata; retention follows CR-7
  policy (no indefinite retention near matter data).

**Bun runtime:** compiled **into** the shipped exe (provenance = manifest hash; no separate Bun
install). Embedded Bun executes the project's plugin TypeScript by design — this is the adopted
seam (`experimental.text.complete`, SEAM_COUNT = 25 flags present). bun/bunx subprocess spawning
**not observed** — matches in the binary are embedded help/documentation strings, not spawn call
sites; `binary-urls.txt`'s 78 bun.com/bun.sh lines are documentation URLs.

---

## 5. A-1 configuration requirements (binding, for the stand-up)

1. **Pin OpenCode at 1.18.25** and run the guard-mount regression rig (the spike's rig) on every
   upgrade — roughly one hour per upgrade. Name the fallback if `experimental.text.complete`
   changes signature or is withdrawn (per Jonathan's 2026-09-16 standing requirement).
2. **`autoupdate: false`** (already in harness config; verified — `cli/upgrade.ts` returns before
   any network call when `false`). Keep; no upgrade-check egress.
3. **`share: "disabled"`** (already in harness config; verified — blocks explicit share; schema
   enum `manual|auto|disabled`; docs default is `manual`). Keep; no share egress.
4. **Pin runtime dependencies:** tarball-pin `opencode-ai@1.18.25` + its 12 platform optionals
   (all exactly `1.18.25`, lockfile `resolved` + `integrity`) and gate-allow
   `registry.npmjs.org` scope only for provider/plugin installs (`provider.*.npm` field) — or
   use `--pure`/offline to avoid runtime npm fetches. Address F2 by pre-placing a pinned `rg.exe`
   on PATH and gate-denying `github.com/*/releases/download/*` **plus** its
   `*githubusercontent.com` 302 redirect targets.
5. **Mitigate F1:** set `OPENCODE_DISABLE_MODELS_FETCH` (and/or `OPENCODE_MODELS_URL`) in the
   harness env — there is no config key for the catalog fetch.
6. **Mitigate F3/F4:** gate-deny the tree-sitter GitHub release-download family and `debug.bun.sh`.
7. **Data-dir placement & backup (CR-7):** place `~/.local/share/opencode` (DB + WAL) in an
   encrypted/vaulted location; maintain encrypted backups with WAL-checkpointing before each
   trusted backup; enforce filesystem access control. Backups must account for the 4.1 MB WAL.
8. **Workspace isolation (SEAM_COUNT / Module E):** agent identity is a record, not a process —
   a matter is a row with a UUID; personas are versioned files on disk loaded at session start.
   Tree-kill supervision (`taskkill /T /F` on Windows, per the spike) and workspace-isolation
   rules from SEAM_COUNT apply.
9. **Envelope-aware tool annotation** is a Module E line item (annotate presentation, not the
   internal JSON envelope) — per Jonathan's 2026-09-16 direction.

---

## 6. Gate verdict

**CLEARED WITH ADJUDICATIONS** — A-1 may proceed.

Basis, per the CR-4 gate semantics:
- **As-measured criticals ≠ 0** (7 lifecycle criticals across 4 trees).
- **Every critical is adjudicated with an evidence trail** — 6 distinct scripts, **6/6 accept,
  0 escalate** (§2), each dossier read in full and linked above. The CR-4 condition
  ("critical findings = 0 **or** each finding adjudicated with an evidence trail") is therefore met.
- **No real matter data passed through OpenCode during this review:** T1 was fetched with
  `--ignore-scripts`; all trees were read, never executed; the DB was opened read-only (`mode=ro`)
  for counts only; no matter data is present anywhere in the audit surface (§4).

**Escalations to Jonathan (out of band — they are not CR-4 criticals and carry no
adjudication deficit, but they gate A-1's safe operation):**
1. `@ai-sdk/provider` two-majors in t2 (§3.2) — resolver behaviour, needs A-1 verification.
2. F1/F2/F3/F4 egress findings (§3.4) — config-gating or deny rules required before real traffic.
3. CR-7 data-dir placement/backup posture for the live DB + WAL (§4) — required once A-1 populates it.
4. Pin + regression rig on every OpenCode upgrade (§5 #1) — standing requirement.

**Standing rule for the programme:** no real matter data reaches OpenCode through A-1 until the
items in §5 are in place **and** the F1–F4 egress mitigations are applied or denied.

---

## 7. Standing rules from M0 (2026-09-16, Jonathan) — carried into A-1

- **Adopt OpenCode as the agent layer; in-house core stays** (gate, provenance, scorer, persona).
- **dsh is out on the CR-2a stability bar** (not a security rejection) — the single critical
  finding in the sibling dsh pre-check was ruled accepted so P0-6 closes properly; dsh exits the
  programme unless deliberately reopened.
- **OpenHands is out on the immutable carrier** (finish-tool ObservationEvent); the delegation
  seam is *unmeasured*, not failed — the Windows `openhands-tools` failure is a Rust-sdist-on-Windows
  issue, not a platform limit.
- **Agent identity is a record, not a process** (UUID per matter); **personas are files**
  (versioned, on disk, loaded at session start).
- **Envelope-aware tool annotation** is a Module E line item.
- **Supermemory self-hosted spike** (2-day timebox, due Fri 25 Sept) and **Thomson-1.0-Small memo**
  (open decision, needs its own memo) are parked outside S7a/S7b.

---

## 8. Artifact index (`data/opencode-audit/`)

| Artifact | Contents |
|---|---|
| `scan.json` | 4 trees, 56 packages, 7 lifecycle criticals, 2 floating, 8 native binaries + sha256s |
| `mechanical-scan.md` | Per-tree criticals, floating, native inventory (human-readable) |
| `sha256-manifest.txt` | 8 native binaries, hash + size |
| `drift.md` | t1/t2/t3 vs T1 lockfile; binary/v版本 drift NONE; sha256 cross-checks |
| `scope-note.md` | Lifecycle tuple definition; npm v11 citation; publish-time-only inventory |
| `adjudications.md` | 6 dossiers, 6/6 accept, full read-full evidence trails |
| `egress.md` | 16-row endpoint × control matrix + F1–F4 findings + negative results |
| `local-storage.md` | Data dir inventory, DB tables/counts, confidentiality read, Bun note |
| `FETCH.md` | T1 fetch provenance; scripts-never-ran proof (3 ways); lockfile integrity |
| `binary-urls.txt` / `log-urls.txt` | Raw host/URL extractions from binary + spike log |

---

*Report generated as part of S7a (A-8), CR-4 gate. Companion plan:
[plans/2026-09-03-s7a-opencode-precheck.md](../../plans/2026-09-03-s7a-opencode-precheck.md).*
