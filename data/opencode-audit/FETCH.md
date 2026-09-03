# T1 Fresh-Fetch Dossier — `opencode-ai@1.18.25` (S7a / CR-4)

Scan target **T1** for the CR-4 supply-chain review of OpenCode 1.18.25.

**Date:** 2026-09-03
**Purpose:** produce a clean, version-pinned, reproducible install of `opencode-ai@1.18.25`
whose install-time scripts were **never executed** (`--ignore-scripts` — unadjudicated scripts
are read, never run), and record the procedure, resolved versions, and tarball digests.

The sandbox lives **outside** this repo at
`C:\Users\mianx\OneDrive\Desktop\opencode-audit\` and is never committed. Only this file is
committed.

## Environment

| Tool  | Version     |
|-------|-------------|
| node  | `v24.16.0`  |
| npm   | `11.13.0`   |
| OS    | Windows 11 Pro (10.0.26200), Git Bash shell |
| Registry | `https://registry.npmjs.org/` (npm ops limited to the registry) |

Global npm config at fetch time: `ignore-scripts=false`, `omit=[]`, `audit=true`, `fund=true`.
The `--ignore-scripts --omit=dev --no-audit --no-fund` flags below therefore all come from the
command line, not from config.

A pre-existing **global** install of `opencode-ai` 1.18.25 at
`C:\Users\mianx\AppData\Roaming\npm\node_modules\opencode-ai` is scan target **T3** for a later
task and was **not touched** by this procedure.

## Step 1 — Commands run (verbatim)

```bash
mkdir -p "/c/Users/mianx/OneDrive/Desktop/opencode-audit/fresh" && cd "/c/Users/mianx/OneDrive/Desktop/opencode-audit/fresh"
npm init -y >/dev/null
npm install opencode-ai@1.18.25 --ignore-scripts --omit=dev --no-audit --no-fund
cp package-lock.json ../fresh-package-lock.json
npm pack opencode-ai@1.18.25 opencode-windows-x64@1.18.25
sha256sum *.tgz
```

All five commands ran as written. Observed npm output:

- `npm install` → `added 3 packages in 7s` (exit 0). **No warnings, no funding or audit
  notices were emitted** (both were disabled by flag); the only output was the `added 3
  packages in 7s` line, recorded here verbatim.
- `npm pack` emitted `npm notice` blocks (reproduced below, verbatim) because `npm pack`
  always prints notices regardless of `--loglevel`; they are informational, not warnings.

```
npm notice
npm notice package: opencode-ai@1.18.25
npm notice Tarball Contents
npm notice 1.1kB LICENSE
npm notice 479B bin/opencode.exe
npm notice 825B package.json
npm notice 5.5kB postinstall.mjs
npm notice Tarball Details
npm notice name: opencode-ai
npm notice version: 1.18.25
npm notice filename: opencode-ai-1.18.25.tgz
npm notice package size: 3.0 kB
npm notice unpacked size: 7.9 kB
npm notice shasum: 0649bb7833e3db91ab1435e9c8a8da75f8eae162
npm notice integrity: sha512-pS4RKJ9eKwU7D[...]03WCArY0EK6mg==
npm notice total files: 4
npm notice
opencode-ai-1.18.25.tgz
npm notice package: opencode-windows-x64@1.18.25
npm notice 179.7MB bin/opencode.exe
npm notice 140B package.json
npm notice name: opencode-windows-x64
npm notice filename: opencode-windows-x64-1.18.25.tgz
npm notice package size: 60.1 MB
npm notice unpacked size: 179.7 MB
npm notice shasum: 5000e1b50a21b42694cabad2848a7d25552542f2
npm notice integrity: sha512-xW5wtSxWYbI7D[...]kqnkU3F2dio7A==
npm notice total files: 2
opencode-windows-x64-1.18.25.tgz
```

**Adaptation noted (Step 3 lockfile listing only):** the brief's
`node -e "const l=require('../opencode-audit/fresh-package-lock.json'); ..."` uses a relative
path that does not resolve from inside `fresh/` (`../opencode-audit/` would be
`.../Desktop/opencode-audit/opencode-audit/`, which does not exist). Run as written it fails
with `Cannot find module '../opencode-audit/fresh-package-lock.json'`. The identical one-liner
was re-run with the corrected path `../fresh-package-lock.json` (same script body, same
lockfile file). No other command was adapted.

## Step 1 result — tarball digests

`sha256sum *.tgz` output (from `.../opencode-audit/fresh/`):

```
9be29b0858b3c9bb1214569f1d8e48a783956c8f5093cc6dcd86717e2cd8c5a3 *opencode-ai-1.18.25.tgz
07bcd049b7f1c7ba7184ab97240fb9cd63332fdbfa1d53d84dfbde0f010f4796 *opencode-windows-x64-1.18.25.tgz
```

On-disk tarball sizes: `opencode-ai-1.18.25.tgz` 3,047 bytes;
`opencode-windows-x64-1.18.25.tgz` 60,101,564 bytes.

**Cross-check:** both `sha512-*` integrity strings recomputed from these tarballs match the
`integrity` fields npm recorded in `fresh-package-lock.json` for
`node_modules/opencode-ai` and `node_modules/opencode-windows-x64` exactly. The tarballs
hashed above are therefore byte-identical to the ones npm actually resolved and installed.

## Step 2 — Verification that scripts did NOT run

Command run (verbatim) and its observed output:

```
$ ls node_modules/opencode-ai/bin/ 2>/dev/null; echo "exit=$?"
opencode.exe
exit=0
```

**Observation verbatim:** `opencode.exe` IS present in `node_modules/opencode-ai/bin/`, so the
gate tripped and was investigated per the brief ("STOP and investigate where it came from
before proceeding").

**Investigation — the file is the publisher's own stub, not a postinstall artifact.**

The `--ignore-scripts` install produced a `bin/opencode.exe` of exactly **479 bytes**. That
file is shipped inside the published `opencode-ai@1.18.25` tarball itself — `npm pack` listed
`479B bin/opencode.exe` among the tarball's 4 contents (see notice block above). Proof, by
byte-identity:

```
21c366f53283d5b5e1cdbbec2aafc98286b4c1075a4c3d5afd5ce1f5c9bf46dd  package/bin/opencode.exe
    (extracted from freshly packed opencode-ai-1.18.25.tgz; 479 bytes)
21c366f53283d5b5e1cdbbec2aafc98286b4c1075a4c3d5afd5ce1f5c9bf46dd  node_modules/opencode-ai/bin/opencode.exe
    (as installed with --ignore-scripts; 479 bytes)
```

Corroborating evidence that `postinstall.mjs` never ran:

1. The real platform binary —
   `node_modules/opencode-windows-x64/bin/opencode.exe`, **179,651,624 bytes** — was **not**
   copied into `node_modules/opencode-ai/bin/`. Reading `postinstall.mjs`, its `main()` ends in
   `copyBinary(resolveBinary(name), targetBinary)`, and `copyBinary` calls
   `fs.unlinkSync(target)` then `fs.linkSync`/`fs.copyFileSync` — i.e. a successful postinstall
   would have **replaced** the 479-byte stub with a 179,651,624-byte file. The stub is intact
   and the directory contains nothing else.
2. `node_modules/opencode-ai/` contains exactly the 4 files the tarball ships
   (`LICENSE`, `package.json`, `postinstall.mjs`, `bin/opencode.exe`) and no extras — no
   caches, logs, or temp dirs that an executing script would leave.
3. `postinstall.mjs` also calls `verifyBinary()` → `childProcess.spawnSync(targetBinary,
   ["--version"])` — it *executes* the binary it installs. No such execution occurred.

**Gate result: PASS.** Scripts were never executed. The 479-byte `opencode.exe` is a
publisher-shipped stub present in the source tarball, and its byte-identity with the tarball
content plus the absence of the 179 MB binary that a successful postinstall would have written
confirm this. Note for downstream tasks: the brief's expectation of an *empty or missing*
`opencode.exe` is not met on the letter — `opencode-ai@1.18.25` ships a stub `bin/opencode.exe`
in the tarball — but the substantive invariant ("the postinstall never ran, so the real binary
was never selected or executed") holds and is proven above.

## Resolved versions (full lockfile listing)

From `../opencode-audit/fresh-package-lock.json`, `lockfileVersion` 3:

```
(root) 1.0.0
node_modules/opencode-ai 1.18.25
node_modules/opencode-darwin-arm64 1.18.25
node_modules/opencode-darwin-x64 1.18.25
node_modules/opencode-darwin-x64-baseline 1.18.25
node_modules/opencode-linux-arm64 1.18.25
node_modules/opencode-linux-arm64-musl 1.18.25
node_modules/opencode-linux-x64 1.18.25
node_modules/opencode-linux-x64-baseline 1.18.25
node_modules/opencode-linux-x64-baseline-musl 1.18.25
node_modules/opencode-linux-x64-musl 1.18.25
node_modules/opencode-windows-arm64 1.18.25
node_modules/opencode-windows-x64 1.18.25
node_modules/opencode-windows-x64-baseline 1.18.25
```

The dependency footprint is minimal: **one runtime package** (`opencode-ai`) plus its **12
`optionalDependencies`** platform-binary packages. Every one of the 12 is pinned to exactly
`1.18.25` — no floating ranges, no transitive dependencies, no other packages in the tree.

### Platform packages: resolved for win32-x64 vs pinned-but-not-installed

`opencode-ai@1.18.25` declares these 12 optionalDependencies, all `1.18.25`:

`opencode-darwin-arm64`, `opencode-darwin-x64`, `opencode-darwin-x64-baseline`,
`opencode-linux-arm64`, `opencode-linux-arm64-musl`, `opencode-linux-x64`,
`opencode-linux-x64-baseline`, `opencode-linux-x64-baseline-musl`, `opencode-linux-x64-musl`,
`opencode-windows-arm64`, `opencode-windows-x64`, `opencode-windows-x64-baseline`.

**Resolved and installed on this host (win32-x64) — 2 packages:**

- `opencode-windows-x64` (os `win32`, cpu `x64`) — carries the real
  `bin/opencode.exe`, 179,651,624 bytes
- `opencode-windows-x64-baseline` (os `win32`, cpu `x64`) — the non-AVX2 fallback variant

npm installed **both** win32-x64-compatible optionals rather than exactly one. This is normal
npm behaviour: every `optionalDependency` whose `os`/`cpu` matches the current platform is
installed, and *choosing* between them is the job of `postinstall.mjs` (its `supportsAvx2()`
probe, which on Windows shells out to PowerShell
`kernel32!IsProcessorFeaturePresent(40)`). Because the postinstall never ran, **no selection
was made and neither binary was chosen, copied, or executed** — both packages sit installed but
inert. That the two-variant install happened instead of a single-package install is itself
further evidence the postinstall was skipped.

**Version-pinned 1.18.25 in the lockfile but NOT installed — the other 10 packages:**

`opencode-darwin-arm64`, `opencode-darwin-x64`, `opencode-darwin-x64-baseline`,
`opencode-linux-arm64`, `opencode-linux-arm64-musl`, `opencode-linux-x64`,
`opencode-linux-x64-baseline`, `opencode-linux-x64-baseline-musl`, `opencode-linux-x64-musl`,
`opencode-windows-arm64`.

Each carries `os`/`cpu` constraints that do not match win32-x64, so npm's optional-dependency
resolution skipped them. **They cannot execute on this OS**, so they are inert metadata in the
lockfile: pinned, digest-recorded, and never unpacked here. Present on disk under
`node_modules/`: only `opencode-ai`, `opencode-windows-x64`,
`opencode-windows-x64-baseline` (plus npm's own `.bin` and `.package-lock.json`).

## Downstream

- The T1 tree at `C:\Users\mianx\OneDrive\Desktop\opencode-audit\fresh\node_modules` is the
  scan target consumed by Task 6's CLI run.
- The lockfile copy is preserved at
  `C:\Users\mianx\OneDrive\Desktop\opencode-audit\fresh-package-lock.json`.
- Because `bin/opencode.exe` here is the 479-byte stub (not a runnable OpenCode CLI), any task
  that needs to *execute* the CLI must do so explicitly and out-of-band; it cannot assume the
  postinstall left a working binary behind.
