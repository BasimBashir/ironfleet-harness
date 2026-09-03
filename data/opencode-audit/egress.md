# A-8 Egress-point inventory — OpenCode 1.18.25 (CR-4 / S7a)

Intersection of three sources: shipped-binary strings, spike-log observations, and
config-schema + v1.18.25 source. Scope is OpenCode's OWN network behaviour — everything
that is NOT model traffic through the eventual egress gate (model-provider endpoints and
the `webfetch`/`websearch` tools are inventoried only to classify them as gate traffic).

**Binary scanned (one of the two ~180 MB variants, per plan):**

- Path: `C:\Users\mianx\OneDrive\Desktop\opencode-audit\fresh\node_modules\opencode-windows-x64\bin\opencode.exe`
- sha256 `ef06e41a35795066e95acde276a42fbbf85d7a683c2787f6a19ed20bcde9b6ff` — matches
  manifest entries `t1/opencode-windows-x64/bin/opencode.exe` and `t3/bin/opencode.exe`
  (`data/opencode-audit/sha256-manifest.txt`). The `-baseline` sibling was NOT scanned
  (its manifest hash `954f2869…` differs — the two 180 MB builds are not byte-identical).
- Deviation from the brief's heredoc: the exe was pinned by absolute path instead of
  `next(rglob("opencode*.exe"))` (rglob order is nondeterministic across three matches,
  including the 479 B stub). Extraction regexes are the brief's, unchanged; sha256 and
  counts were added to the header.

**Source counts:**

| Source | File | Count |
|---|---|---|
| Binary strings | `data/opencode-audit/binary-urls.txt` | 1040 URLs, 545 distinct hosts |
| Spike log (`~/.local/share/opencode/log/opencode.log`, 1 file) | `data/opencode-audit/log-urls.txt` | 52 URLs, 20 distinct hosts |
| Config schema (`https://opencode.ai/config.json`) + docs + v1.18.25 source | this file | 6 egress-relevant keys (`autoupdate`, `share`, `autoshare` (deprecated), `experimental.openTelemetry`, `disabled_providers`, `enabled_providers`) + `lsp`, `permission`, `tools`, `provider.*.npm` via docs/source |

## FINDINGS — default-on, no config-schema control (report items, not just rows)

- **F1 — `models.opencode.ai/api.json` catalog fetch is default-on and config-uncontrolled.**
  Fetched at startup in a background fiber and re-fetched every **60 minutes** while
  running; disk cache considered stale after 5 minutes. Disable exists only as env vars:
  `OPENCODE_DISABLE_MODELS_FETCH`, `OPENCODE_MODELS_URL`, `OPENCODE_MODELS_PATH` — there
  is NO `opencode.json` key for it. The spike did not set the env var; the 4.4 MB
  `~/.cache/opencode/models.json` on disk proves the fetch ran. Source:
  `packages/core/src/models-dev.ts` @v1.18.25 (`const source = Flag.OPENCODE_MODELS_URL || "https://models.opencode.ai"`,
  `${source}/api.json`, `Schedule.spaced("60 minutes")`, `Duration.minutes(5)`).
- **F2 — ripgrep executable downloaded from GitHub releases, no integrity check, no disable.**
  Lazy-triggered on first grep-tool use; stores `rg.exe` in `~/.cache/opencode/bin/`;
  **no sha256/signature verification** (only non-empty-size + extraction-success checks);
  **no config key and no env var** — the only aversions are a system `rg` found on PATH
  (preferred) and reuse of the cached copy. Observed live in the spike (log line
  `message="downloading ripgrep" url=https://github.com/BurntSushi/ripgrep/releases/download/15.1.0/ripgrep-15.1.0-x86_64-pc-windows-msvc.zip`;
  the 4.3 MB `rg.exe` is present on disk). Source: `packages/core/src/ripgrep/binary.ts`
  @v1.18.25.
- **F3 — tree-sitter `.wasm` grammar downloads from GitHub releases (binary-only evidence).**
  URLs such as `github.com/{alex-pinkus,anomalyco,elixir-lang,fwcd,ionide,…}/tree-sitter-*/releases/download/*.wasm`
  are present in the binary. No log evidence (not triggered by the spike), no fetch site
  pinned in the v1.18.25 lookups, and no config control found. Lower confidence than F2 by
  design — stated as binary-only.
- **F4 — `debug.bun.sh` (Bun runtime crash-report endpoint) compiled into the exe.**
  Present via the Bun runtime the exe is compiled with. Crash-only path; no call evidence
  in the spike log; no OpenCode config key. Gate-deny recommended; whether compiled Bun
  actually uploads on Windows panics is unverified here.

## Egress table

`default` = behaviour with an EMPTY config (the spike config is not assumed); `sources` =
which of binary(B) / log(L) / schema+source(S) evidenced the row.

| endpoint | purpose | default | config control | A-1 action | sources |
|---|---|---|---|---|---|
| `registry.npmjs.org` (install-time) | Package fetch: `opencode-ai` → platform exe package (FETCH.md pinned install) | n/a — invoked by `npm install`, not by the binary | npm scope / install procedure (FETCH.md) | no action (install-time, already pinned) | manifest, FETCH.md |
| `registry.npmjs.org` (runtime) | Runtime npm install of provider SDKs (`provider.*.npm` field — spike installed `@ai-sdk/openai-compatible` 3.0.41) and plugin SDK (`@opencode-ai/plugin` 1.18.25) into `~/.config/opencode/node_modules` | on when any provider/plugin declares an npm package (observed in spike) | config design: omit `npm` fields / `--pure` flag skips external plugins; no dedicated disable key | pin tarballs or gate-allow `registry.npmjs.org` scope only with lockfile pinning | L (lockfile artifact on disk), S (`package-lock.json` `resolved` URLs, config schema `provider.*.npm`) |
| `models.opencode.ai/api.json` | Model-provider catalog (names, endpoints, limits) | **on at startup + every 60 min** | env `OPENCODE_DISABLE_MODELS_FETCH` / `OPENCODE_MODELS_URL` / `OPENCODE_MODELS_PATH` — **no config key** → **F1** | set `OPENCODE_DISABLE_MODELS_FETCH` in harness env; gate-deny host | B, S (`packages/core/src/models-dev.ts`), disk cache artifact |
| `github.com/BurntSushi/ripgrep/releases/download/15.1.0/…zip` | ripgrep binary for grep tool; downloaded **and executed** as a subprocess | on at first grep use (lazy); no checksum; no key → **F2** | none (system `rg` on PATH is preferred if present) | pre-place pinned `rg.exe` on PATH; gate-deny `github.com/*/releases/download/*` AND its `*githubusercontent.com` 302 redirect targets (`objects.githubusercontent.com`, `release-assets.githubusercontent.com`) — a deny shaped only on the `github.com` path lets the download complete on the redirect leg | B, L (log line 146), disk (`~/.cache/opencode/bin/rg.exe`), S (`packages/core/src/ripgrep/binary.ts`) |
| `registry.npmjs.org/opencode-ai/<channel>` (npm channel); fallback `api.github.com/repos/anomalyco/opencode/releases/latest`; also `formulae.brew.sh`, `community.chocolatey.org`, `raw.githubusercontent.com/ScoopInstaller/…` | version check (latest) when `autoupdate` unset/true; unset ⇒ **enabled**, and patch releases auto-upgrade | **on when unset** | `autoupdate: false` (config key — spike used it; schema documents it) or env `OPENCODE_DISABLE_AUTOUPDATE`; `false` returns before any network call | keep `autoupdate: false` (already in harness config) | B, S (`packages/opencode/src/cli/upgrade.ts`, `…/installation/index.ts`) |
| `https://opencode.ai/install` | upgrade path for curl/unknown installs: downloads install script and **pipes it into a shell** | only on an actual upgrade (auto patch-upgrade when enabled, or manual) | `autoupdate: false` (removes the trigger) | none beyond `autoupdate: false`; note script-to-shell pattern in report | B, S (`installation/index.ts`) |
| `https://opncd.ai/api/share` (+ `/sync`, `/data`; enterprise override `enterprise.url`; console accounts → `{account url}/api/shares`) | session sharing — POST creates share, sync uploads **full transcript** (session, messages, parts, diffs, models) | **manual** — no egress unless the user runs `/share`; `auto` shares every new top-level session | `share: "manual"|"auto"|"disabled"` (schema enum; spike used `disabled`, which also blocks explicit share); env `OPENCODE_DISABLE_SHARE` | keep `share: "disabled"` | B (host `opncd.ai`), S (`packages/opencode/src/share/session.ts`, `…/share/share-next.ts`), docs (default manual) |
| `api.github.com/repos/{kotlin-lsp,lua-language-server,tinymist,clangd,texlab,zls}/releases/latest`, `api.releases.hashicorp.com/v1/releases/terraform-ls/latest`, + release-asset downloads | LSP server version checks and auto-install downloads when files of a matching language are opened | on-when-triggered (lazy; not triggered by the spike) | `lsp` config object with per-server `disabled: true` (e.g. `{ "pyright": { "disabled": true } }`); no global off-switch found | pre-pin needed LSP binaries; disable others via `lsp.*.disabled`; gate-deny the github.com release-download family AND its `*githubusercontent.com` redirect targets | B, S (LSP config docs; `packages/opencode/src/lsp/`) |
| `github.com/*/tree-sitter-*/releases/download/*.wasm` | tree-sitter grammars (TUI syntax highlighting) | unknown trigger (binary-only) | none found → **F3** | gate-deny `github.com/*/tree-sitter-*/releases/download/*.wasm` AND its `*githubusercontent.com` redirect targets; verify empirically in A-1 | B only |
| `api.opencode.ai` (`/get_github_app_installation`), `api.github.com/installation/token`, `api.github.com/graphql` | GitHub App / PR integration (`opencode github`, `opencode pr`) | off unless the user invokes it and authenticates | command-gated; not invoked by harness flows | no action (not used) | B, S (`packages/opencode/src/cli/cmd/github*.ts`) |
| GitHub host family: `codeload.github.com` (incl. `/gist/…`), `gist.githubusercontent.com`, `uploads.github.com` | gist/tarball upload-download paths for the GitHub integration | off unless invoked; no log evidence | command-gated (same as above) | covered by gate-deny on github.com family — the rule must also cover the release-download family AND its `*githubusercontent.com` redirect targets | B only |
| `opencode.ai/zen/v1` (+ `/zen`, `/zen/go/v1`) | Zen — OpenCode's hosted model gateway | off unless configured as a provider + authenticated | provider config; `enabled_providers`/`disabled_providers` | no action (becomes gate traffic if ever used) | B |
| `opencode.ai/{changelog.json,theme.json,desktop-theme.json,tui.json,config.json}` | literals in the binary. `config.json`/`tui.json` are `$schema` references (editor validation, not runtime calls); `changelog.json`/`theme.json` fetch sites were not pinned in the v1.18.25 lookups | unknown (no log evidence of any fetch) | none known | gate-deny `opencode.ai` (except schemas if needed); verify empirically | B only |
| `debug.bun.sh` | Bun runtime crash-report upload endpoint | crash-only; no call evidence | none at OpenCode level → **F4** | gate-deny host | B only |
| AI provider + cloud-plugin endpoints — ~540 hosts in the binary (`api.anthropic.com`, `api.openai.com`, `api.groq.com`, `api.mistral.ai`, `bedrock-*.amazonaws.com`, `integrate.api.nvidia.com`, plus plugin endpoints `api.cloudflare.com`, `api.vercel.com`, `api.digitalocean.com`, …) | model traffic for whichever providers are configured, plus cloud-provider plugin auth (catalog data + bundled SDKs; includes doc/example strings like `registry.mycorp.com`, `opencode.internal` that are not real endpoints) | on only per configured provider + credentials; spike contacted **only `127.0.0.1:11434`** (ollama-local) | provider config; `enabled_providers`/`disabled_providers`; no credentials ⇒ no call | through-gate model traffic (out of scope for this inventory by definition) | B (strings), L (`stream providerID=ollama-local`) |
| Arbitrary hosts via `webfetch`/`websearch` tools | model-directed HTTP fetches — any URL the model chooses (spike: `nzlii.org`, `legislation.govt.nz`, `api.legislation.govt.nz`, `duckduckgo.com`, `google.com`, `bing.com`, `en.wikipedia.org`, `austlii.edu.au`, `casetext.com`, `courtsofnz.govt.nz`, `dlapiper.com`, `lawtalk.co.nz`, `lawblog.com`, `worldlii.org`) | permission-gated; spike log shows `evaluated permission=webfetch … action.action=allow` (whether from default policy or a workspace rule is not determinable from the log) | `permission` config (`webfetch`/`websearch` patterns), `tools` disable | gate-classified model traffic: webfetch must egress through the gate or be denied | L (51 of 52 log URLs + permission lines), S (schema `permission`/`tools`) |

## Negative results (state of absence, as evidence)

- **No telemetry/analytics endpoints in the binary.** Zero matches for sentry/posthog/
  statsig/segment/ingest hosts or URLs across all 545 hosts / 1040 URLs. The config
  schema has no telemetry, crash-report, metrics, or anonymous-ID keys (only
  `experimental.openTelemetry`, which enables AI-SDK spans locally and needs an OTel
  collector). The Sentry JS SDK v10.36.0 code **is** bundled in the TUI exe (markers
  `__SENTRY_DEBUG__`, `Sentry Logger`, `_sentrySpan`, `captureException`,
  `__SENTRY_SAFE_RANDOM_ID_WRAPPER__`); no `sentry.io` host, no DSN, no `SENTRY_DSN`
  and no `Sentry.init` appear; the single `@sentry/` string occurrence is data inside
  the SDK's bundled module-name registry — a detection list that also names
  `@sentry/capacitor`, `@sentry/profiling-node`, `better-sqlite3`, `sodium-native`,
  `hummus`, etc. — not an import or an endpoint. Conclusion: telemetry-capable but
  inactive; re-check if a DSN ever appears in a future version.
- **Log shows no update check, no share upload, no catalog-fetch URL line.** Absence is
  consistent with the spike's `autoupdate: false` (source: returns before any network
  call) and `share: "disabled"`; the catalog fetch is real but simply not URL-logged
  (evidenced by its disk artifact instead). The 187 `share` string hits in the log are
  `.local\share\opencode` filesystem paths, not network events.
- **Log URLs are 51/52 spike task content** (NZ legal research via webfetch) plus exactly
  one OpenCode-internal egress line (the ripgrep download).

## Spike config verification (`src/harness/spike/candidates/opencode/opencode.json`)

Both keys exist in `https://opencode.ai/config.json` and both spike values are valid:

- `share: "disabled"` — schema enum `["manual","auto","disabled"]`; no schema default;
  docs + `share/session.ts` @v1.18.25 establish default "manual" (no auto-upload;
  explicit `/share` only). "disabled" additionally blocks explicit sharing — honored,
  no share egress in logs.
- `autoupdate: false` — schema type `boolean|"notify"`; no schema default; source
  (`cli/upgrade.ts` @v1.18.25: `if (config.autoupdate === false || Flag.OPENCODE_DISABLE_AUTOUPDATE) return`)
  establishes unset ⇒ enabled, `false` ⇒ no network check at all — honored, no
  update-check lines in logs.

## Key source citations (sst/opencode @ tag v1.18.25, via raw.githubusercontent.com)

- `packages/core/src/models-dev.ts` — catalog URL, 60-min loop, 5-min TTL, disable flags
- `packages/core/src/ripgrep/binary.ts` — download URL template, lazy trigger, no
  checksum, no disable
- `packages/opencode/src/cli/upgrade.ts` — autoupdate gating
- `packages/opencode/src/installation/index.ts` — per-channel check URLs, `opencode.ai/install`
- `packages/opencode/src/share/session.ts` + `share/share-next.ts` — share gating +
  `opncd.ai/api/share` endpoints + `OPENCODE_DISABLE_SHARE`
- `packages/opencode/src/config/config.ts` — config merge; no autoupdate default here
- `https://opencode.ai/config.json` (schema), `https://opencode.ai/docs/config/` (docs)
