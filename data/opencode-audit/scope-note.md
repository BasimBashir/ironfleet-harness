# Scan scope note — what the A-8 mechanical scan does and does not cover (S7a)

Companion to `scan.json`, `mechanical-scan.md`, `sha256-manifest.txt`, and `drift.md`.
This file discloses the scan's own scope so the gate report can quote the record without
overstating it. It changes no finding and no number in those four artifacts.

## 1. The scanner's lifecycle tuple

`src/harness/security/opencode_precheck.py` defines:

    LIFECYCLE = ("preinstall", "install", "postinstall", "prepare", "prepublish")

A `package.json` `scripts` entry whose name is in that tuple is reported as a lifecycle
finding and counted as CRITICAL until adjudicated. Any other `scripts` name — including
npm's publish-time-only hooks — is invisible to the scan.

### Why the publish-time-only hooks are excluded

npm runs a fixed subset of lifecycle hooks when a package is installed **from the registry**
as a dependency. Per the npm CLI documentation (`npm help scripts`, npm CLI v11):

- `preinstall`, `install`, `postinstall` — run on install, including a registry dependency
  install and a global install.
- `prepare` — runs on a local `npm install` with no package arguments, on `npm pack`,
  `npm publish`, and when installing a **git dependency** (the package is built from source
  before it is packed). npm's documentation lists `prepare` in the install lifecycle, and the
  scanner keeps it in scope for that reason: it is a build hook, so it is treated as
  install-adjacent rather than inert.
- `prepublish` (deprecated) — the docs state it "does not run during `npm publish`, but does
  run during `npm ci` and `npm install`". Kept in the tuple for that reason.
- `prepublishOnly` — "runs BEFORE the package is prepared and packed, ONLY on `npm publish`".
  **Never runs on an install.**
- `prepack` — runs on `npm pack`, `npm publish`, and git-dependency install. **Does not run on
  a registry install** — no packing happens, the tarball already exists.
- `postpack`, `publish`, `postpublish` — parts of `npm publish` only.

The excluded names therefore cannot execute during a registry `npm install`. Note the tuple is
a deliberate **superset** of what a registry install actually runs: it also flags `prepare` and
`prepublish`, which only fire in adjacent scenarios (local no-arg install, `npm ci`, git deps,
`npm pack`). The scan over-flags rather than under-flags — it cannot miss an install-time
script by being too narrow.

## 2. Secondary inventory — publish-time-only scripts present in the scanned trees

These are **NOT** counted in `mechanical-scan.md`'s "lifecycle scripts (CRITICAL until
adjudicated)" figure, because they cannot run at install time. They are listed here so the
record is honest about what the tuple excludes. Re-derived by sweeping all three trees for
every name in `prepublishOnly`, `prepack`, `postpack`, `publish`, `postpublish`.

**8 publish-time-only scripts found, all in `t2`.** `t1` and `t3` have none.

### `prepublishOnly` — 5 found

- `t2` · `eventsource-parser` · `prepublishOnly`
  - path: `C:/Users/mianx/.config/opencode/node_modules/eventsource-parser/package.json`
  - command: `npm run build`
- `t2` · `toml` · `prepublishOnly`
  - path: `C:/Users/mianx/.config/opencode/node_modules/toml/package.json`
  - command: `npm run build`
- `t2` · `uuid` · `prepublishOnly`
  - path: `C:/Users/mianx/.config/opencode/node_modules/uuid/package.json`
  - command: `npm run build`
- `t2` · `yaml` · `prepublishOnly`
  - path: `C:/Users/mianx/.config/opencode/node_modules/yaml/package.json`
  - command: `npm run clean && npm test && npm run build`
- `t2` · `zod` · `prepublishOnly`
  - path: `C:/Users/mianx/.config/opencode/node_modules/zod/package.json`
  - command: `tsx ../../scripts/check-versions.ts`

### `prepack` — 1 found

- `t2` · `uuid` · `prepack`
  - path: `C:/Users/mianx/.config/opencode/node_modules/uuid/package.json`
  - command: `npm run build -- --no-pack`

### `postpublish` — 2 found

- `t2` · `isexe` · `postpublish`
  - path: `C:/Users/mianx/.config/opencode/node_modules/isexe/package.json`
  - command: `git push origin --all; git push origin --tags`
- `t2` · `which` · `postpublish`
  - path: `C:/Users/mianx/.config/opencode/node_modules/which/package.json`
  - command: `git push origin --follow-tags`

Total: 8.

## 3. Install-time scope — the criticals stand

The install-time execution surface is exactly the tuple above:
`preinstall` / `install` / `postinstall` / `prepare` / `prepublish`.

A full sweep of all three trees for **every** `scripts` key confirmed that those five names
produce exactly the 7 findings already recorded in `scan.json` /
`mechanical-scan.md`, and nothing more:

- `t1` · `opencode-ai` · `postinstall` · `opencode-ai/package.json`
- `t2` · `msgpackr` · `prepare` · `node_modules/msgpackr/package.json`
- `t2` · `msgpackr-extract` · `install` · `node_modules/msgpackr-extract/package.json`
- `t2` · `undici` · `prepare` · `node_modules/undici/package.json`
- `t2` · `uuid` · `prepare` · `node_modules/uuid/package.json`
- `t2` · `which` · `prepublish` · `node_modules/which/package.json`
- `t3` · `opencode-ai` · `postinstall` · `package.json`

**The 7 criticals stand as the complete set for the install-time scope.** No
install-time script was missed by the tuple. The only names present in the trees outside that
tuple are the 8 publish-time-only entries inventoried in section 2, plus ordinary
developer-convenience scripts (`build`, `test`, `lint`, `pretest`, `postversion`, …). Those are
not installation lifecycle hooks: npm runs them only when the matching command (`npm test`,
`npm version`, `npm run build`) is invoked explicitly, never as part of `npm install`, so they
are out of scope for this review.

## 4. Sentence for Task 10 to quote

> The mechanical record's critical scope is install-time lifecycle scripts; publish-time-only
> scripts are inventoried here as non-critical.

