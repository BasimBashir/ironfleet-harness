# Drift - installed/runtime trees vs T1 fresh fetch (S7a / A-8)

- generated: 2026-09-03
- T1 reference lockfile: `C:/Users/mianx/OneDrive/Desktop/opencode-audit/fresh-package-lock.json` (14 pinned entries)
- T1 reference tree: `C:/Users/mianx/OneDrive/Desktop/opencode-audit/fresh/node_modules`
- Version source for T3/T2: every `package.json` found recursively under each tree root.
- Status keys: **match** = same version in T1 lock; **DRIFT** = both present, versions differ;
  **not-in-t1** = absent from the T1 lock (a set difference, not a version mismatch).

## t3 (global install) - `%APPDATA%/npm/node_modules/opencode-ai`

- distinct packages found: 3

- opencode-ai: 1.18.25 vs t1 1.18.25 - **match**
- opencode-windows-x64: 1.18.25 vs t1 1.18.25 - **match**
- opencode-windows-x64-baseline: 1.18.25 vs t1 1.18.25 - **match**

## t2 (`~/.config/opencode` - runtime tree)

- distinct packages found: 32

- @ai-sdk/openai-compatible: 3.0.41 vs t1 None - not-in-t1
- @ai-sdk/provider: 3.0.8 + 4.0.9 vs t1 None - MULTIPLE-VERSIONS
- @ai-sdk/provider-utils: 5.0.34 vs t1 None - not-in-t1
- @msgpackr-extract/msgpackr-extract-win32-x64: 3.0.4 vs t1 None - not-in-t1
- @opencode-ai/plugin: 1.18.25 vs t1 None - not-in-t1
- @opencode-ai/sdk: 1.18.25 vs t1 None - not-in-t1
- @standard-schema/spec: 1.1.0 vs t1 None - not-in-t1
- @workflow/serde: 4.1.0 vs t1 None - not-in-t1
- cross-spawn: 7.0.6 vs t1 None - not-in-t1
- detect-libc: 2.1.2 vs t1 None - not-in-t1
- effect: 4.0.0-beta.83 vs t1 None - not-in-t1
- eventsource-parser: 3.1.1 vs t1 None - not-in-t1
- fast-check: 4.9.0 vs t1 None - not-in-t1
- find-my-way-ts: 0.1.6 vs t1 None - not-in-t1
- ini: 7.0.0 vs t1 None - not-in-t1
- isexe: 2.0.0 vs t1 None - not-in-t1
- json-schema: 0.4.0 vs t1 None - not-in-t1
- kubernetes-types: 1.30.0 vs t1 None - not-in-t1
- msgpackr: 2.1.0 vs t1 None - not-in-t1
- msgpackr-extract: 3.0.4 vs t1 None - not-in-t1
- multipasta: 0.2.8 vs t1 None - not-in-t1
- node-gyp-build-optional-packages: 5.2.2 vs t1 None - not-in-t1
- path-key: 3.1.1 vs t1 None - not-in-t1
- pure-rand: 8.4.2 vs t1 None - not-in-t1
- shebang-command: 2.0.0 vs t1 None - not-in-t1
- shebang-regex: 3.0.0 vs t1 None - not-in-t1
- toml: 4.3.0 vs t1 None - not-in-t1
- undici: 7.29.0 vs t1 None - not-in-t1
- uuid: 14.0.2 vs t1 None - not-in-t1
- which: 2.0.2 vs t1 None - not-in-t1
- yaml: 2.9.0 vs t1 None - not-in-t1
- zod: 4.1.8 vs t1 None - not-in-t1

- t2 totals: 0 match / 0 DRIFT / 31 not-in-t1 (out of 32)

### t2 package-name reconciliation (why 50 scanned files -> 32 distinct names)

- t2 `package.json` files scanned: 50
- with a `name` field: 34
- without a `name` field (package sub-path manifests such as `zod/v4/classic`, plus t2's own
  root `package.json`, which carries only `dependencies`): 16
- distinct names: 32 (= 34 named files - 2 duplicate-name files)

- names installed more than once: 1

**`@ai-sdk/provider` is present at TWO MAJOR VERSIONS in the t2 tree:**

- `3.0.8` - `node_modules/@ai-sdk/provider/package.json`
- `4.0.9` - `node_modules/@ai-sdk/openai-compatible/node_modules/@ai-sdk/provider/package.json`
- `4.0.9` - `node_modules/@ai-sdk/provider-utils/node_modules/@ai-sdk/provider/package.json`

This is a direct consequence of the floating range the scanner flagged:
`@ai-sdk/openai-compatible ^3.0.41` resolved to `3.0.41` (the bottom of its range) and pulled
its own `@ai-sdk/provider` 4.0.9, while the tree also carries a top-level `@ai-sdk/provider`
3.0.8. Two majors of one package in a single runtime tree means the actually-loaded provider
code path cannot be determined from the manifest alone - it depends on which copy OpenCode's
runtime resolver picks. **Escalate to Task 7** alongside the `^3.0.41` adjudication.

## t2 lockfile - resolved versions behind the floating ranges

- `@ai-sdk/openai-compatible` declared `^3.0.41` (floating) in `C:\Users\mianx\.config\opencode\package.json`
  -> resolved by t2 lockfile to **3.0.41** (`node_modules/@ai-sdk/openai-compatible`)
- `provider.ollama-local.npm` (non-dependency floating ref, spec `(none)`) - no lockfile resolution to check

## t3b - planned fourth tree label (sibling platform package)

- planned path: `C:/Users/mianx/AppData/Roaming/npm/node_modules/opencode-windows-x64`
- exists: **False**

The brief expected the platform package to sit as a **sibling** of `opencode-ai` in the global
`node_modules`. It does not. On this host the global install nests the platform packages
**inside** `opencode-ai`:

- `%APPDATA%/npm/node_modules/` contains `opencode-ai` and `pnpm` only - no `opencode-*` siblings.
- `%APPDATA%/npm/node_modules/opencode-ai/node_modules/opencode-windows-x64` - present.
- `%APPDATA%/npm/node_modules/opencode-ai/node_modules/opencode-windows-x64-baseline` - present.

**Consequence: t3b is skipped as a separate label.** Nothing is lost - the scanner walks the tree
recursively, so both nested platform packages were already inventoried **under `t3`** (see
`sha256-manifest.txt` entries `t3/node_modules/opencode-windows-x64*/bin/opencode.exe`, and
`mechanical-scan.md` line `tree t3 ... native binaries: 3`). The intent behind t3b - inventory the
shipped binary from the installed side - is met by `t3` itself.

## shipped binary sha256 (paths derived from `sha256-manifest.txt`)

- t1 `opencode.exe` entries in manifest: 3
- t3 `opencode.exe` entries in manifest: 3

### T1 reference variants (fresh fetch, scripts never run)

- `x64-baseline` - `t1/opencode-windows-x64-baseline/bin/opencode.exe`
  - sha256 `954f2869f9cc2131b03cb6aa7ee50c70601c1a56811fb5bcf749b827c970d290` (179,651,624 bytes) - recomputed from disk: verified
- `x64` - `t1/opencode-windows-x64/bin/opencode.exe`
  - sha256 `ef06e41a35795066e95acde276a42fbbf85d7a683c2787f6a19ed20bcde9b6ff` (179,651,624 bytes) - recomputed from disk: verified

### T3 counterparts (installed side)

- `t3/bin/opencode.exe`
  - sha256 `ef06e41a35795066e95acde276a42fbbf85d7a683c2787f6a19ed20bcde9b6ff` (179,651,624 bytes) - recomputed from disk: verified
  - verdict: postinstall OUTPUT - no t1 counterpart (this is the file postinstall.mjs creates)
- `t3/node_modules/opencode-windows-x64-baseline/bin/opencode.exe`
  - sha256 `954f2869f9cc2131b03cb6aa7ee50c70601c1a56811fb5bcf749b827c970d290` (179,651,624 bytes) - recomputed from disk: verified
  - verdict: **MATCH** t1 `x64-baseline`
- `t3/node_modules/opencode-windows-x64/bin/opencode.exe`
  - sha256 `ef06e41a35795066e95acde276a42fbbf85d7a683c2787f6a19ed20bcde9b6ff` (179,651,624 bytes) - recomputed from disk: verified
  - verdict: **MATCH** t1 `x64`

### t1 stub vs installed binaries

- t1 `opencode-ai/bin/opencode.exe` (publisher stub shipped in the tarball): `21c366f53283d5b5e1cdbbec2aafc98286b4c1075a4c3d5afd5ce1f5c9bf46dd`, 479 bytes
- installed t3 binaries carrying the stub hash: none
- the 479-byte stub hash appears nowhere in the installed tree: every installed `opencode.exe` is a
  179,651,624-byte platform binary. The stub is T1-only evidence that the postinstall never ran
  there; on the installed side (t3) the postinstall DID run and replaced it.

## Drift verdict

- **binary drift: NONE.** Every t3 `opencode.exe` recomputes from disk to the sha256 recorded in
  `sha256-manifest.txt` and is byte-identical to the matching t1 variant:
  `opencode-windows-x64` -> `ef06e41a35795066e95acde276a42fbbf85d7a683c2787f6a19ed20bcde9b6ff`;
  `opencode-windows-x64-baseline` -> `954f2869f9cc2131b03cb6aa7ee50c70601c1a56811fb5bcf749b827c970d290`.
- the installed `t3/bin/opencode.exe` hashes identical to
  `t3/node_modules/opencode-windows-x64/bin/opencode.exe`: the global install's postinstall ran,
  selected the AVX2 (`x64`) variant, and installed it. That execution is exactly what
  `--ignore-scripts` prevented in T1.
- **version drift: none within the shared package set.** Every package name present in both a
  scanned tree and the T1 lockfile resolves to `1.18.25` on both sides. t2 is a different package
  set (OpenCode's runtime-installed plugins/deps), so its entries report `not-in-t1` - a set
  difference, not a version conflict.
- floating ranges are tracked in `mechanical-scan.md`; t2's `@ai-sdk/openai-compatible ^3.0.41`
  resolves to `3.0.41` in t2's own lockfile (see above).

## Adjustments to the brief's heredoc, and why

1. `../opencode-audit/...` relative to `harness-core/` does not exist - that path assumes the
   sandbox is a sibling of `harness-core`. It is a sibling of the `IronFleet harness` folder:
   `C:/Users/mianx/OneDrive/Desktop/opencode-audit/`. All T1 paths were passed as absolute.
   (The brief anticipated exactly this class of problem: "If the fresh exe sits elsewhere, adjust
   by reading `data/opencode-audit/sha256-manifest.txt` for the `t1/...opencode.exe` entry".)
2. The heredoc's `fresh_exe` path ternary was replaced by manifest-derived paths as instructed:
   `t1/...opencode.exe` and `t3/...opencode.exe` entries are read out of `sha256-manifest.txt` and
   paired by variant, so no assumption is baked in about which variants exist. Both variants exist
   on both sides here, so both are compared (the instruction anticipated only one would be).
3. `tree_versions` was keyed on package name holding a **set** of versions, so a name installed at
   two nesting depths cannot silently collapse to one value; a collision would report
   `MULTIPLE-VERSIONS` rather than an arbitrary winner. No collisions occurred.
4. Every sha256 quoted above is recomputed from disk by this script and cross-checked against the
   committed manifest - the manifest is not trusted as input to its own verdict.

