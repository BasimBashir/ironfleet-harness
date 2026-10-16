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

The tags must match exactly what the bootstrap table registers
(`src/harness/bootstrap.py`, `_probe_ollama`); the verify script checks for these
three by name. `thomson1-chat` is the programme's in-house model — provision it into
your Ollama registry the way you obtained it (a public `ollama pull` may not carry
it). The reranker model `qwen3-reranker-0.6b` (optional, ~1.2 GiB GGUF) is
downloaded per the `research/06` recipe, not via Ollama.

## 4. Python packages (installed automatically — no action)

`install_windows.ps1` creates `.venv` and `pip install -e .` from `pyproject.toml`
(network needed once):

`pydantic ≥ 2.6` · `httpx ≥ 0.27` · `keyring ≥ 24` (uses Windows Credential Manager,
built in — no extra tool) · `pyyaml ≥ 6` · `pypdf ≥ 6.0` · **`sqlite-vec==0.1.9`**
(pinned, fail-closed — the vector index) · `markitdown ≥ 0.1` (document parsing).

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
