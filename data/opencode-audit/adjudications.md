# A-8 lifecycle-script adjudication dossiers (S7a / CR-4) — Task 7

**Date:** 2026-09-03 · **Adjudicator:** Claude (Task 7), for Jonathan's CR-4 gate
**Input:** the 7 critical lifecycle findings in `scan.json` / `mechanical-scan.md` (Task 6,
independently re-derived twice). **Output:** 6 dossiers — finding 1 (`t1 opencode-ai
postinstall`) and finding 7 (`t3 opencode-ai postinstall`) are the **same script, byte-identical**
(sha256 `5a7c990fe552e76b16422cdba3f4b0550590c7a487f7932c773362f74317c87b` on both trees,
`diff` empty) and are adjudicated once, with the second instance noted in the dossier.

Method (S1 lefthook-ruling style, NEXT_STEPS.md §S1): every script read **in full** in its own
tree, imports followed transitively where they are local files, third-party commands identified
by name and (where not present in the tree) characterized from the exact published artifacts.
Scripts were **read, never executed**; all trees untouched.

Common context for the `t2` dossiers (cited once here, not repeated):

- The `t2` tree (`C:\Users\mianx\.config\opencode`) is OpenCode's **runtime-installed** package
  tree (drift.md: "t2 is a different package set (OpenCode's runtime-installed plugins/deps)"),
  populated 2026-09-01 16:07 during the adopt spike. Its root `package.json` declares only
  `@ai-sdk/openai-compatible ^3.0.41` and `@opencode-ai/plugin 1.18.25`; the six adjudicated
  packages below are transitive dependencies of those. The install is npm-CLI-shaped:
  `package-lock.json` `lockfileVersion` 3 with registry `resolved` + `integrity` for every
  package (spot-checked for all six), and npm-style `.bin` shims (`.sh`/`.cmd`/`.ps1` trio).
- **Why `prepare`/`prepublish` are in scope at all:** npm CLI v11's own docs
  (`C:\Program Files\nodejs\node_modules\npm\docs\content\using-npm\scripts.md`, "Life Cycle
  Operation Order", `npm install` and `npm ci` tables — lines 129-139 and 112-120) list
  `prepublish`, `preprepare`, `prepare`, `postprepare` in the documented install lifecycle
  (the `npm install` table notes "These also run when you run `npm install -g <pkg-name>`").
  The scan's tuple keeps them for that reason (scope-note.md §1: over-flag rather than
  under-flag). Nuance kept honest below: for a **registry-tarball dependency**, npm does not
  re-run a dependency's own `prepare`/`prepublish` (those fire for the root package, git
  dependencies, local no-arg installs, and `npm pack` — scope-note.md:22-30); they are
  adjudicated anyway because the runtime installer's engine policy is not ours to assume and
  the gate counts them critical until ruled.
- `C:\Users\mianx\.config\opencode` is **not a git repository, nor is any parent** —
  `git rev-parse --show-toplevel` from that directory: `fatal: not a git repository (or any of
  the parent directories): .git`. This is load-bearing for three of the five t2 scripts.
- The t2 `node_modules` contains exactly 29 top-level entries; **none** of them is `rollup`,
  `cpy-cli`/`cpy`, `husky`, `lefthook`, or `node-gyp` (full listing checked; `.bin` grep
  matches only the `node-gyp-build-optional-packages*` trio). Every dev-tool a t2 script
  references is therefore absent from the tree.

**Out of scope here by the Task 7 brief** (recorded so the count above stays clean): the
`@ai-sdk/provider` two-majors hazard and the `^3.0.41` floating range (drift.md lines 67-84
marks them "Escalate to Task 7"; the Task 7 brief assigns them to Task 10's hazard/A-1 input
instead — no dossier here silently drops them), and the 8 publish-time-only scripts
(scope-note.md §2, non-critical).

---

## t1 — opencode-ai · postinstall — C:\Users\mianx\OneDrive\Desktop\opencode-audit\fresh\node_modules\opencode-ai\postinstall.mjs

*(dual instance: finding 7, `t3 — opencode-ai · postinstall` at
`C:\Users\mianx\AppData\Roaming\npm\node_modules\opencode-ai\postinstall.mjs` — byte-identical
file, sha256-verified above; one adjudication covers both. Declared at
`opencode-ai/package.json:7` — `"postinstall": "node ./postinstall.mjs"`; 189 lines, read in
full. The tarball ships exactly 4 files: LICENSE, package.json, postinstall.mjs, and a 479-byte
stub `bin/opencode.exe`.)*

- **when it runs:** `npm install opencode-ai@1.18.25` (plain or `-g`) — a registry install
  runs `postinstall` per npm docs (scripts.md `npm install` table). **It DID run on this
  machine**: the spike's global install (t3) is proven by drift.md lines 119-127, 139-146 —
  `t3/bin/opencode.exe` (179,651,624 bytes) hashes to the AVX2 `x64` variant
  `ef06e41a35795066e95acde276a42fbbf85d7a683c2787f6a19ed20bcde9b6ff`, byte-identical to the
  digest-pinned T1-fetched `opencode-windows-x64` binary, and the 479-byte stub is gone. It
  never ran in t1 (`--ignore-scripts`, FETCH.md §"Verification that scripts did NOT run").
- **what executes:** `node postinstall.mjs`. Code paths: platform/arch mapping to a package
  name `opencode-<platform>-<arch>` (lines 14-27); CPU probe `supportsAvx2()` (31-77);
  musl probe `isMusl()`, Linux-only (79-94); candidate list `packageNames()` (96-117) — on
  this host win32/x64: `[opencode-windows-x64, opencode-windows-x64-baseline]` or the reverse
  (line 115), decided by the AVX2 probe; `resolveBinary()` (119-124) locates the binary
  **inside the already-installed optionalDependency** via `require.resolve(name/package.json)`
  — no download; `copyBinary()` (146-156) `unlinkSync` + `linkSync`(fallback `copyFileSync`)
  + `chmodSync 0o755` into its own `bin/`; `verifyBinary()` (158-165); `main()` loop
  (167-182) tries candidates and only on copy/verify failure calls the `installPackage`
  fallback (126-144).
- **network:** none on the observed (t3) path — every branch that executed reads local files
  only. **Conditional:** the fallback `installPackage()` spawns
  `npm install --ignore-scripts --no-save --loglevel=error --prefix <tmp> <name>@<version>`
  (lines 132-136), which hits `registry.npmjs.org` if the package is not in cache. The version
  is **pinned** from `packageJson.optionalDependencies` (line 127) — all 12 entries exact
  `"1.18.25"` (t1 `opencode-ai/package.json:20-33`), and `--ignore-scripts` is passed to the
  child (line 134). This fallback triggers only when no candidate platform package is locally
  present — not the case on this mount (both win32-x64 variants were installed, t3 tree).
- **filesystem writes:** (a) `__dirname/bin/opencode.exe` — the package's own bin dir only
  (lines 29, 146-156); (b) fallback only: `os.tmpdir()/opencode-install-*` via `mkdtempSync`
  (line 130), removed in `finally` `rmSync` (line 142). Nothing outside the package dir + tmp.
- **spawned processes:** (1) `powershell.exe` (then `pwsh.exe`/`pwsh`/`powershell` fallbacks)
  with `-NoProfile -NonInteractive -Command` running an `Add-Type` P/Invoke of
  `kernel32!IsProcessorFeaturePresent(40)` (lines 56-65) — a read-only CPU-feature probe,
  3 s timeout, `windowsHide`; (2) fallback-only `npm install` (above); (3) the copied binary
  itself: `spawnSync(targetBinary, ["--version"])` (line 159) — single fixed argument,
  `stdio: "ignore"` — i.e. it **executes the freshly installed OpenCode CLI binary** to check
  it starts. That binary is the digest-pinned first-party artifact (`ef06e41a…` above), not
  third-party code; on macOS/Linux the equivalents are `sysctl hw.optional.avx2_0` (44-47) and
  `ldd --version` (89) — not this mount.
- **verdict:** adjudicated: accept — this is the S1-lefthook-shaped case: a fully readable,
  package-scoped installer whose only spawn-heavy step is a documented CPU probe and whose
  output is a pinned, registry-digested first-party binary. Its one network-capable branch is
  a version-pinned, `--ignore-scripts` npm fetch used only when the platform package is
  missing, and its `--version` verification spawn executes the same pinned binary the gate
  already inventories. The local execution record (t3) corroborates the code reading exactly:
  it selected the AVX2 variant, replaced the stub, and nothing else in the tree changed
  (drift.md: binary drift NONE; every installed `opencode.exe` recomputes to the manifest
  sha256). Residual exposure (not adjudication-blocking, for Task 10's record): install-time
  execution of the platform binary means a compromised publisher build would run at
  `--version` privilege on install — mitigated by the version pin + integrity digests and by
  the fact that the binary is the product itself, the thing CR-4 is gating on other axes.

---

## t2 — msgpackr · prepare — C:\Users\mianx\.config\opencode\node_modules\msgpackr\package.json (scripts.prepare → scripts.build)

- **when it runs:** declared `msgpackr/package.json:26` — `"prepare": "npm run build"`, which
  npm expands to `build` (line 24): `rollup -c && cpy index.d.ts . --rename=index.d.cts && cpy
  pack.d.ts . --rename=pack.d.cts && cpy unpack.d.ts . --rename=unpack.d.cts`. In npm's
  documented lifecycle `prepare` runs on local no-arg install / `npm pack` / `npm publish` /
  git-dependency install (scope-note.md:22-30; scripts.md:42-49) — npm does **not** run a
  registry dependency's own `prepare` on a tarball install; it stays in the scan's superset
  and is adjudicated anyway (common context above). Runtime-tree reality: msgpackr 2.1.0
  arrived here as a registry tarball (lockfile `resolved` …msgpackr-2.1.0.tgz, integrity
  `sha512-p/pBCVO63Csvv…`) installed by OpenCode's runtime installer on 2026-09-01.
- **what executes:** `npm run build` → `rollup -c` reads `rollup.config.js` (89 lines, read
  in full): 7 bundle jobs, inputs `node-index.js`/`index.js`/`unpack.js`/`tests/test.js`,
  outputs to `dist/node.cjs`, `dist/index.js`, no-eval/min variants, `dist/test.js`; plugins
  `@rollup/plugin-terser`, `@rollup/plugin-json`, `@rollup/plugin-replace` (lines 1-3) —
  pure local code transforms (the `replace({Function: 'BlockedFunction'})` jobs, lines 28,
  40, 64, build the eval-free variants). Then `cpy` copies the shipped `.d.ts` files to
  `.d.cts` twins. **On this mount none of this can run:** `rollup` (^3.2.5) and `cpy-cli`
  (^4.1.0) are `devDependencies` (package.json:92) and are absent from the t2 tree (29 packages,
  no rollup/cpy; no `.bin` shims) → the script fails at its first command
  (`rollup: command not found`, exit 127) and `cpy` is never reached. It is also pointless
  here: the tarball already ships the build outputs (`files`: `['/dist', '*.md', '/*.js',
  '/*.ts', '/*.cts']`, package.json:82-88; `dist/` present fully populated incl. `.map`s, and
  `index.d.cts` / `pack.d.cts` / `unpack.d.cts` present) — this is a publish-time build hook,
  not an install-time behavior.
- **network:** none. No fetch/import of anything remote in `rollup.config.js` or the npm
  script strings; the only conceivable network would be npm resolving the `devDependencies`
  — which are not installed in this tree and are not installed by a consumer install.
- **filesystem writes:** (hypothetically, with dev deps present — e.g. in the publisher's
  repo) `dist/*` and `*.d.cts` **inside the msgpackr package dir only**. On this mount:
  none — the script cannot get past command-not-found.
- **spawned processes:** none on this mount (fails before spawning anything). With dev deps
  present it would spawn `rollup` and `cpy` child processes — local build tools operating on
  package-local files.
- **verdict:** adjudicated: accept — the script is a self-contained bundler invocation whose
  inputs and outputs are all inside the package, with no network reach and no process spawn
  beyond local build tools; in this tree it is doubly inert (npm does not run a registry
  dependency's `prepare`, and its build tools are not even present). The shipped artifacts it
  would produce are already in the tarball and digest-locked by the lockfile integrity.

---

## t2 — msgpackr-extract · install — C:\Users\mianx\.config\opencode\node_modules\msgpackr-extract\package.json (scripts.install)

- **when it runs:** declared `msgpackr-extract/package.json:12` — `"install":
  "node-gyp-build-optional-packages"`. npm runs the `install` hook of a registry dependency
  (scripts.md `npm install`/`npm ci` tables: `preinstall`/`install`/`postinstall`), so of the
  five t2 findings this is the one **npm itself would run on any plain install**. Whether
  OpenCode's runtime installer executes it is engine-dependent, but either way the executed
  code is fully read (below). msgpackr-extract 3.0.4 (optional dep in the lockfile,
  integrity `sha512-4kmO/MdyUIkLI…`) is the native accelerator for msgpackr.
- **what executes:** the command resolves via the npm `.bin` shim
  (`node_modules/.bin/node-gyp-build-optional-packages` → `exec node
  ../node-gyp-build-optional-packages/bin.js`) to **`node-gyp-build-optional-packages@5.2.2`**
  (its only declared dependency, pinned exact — package.json:26; lockfile integrity
  `sha512-s+w+rBWnpTMwS…`). Transitive read in full: `bin.js` (83 lines), `build-test.js`
  (19 lines), `index.js` (6 lines), `node-gyp-build.js` (236 lines). Flow: `bin.js` checks
  `--build-from-source`/`npm_config_build_from_source` (67-69) — absent → runs the package's
  second bin `node-gyp-build-optional-packages-test` (line 8) → `build-test.js` reads cwd's
  package.json (no `prebuild.test` field exists in msgpackr-extract's manifest, so line 18
  falls through) → `require('./')()` → `node-gyp-build.js` `load.resolve(cwd)`: checks
  `build/Release`, `build/Debug`, `prebuilds/` (none exist in the package — all reads are
  try/catch'd `readdirSync`), then resolves the **platform package**
  `@msgpackr-extract/msgpackr-extract-win32-x64` (lines 56-60; one of six pinned
  `optionalDependencies`, package.json:37-44, all exact `3.0.4`; installed from the registry,
  integrity `sha512-CmCXPQrkbwExx…`) and loads its shipped `node.napi.node` (runtime-agnostic
  N-API flavor; `node.abi115.node` also present for older ABIs). If that load exits 0,
  `bin.js`'s callback sees no error and **does nothing further** (lines 8-16) — happy path
  complete: a load-and-verify, nothing built, nothing written.
- **network:** none in any read file — `bin.js`, `build-test.js`, `index.js`,
  `node-gyp-build.js` contain no fetch/socket/https and spawn no downloader. (Guard: the
  package's *other* bin `bin/download-prebuilds.js`, read in full, does run
  `prebuildify-ci download` — but it is invoked only by its explicit command name
  (`download-msgpackr-prebuilds`), never by this `install` script.) Conditional second-order
  exception, only on the failure path: `bin.js:21-40` `build()` spawns `node-gyp rebuild`,
  and node-gyp (the tool) downloads Node headers from nodejs.org when it compiles. That
  branch requires the prebuilt binding to have failed to load AND node-gyp to be findable —
  it is **neither in the t2 tree nor a declared dependency** (only
  `node-gyp-build-optional-packages` is), and the prebuilt load demonstrably succeeds here
  (below).
- **filesystem writes:** none on the observed path — the resolver only reads. A source
  compile would write `build/` inside msgpackr-extract only; **no `build/` directory exists**
  in the installed package (listing: LICENSE, README.md, bin/, binding.gyp, index.js,
  package.json, src/), so no local compilation happened; the `.node` binaries in use came
  from the registry-pinned platform package tarball.
- **spawned processes:** `node` (via the `.bin` shim chain) — twice on the happy path
  (bin.js, then build-test.js), each package-local; conditionally `node-gyp rebuild`
  (unreachable as evidenced above). No shell-outs to anything else; no PowerShell anywhere.
- **verdict:** adjudicated: accept — the execution chain is four small, fully-read MIT files
  (Mathias Buus / Kris Zyp, prebuildify ecosystem) that at install time only **load-test a
  digest-pinned prebuilt binary** and, on success, exit; every branch that could write or
  reach the network requires a tool (node-gyp) that is not present and a failure that did not
  occur (no `build/` artifacts). The native binary itself is a scan-inventoried artifact
  (Task 3, `sha256-manifest.txt`), carried under the lockfile's registry integrity — the
  in-process load of it at runtime is the package's declared function, not an install-time
  surprise.

---

## t2 — undici · prepare — C:\Users\mianx\.config\opencode\node_modules\undici\package.json (scripts.prepare)

- **when it runs:** declared `undici/package.json:109` — `"prepare": "husky && node
  ./scripts/platform-shell.js"`. Same `prepare` framing as msgpackr (npm docs run it on
  local/pack/publish/git-dep installs; registry-dependency installs do not run it; kept in
  the scan superset — common context above). undici 7.29.0 (registry tarball, lockfile
  integrity `sha512-IDxfleLmmbSsk…`) is Node's official HTTP/1.1+fetch client, pulled in by the
  runtime tree as a transitive dependency; it is the library OpenCode's SDK stack uses for
  egress, not a lifecycle actor.
- **what executes:** first command `husky` — `husky@^9.0.7` is an undici **devDependency**
  (package.json:125) and is **absent from the t2 tree** (29 packages, no husky) →
  `husky: command not found`
  (exit 127) → npm aborts the script; the second half is unreachable **on this mount**. Both
  halves characterized anyway, per the full-read standard: (a) `husky` 9.0.7 (published
  artifact, unpkg): `bin.js` → `index.js`, which checks `existsSync('.git')` in its cwd and
  on failure returns the string `.git can't be found` — no spawn, no writes;
  `C:\Users\mianx\.config\opencode\node_modules\undici` contains no `.git` (hidden-file
  listing), and no parent is a repo (git check above), so even a present husky could only
  no-op/error. With a repo present it would run `git config core.hooksPath .husky/_` and
  scaffold `.husky/_` — repo-internal, no network (S1-adjacent tool class). (b)
  `scripts/platform-shell.js` is **not shipped in the registry tarball** — the installed
  `undici/scripts/` contains only `strip-comments.js`. Read from the upstream
  `nodejs/undici` `v7.29.0` tag for completeness: 15 lines — on win32 only,
  `writeFileSync(resolve(__dirname, '.npmrc'), 'script-shell = "…powershell.exe"\n')`, i.e. a
  package-internal config file telling npm to use PowerShell for script shells on Windows;
  no network, no spawn, no external writes.
- **network:** none. Neither `husky` (characterized above) nor `platform-shell.js` (15
  lines, quoted) performs any network operation; the failure-on-first-command reality makes
  even that moot.
- **filesystem writes:** none possible on this mount (first command fails; and the one
  write the full script could make — an `.npmrc` inside undici's own dir — is empirically
  absent: no `.npmrc` in the installed package, proof `platform-shell.js` never executed
  here). Hypothetical scope: undici's own directory only.
- **spawned processes:** none on this mount. Hypothetically `git config` (husky, repo
  present) — none here.
- **verdict:** adjudicated: accept — the script is a development-repo hook chain (git-hooks
  scaffolder + a Windows npm script-shell preference file) whose every constituent is either
  not shipped to consumers (`platform-shell.js`), not installed (husky is a devDependency),
  or gated on a git repository this tree does not have; all hypothetical writes are
  package-internal and there is no network reach in any path. The registry tarball cannot
  execute this script to effect even in a worst-case engine policy.

---

## t2 — uuid · prepare — C:\Users\mianx\.config\opencode\node_modules\uuid\package.json (scripts.prepare)

- **when it runs:** declared `uuid/package.json:87` — `"prepare": "lefthook install"`. Same
  `prepare` framing as the two above (registry-dependency installs do not run it; scan
  superset keeps it; common context above). uuid 14.0.2 (registry tarball, lockfile
  integrity `sha512-xZe/16rV4aa+H…`) is the standard UUID generator, a transitive runtime dep.
- **what executes:** the command `lefthook` — pinned exact `1.11.13` as a uuid
  **devDependency** (package.json:50) and **absent from the t2 tree** (no lefthook package, no `.bin`
  shim) → `lefthook: command not found` (exit 127) → script fails; nothing else runs
  **on this mount**. Characterized anyway (full-read standard, and direct continuity with
  the S1 ruling on this exact tool family): `lefthook@1.11.13`'s published manifest has
  `bin: bin/index.js`, no regular dependencies, and ten platform binaries pinned `1.11.13`
  via `optionalDependencies`; the wrapper (read from the published artifact) does
  `spawn(getExePath(), process.argv.slice(2))` — argument passthrough to the pinned platform
  binary, no download logic in the wrapper. Its `install` subcommand configures git hooks
  **in the current repository** (the S1 ruling adjudicated the sibling installer script of
  this same project as worktree-scoped, no network, refusing to touch user-owned
  `core.hooksPath`); `C:\Users\mianx\.config\opencode\node_modules\uuid` is not inside any
  git repository (verified above), so there is nothing for it to configure. uuid's tarball
  also ships no `lefthook.yml` (`files`: `['dist', 'dist-node', '!**/test']`, package.json:37;
  installed dir: LICENSE.md, README.md, dist, dist-node, package.json) — lefthook with no
  config file and no repo is inert.
- **network:** none. The invoked command is not installed; even present, `lefthook install`
  makes no network calls (S1 evidence + pinned-binary distribution model above).
- **filesystem writes:** none possible on this mount. Hypothetically `.git`-internal hook
  files in a repo root — which this tree lacks.
- **spawned processes:** none on this mount. Hypothetically the pinned lefthook platform
  binary running `git` config/plumbing — not reachable.
- **verdict:** adjudicated: accept — identical shape to the S1 lefthook ruling but weaker
  even than that: the tool is a devDependency absent from the consumer tree, its
  configuration file is not shipped, and the only filesystem it could touch (a git
  repository's hooks) does not exist on this mount. No execution path, actual or
  hypothetical, writes outside a repo or touches the network.

---

## t2 — which · prepublish — C:\Users\mianx\.config\opencode\node_modules\which\package.json (scripts.prepublish)

- **when it runs:** declared `which/package.json:27` — `"prepublish": "npm run changelog"`.
  npm CLI v11 docs list `prepublish` in the `npm ci` and `npm install` lifecycle tables
  (scripts.md:112-120, 129-139; the legacy behavior documented at scripts.md:78 —
  "the npm CLI has run the `prepublish` script for both `npm publish` and `npm install`"),
  and the scan keeps it in scope for exactly that reason (scope-note.md:29-30). For a
  registry-tarball dependency npm does not run the dependency's `prepublish`; adjudicated
  anyway per the superset policy. which 2.0.2 (registry tarball, lockfile integrity
  `sha512-BLI3Tl1TW3Pvl…`) is isaacs' `which(1)`-style PATH lookup library — a tiny,
  dormant-at-install transitive dep (it is itself the dependency of `cross-spawn`).
- **what executes:** `npm run changelog` auto-runs its pre/post hooks (npm run-scripts
  semantics): `prechangelog` = `bash gen-changelog.sh` (line 28) → `changelog` = `git add
  CHANGELOG.md` (line 29) → `postchangelog` = `git commit -m 'update changelog - <version>'`
  (line 30). **The chain dies at step 1 on this mount:** `gen-changelog.sh` is not shipped —
  `files` is `['which.js', 'bin/node-which']` (lines 33-36) and the installed package
  contains no such file → `bash: gen-changelog.sh: No such file or directory` (exit 127) →
  npm aborts the run-chain; `git add`/`git commit` are never reached (and could not act
  anyway: no git repository at or above this tree — verified above). Characterized anyway:
  `gen-changelog.sh` read from upstream `isaacs/node-which` `v2.0.2` — 9 lines:
  `git log --first-parent --pretty=format:'%s'` piped through `grep -v '^update changelog'`
  and two `perl -p` one-liners, redirected into `CHANGELOG.md` — a local git-history →
  markdown text transform.
- **network:** none — `bash`/`git log`/`grep`/`perl` on local files; no fetch anywhere in
  the chain.
- **filesystem writes:** none possible on this mount (first command fails against a file
  that does not exist). Hypothetically, in the publisher's repo: rewrite `CHANGELOG.md` in
  cwd and stage/commit it — repo-internal only. The `CHANGELOG.md` present in the installed
  tree is the tarball-shipped copy (npm always packs README/LICENSE/CHANGELOG regardless of
  `files`), timestamped at install time, not a script artifact.
- **spawned processes:** none on this mount. Hypothetically `bash`, `git log`, `perl`,
  `grep`, `git add`, `git commit` — all local VCS plumbing.
- **verdict:** adjudicated: accept — a maintainer's changelog-regeneration convenience
  chain whose first link references a file the package does not even ship to consumers, and
  whose remaining links are git plumbing that requires the repository this tree
  definitively lacks. Zero install-time effect, zero network, zero external writes on this
  or any registry-install mount.

---

### Count cross-check (brief Step 3)

- `## ` dossier sections in this file: **6** (t1 dual-instance with t3; t2 msgpackr;
  t2 msgpackr-extract; t2 undici; t2 uuid; t2 which). This cross-check deliberately uses a
  `###` heading so a mechanical `grep -c '^## '` returns exactly the dossier count.
- Findings covered from `scan.json` Step 1 enumeration: **7 of 7**
  (t1 opencode-ai postinstall + t2 msgpackr prepare + t2 msgpackr-extract install +
  t2 undici prepare + t2 uuid prepare + t2 which prepublish + t3 opencode-ai postinstall),
  via 6 dossiers — t1/t3 = one byte-identical script, sha256-verified.
- Verdicts: **6/6 accept, 0 escalate.** No escalation line is owed to the Task 10 report
  from this adjudication. (Separately and NOT from here: the `@ai-sdk/provider` two-majors /
  `^3.0.41` floating-range hazard remains Task 10's hazard/A-1 input per the brief.)
