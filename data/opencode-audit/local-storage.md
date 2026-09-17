# Local-storage confidentiality + Bun runtime note — OpenCode 1.18.25 (CR-4 / S7a, plan item A-8)

**Read-only inspection only.** Database opened `mode=ro`; counts only — no content dumped. No matter data present.

## 1. Inventory — `~/.local/share/opencode`

| Entry | Size | Notes |
|---|---|---|
| `log/` | 404K | Spike log (1 file, `opencode.log`) |
| `opencode.db` | 8.8M | SQLite session database |
| `opencode.db-shm` | 32K | Shared-memory header |
| `opencode.db-wal` | 4.1M | Write-ahead log (unflushed data) |
| `repos/` | 0 | Empty |
| `snapshot/` | 309K | Contains `global/` subdir |
| `tool-output/` | 828K | Tool call outputs |

Total live data (DB + WAL): ~12.9 MB; snapshot + log + tool-output add ~1.5 MB.

## 2. DB tables + counts + confidentiality read

All tables (name, row count):

| Table | Rows | Holds session/message TEXT? |
|---|---|---|
| `workspace` | 0 | — |
| `data_migration` | 0 | — |
| `account_state` | 0 | — |
| `account` | 0 | — |
| `control_account` | 0 | — |
| `credential` | 0 | Possible auth tokens (0 rows) |
| `event_sequence` | 66 | Yes — sequence metadata |
| `event` | 2043 | Yes — event payloads (text) |
| `permission` | 0 | — |
| `project_directory` | 1 | — |
| `project` | 2 | Project config |
| `message` | 197 | **Yes — user/assistant message text** |
| `part` | 704 | **Yes — message content parts (text)** |
| `session_context_epoch` | 0 | — |
| `session_input` | 0 | Plausible (name suggests prompt text; 0 rows) |
| `session_message` | 0 | Plausible (name suggests message text; 0 rows) |
| `session` | 66 | Session metadata |
| `todo` | 0 | — |
| `session_share` | 0 | — |
| `migration` | 38 | Schema version records |

**Session/message TEXT tables (names only):** `message`, `part`, `event`, `event_sequence`, `session`, `session_input` (0 rows), `session_message` (0 rows).

**Confidentiality read:** Once A-1 runs and populates the DB, `message`, `part`, and `event` will hold user/assistant conversation text — that is **matter data at rest**. These tables must be treated according to CR-7 posture: A-1 must place the DB in an encrypted/vaulted location, maintain encrypted backups, and enforce access control on the SQLite file. The `credential` table is a potential holder of auth tokens (currently 0 rows) and must also be CR-7 protected once populated.

**WAL / CR-7 backup timing:** The `-wal` file is 4.1M — significant unflushed data. Any backup taken while WAL is non-zero risks capturing incomplete transactions; the WAL must be checkpointed (or the backup taken with WAL consistent snapshot) before a trusted backup. CR-7 backup cadence should account for WAL growth between checkpoints.

**Log retention:** `log/opencode.log` (404K) may contain operation metadata; retention should follow CR-7 policy (no indefinite retention of operational logs near matter data).

## 3. Bun runtime note

**Binary scanned:** `opencode-windows-x64/bin/opencode.exe` (~180 MB; sha256 `ef06e41a35795066e95acde276a42fbbf85d7a683c2787f6a19ed20bcde9b6ff`, per `data/opencode-audit/sha256-manifest.txt`).

**Bun is compiled INTO the shipped exe.** Evidence from the binary:
- `bunx` string matches: `bunx`, `bunx-`, `bunxu` — all found inside embedded documentation/usage strings (`"Use \`bunx <package> <command>\` instead"`, `"usage: bunx --package=<package-name> <bin>"`, `"bunx failed to install"`, `"Runs bunx create-<template>"`, `"Installing if needed (bunx)"`, etc.).
- `bun ` spawn matches: `bun `, `bun\n`, `bun\r` — all in help/error text, NOT process-spawn call sites.
- **bun/bunx subprocess spawning NOT observed.** These are static strings in the binary's embedded help/documentation, not evidence of runtime `spawn("bunx", ...)` or `spawn("bun", ...)` calls.

**No separate Bun install required.** The runtime ships bundled in the exe (provenance = Task 6 manifest hash). Embedded Bun executes the project's plugin TypeScript by design — this is the adopted seam.

**Adopted seam — `experimental.text.complete`:** The binary contains 25 distinct `experimental.*` feature flags, including `experimental.text.complete` (the seam referenced in the spec). Full list of SEAM_COUNT=25 flags: `experimental.capabilities.get`, `experimental.chat.messages.transform`, `experimental.chat.system.transform`, `experimental.compaction.autocontinue`, `experimental.console.get`, `experimental.console.listOrgs`, `experimental.console.switchOrg`, `experimental.controlPlane.moveSession`, `experimental.policies`, `experimental.projectCopy.generateName`, `experimental.provider.small`, `experimental.resource.list`, `experimental.session.background`, `experimental.session.compacting`, `experimental.session.list`, `experimental.tasks.callToolStream`, `experimental.text.complete`, `experimental.wolfram`, `experimental.workspace.adapter.list`, `experimental.workspace.create`, `experimental.workspace.list`, `experimental.workspace.remove`, `experimental.workspace.status`, `experimental.workspace.syncList`, `experimental.workspace.warp`.

**`data/opencode-audit/binary-urls.txt`:** Contains 78 lines referencing `bun.com` and `bun.sh` URLs (docs, changelog, Discord, CLI reference, bundler docs, test snapshots, debug endpoint). These are documentation URLs shipped as binary strings — not runtime fetch targets identified by the spike. They do not indicate a separate Bun runtime dependency.

**Conclusion:** Runtime = Bun compiled into the exe. No standalone Bun install. bunx spawning not observed. Plugin TS execution via embedded Bun is by design (the adopted seam).
