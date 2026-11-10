# PREREQUISITES — running the IronFleet harness on a clean, fresh Windows machine

Everything the harness needs from outside its own zip. Install the tools in this
order, then run `install_windows.ps1` (it checks each one and fails loud with a
remediation if something is missing), then `verify_windows_install.ps1
-WithDriveSmoke` to prove one real gated dispatch.

**Privacy shape (why this list is short):** all inference is LOCAL. The egress gate
(`127.0.0.1:7373`) is the only path from the agent to any model, it routes every call
to the local servers below, and embedding + rerank are structurally local-only
(`harness/policy.py LOCAL_ONLY_TASKS` — no routing table can send them to cloud).
No cloud API keys are needed for the shipped configuration.

## 1. Windows itself

| Requirement | Why |
|---|---|
| Windows 10/11 **Pro, Enterprise or Education** (64-bit) | The privileged store must sit on a BitLocker-encrypted volume; `manage-bde.exe` (which the installer uses to enforce that) ships only with these editions. **Home** editions have device encryption only — the installer's store gate cannot verify it. Options: upgrade the edition, or pass `-AcceptUnencryptedStore` (a recorded, printed CR-7 deviation: the store is NOT encrypted at rest). |
| PowerShell 5.1 or newer | Built into Windows; the install/verify scripts are ASCII-only for it. |
| An admin PowerShell **only if** you need to turn BitLocker ON | Enabling encryption: `manage-bde -on C: -RecoveryPassword` (elevated). Installing the harness itself needs no elevation. |

## 2. Third-party tools (install these yourself)

| Tool | Version | Used for |
|---|---|---|
| **CPython** | ≥ 3.12 (3.14 proven) | Runs the harness. The [python.org installer](https://www.python.org/downloads/) with the `py` launcher is the tested path; tick "Add python.exe to PATH". |
| **Git for Windows** | current | Each drive workspace is its own git repo (isolation seam — `git init` only, no commits, matter data never enters history). |
| **Node.js + npm** | LTS (≥ 18; 24 proven) | Installs the pinned opencode binary (next row). |
| **opencode-ai** | **1.18.25 — PINNED** | The agent binary the harness drives. The installer runs `npm install -g opencode-ai@1.18.25` and then RE-VERIFIES the version — drift fails the install. The global `~/.config/opencode/opencode.jsonc` gets `"autoupdate": false` (the binary is part of the harness; its guard hooks are version-sensitive and re-verified per upgrade). Never `npm update -g opencode-ai` on your own. |
| **Ollama** | current (0.32+ proven) | Local model server on `127.0.0.1:11434`. Runs during use; `ollama serve` or the desktop app. |
| **llama.cpp `llama-server`** | current — **OPTIONAL** | ONLY the corpus **rerank** class (R1 retrieval re-ranking), served as `llama-server --reranking --pooling rank` on `127.0.0.1:8778` with the official ggml-org **`qwen3-reranker-0.6b`** GGUF (third-party conversions measured broken — llama.cpp #16407). Ollama has no rerank endpoint. Without it, corpus retrieval refuses; chat/drafting/extraction run fine. Recipe: `research/06`. |

## 3. Ollama models (pull after installing Ollama)

```powershell
ollama pull thomson1-chat:latest   # default chat model - research/drafting/extraction/etc (34.7B Q4_K_M, ~20 GiB)
ollama pull qwen3.8:27b            # the toolpath class (tool-calling injection leg), ~17 GiB
ollama pull bge-m3:567m            # embeddings (1024-dim), ~1.2 GiB
```

The tags must match exactly what the provider registry registers — the tags live in
`data/providers.yaml` (R3: one row per provider = url + model + engine + kind; the
doc's drift-guard asserts every registered model is named here); the verify script
checks for these three by name. `thomson1-chat` is the programme's in-house model —
provision it into your Ollama registry the way you obtained it (a public `ollama pull`
may not carry it). The reranker model `qwen3-reranker-0.6b` (optional, ~1.2 GiB GGUF)
is downloaded per the `research/06` recipe, not via Ollama.

## 3b. Cloud provider (optional; needed for non-mechanical classes)

`nvidia-nim` (`nvidia/nemotron-3.5-super-vl-120b-a12b`, NVIDIA NIM
`integrate.api.nvidia.com`) serves drafting / research / analysis /
complex_reasoning / summarization — the cloud model for every NIM row (user
directive 2026-10-20). `nvidia-nim-tool` (same model) is the tool-calling leg's
OWN row, so the toolpath injection class and the research class never share a
candidate (S7j-W 1.2, by row name).
Ollama is honestly `mechanical-only` on this box (CR-3: its executing backend is
unverifiable), so **without a cloud provider these classes refuse — by design**, and
only the mechanical classes (extraction / classification / redaction /
grounding_check) run locally. Registration is one command per row (key → OS
keychain, never on disk):

```powershell
harness providers set-key --provider nvidia-nim --key <your-nvidia-api-key>
harness providers set-key --provider nvidia-nim-tool --key <your-nvidia-api-key>
harness providers list     # the honest probe verdict per provider
```

**Changing provider / model later (user surface):** edit the provider's row in
`data/providers.yaml` (url + model + engine + provenance travel together — a swap is
one row), or override per-row with `IRONFLEET_<NAME>_URL` / `_MODEL` / `_REVISION`
env vars; which provider serves which class is `data/routing-a1.yaml`. The key stays
per-provider in the keychain. No code edit, ever.

## 4. Python packages (installed automatically — no action)

`install_windows.ps1` creates `.venv` and `pip install -e .` from `pyproject.toml`
(network needed once):

`pydantic ≥ 2.6` · `httpx ≥ 0.27` · `keyring ≥ 24` (uses Windows Credential Manager,
built in — no extra tool) · `pyyaml ≥ 6` · `pypdf ≥ 6.0` · **`sqlite-vec==0.1.9`**
(pinned, fail-closed — the vector index) · `markitdown ≥ 0.1` (document parsing) ·
`textual>=3.0` (the R3 TUI's toolkit — MIT, pure-Python; without it the shell
does not start) · **`fastapi==0.162.2`** + **`uvicorn==0.54.0`** (pinned — the M7
REST + SSE API, `python -m harness.api serve`, loopback only; fastapi pulls
`starlette`, `annotated-doc` and `opentelemetry-api` as hard requirements).

## 5. Network

- **At install: REQUIRED** — pip and npm fetch packages. (Offline wheels are NOT
  provided yet.)
- **At run time: NONE** — every model call goes to the local servers above through
  the gate; the default routing table names only local providers, and cloud egress
  would require an explicit, keyring-held provider registration (not part of the
  shipped product).

## 6. Hardware shape

- **RAM:** the scheduler reserves **20 GiB per served model** when deriving the
  concurrency cap (a 30B Q4_K_M model must always be able to cold-load). 32 GiB
  total is a comfortable minimum; the cap self-derives and `HARNESS_MAX_CONCURRENT`
  overrides.
- **Disk:** ~40 GiB for the three Ollama models + the reranker GGUF + the store
  (corpus + vectors grow with ingested matter).
- **CPU:** multi-core; the cap derivation counts performance-class logical CPUs.

## 7. Where your data lives

- Privileged store: `%LOCALAPPDATA%\IronFleet\harness` (override: `HARNESS_HOME`),
  BitLocker-gated, with a versioned backup script laid down by the installer.
- Matter workspaces: `~\spike-ws-a1\opencode-a1` per drive run (override:
  `--workspace`).

## 8. Version + update story

- **Harness version** lives in `pyproject.toml` (`version`), shown by
  `harness --version` and carried in the zip name. Update = rebuild/re-extract the
  zip at the new version and re-run `install_windows.ps1` — it is idempotent and
  re-verifies every pin below.
- **The opencode pin** lives ONLY in `src/harness/packaging/macdist.py` (`PINS`);
  the installer and the verify script read it from there, and global
  `autoupdate: false` defends it. Upgrading opencode is a DELIBERATE ruling (its
  guard hooks are version-sensitive and must be re-verified on every upgrade — M0
  hazard 1), never a casual `npm update`.
- **Model ids** live in `src/harness/bootstrap.py` (registration) and
  `data/routing-a1.yaml` (which class each serves). Swapping the chat model = change
  the spec table row + the routing rows. Swapping the embedding model = deliberate
  wipe-and-reingest (the vector store records the model per row).
- **Python deps**: bump in `pyproject.toml`, re-run the installer. `sqlite-vec` is
  pinned and fails closed if it cannot import.

## 9. Reliability surface (M11)

- **Upgrades**: after extracting a new zip, run `harness migrate` before first use
  — it upgrades the SQLite stores in place, additive-only and versioned; rollback
  is "restore backup" (migrate never rewrites history).
- **Backups + the drill**: the installer lays down a versioned backup script
  (RUNBOOK_P0_7). Prove the restore path with
  `.venv/Scripts/python.exe scripts/restore_drill.py` — quarterly and before every
  release; the live store is read-only throughout and it prints an evidence block.
- **Crash logs**: an unexpected death of `harness serve` or the API leaves a log
  under `<store-root>\crash\` (version + component + traceback; last 20 kept).
  Local only — nothing is ever sent automatically. Ctrl-C is clean and writes none.
- **Help + legal in the zip**: `docs/help/firm-mode.md`, `docs/help/selfrep-mode.md`,
  and the `docs/legal/*-DRAFT.md` terms/privacy/disclosure drafts. The legal drafts
  are marked **DRAFT — PENDING R-1**: not legal advice and not for publication
  until the R-1 consultation rules.
- **Tri-OS distribution**: one zip serves all three OSes (the `-windows` in the
  name is only accept_r2's fresh-machine contract). Linux: `install_linux.sh` +
  `verify_linux_install.sh`; macOS: `src/harness/ops/pack_macos.sh` builds
  `IronFleet.dmg`. This release ships **unsigned + sha256-checksummed** — verify
  `<artifact>.sha256` before installing (docs/enterprise/11-release-runbook.md §1).
