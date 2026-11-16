# IronFleet Harness

**A local-first runtime for IronFleet's legal AI agents.** It runs a crew of specialist
agents (intake, research, assessment, strategy, adversary, moot court, filings) on your
matters, sends every model call through a provenance-checked gateway, keeps each matter's
work in its own isolated workspace, and lets you watch every agent and every LLM call live
— in a web app that installs on Windows with one click.

> IronFleet does not give legal advice. Every draft it produces must be checked by a
> qualified person before it is relied on.

- **Releases (Windows installer):** [GitHub Releases](https://github.com/BasimBashir/ironfleet-harness/releases)
  · mirror: [GitLab](https://gitlab.aiconsult.live/NL-Developer/ironfleet-harness/-/releases)
- **Companion plugin** for Claude Code, Codex, Cursor, Gemini and other agent tools:
  [ironfleet-legal](https://github.com/BasimBashir/ironfleet-legal)

---

## Contents

1. [What it does](#what-it-does)
2. [Install (Windows)](#install-windows)
3. [First run](#first-run)
4. [Using IronFleet](#using-ironfleet)
5. [Watching agents live](#watching-agents-live)
6. [Usage and cost per account](#usage-and-cost-per-account)
7. [Where your data lives (privacy)](#where-your-data-lives-privacy)
8. [Updating and uninstalling](#updating-and-uninstalling)
9. [Troubleshooting](#troubleshooting)
10. [For developers](#for-developers)
11. [Configuration reference](#configuration-reference)
12. [Repository layout](#repository-layout)
13. [Licence](#licence)

---

## What it does

| Area | What you get |
|---|---|
| **Matters** | A board of every matter with state, stage, approvals waiting on you, deadlines, risk and token use. |
| **Agent crew** | One instruction ("Dispatch work") runs a staged pipeline — intake → research → assessment → strategy → adversary attack → moot court → filings — each stage an agent with its own instructions and tools. |
| **Grounding** | Agents search your ingested documents and legislation through a local retrieval index (embeddings + reranker), and citations are checked against the source passages. |
| **Egress gate** | Every model call goes through one gateway on `127.0.0.1:7373`. It routes each task to an allowed provider, refuses what policy forbids (fail-closed), and records provider, model, tokens, thinking tokens and milliseconds for every call. |
| **Human control** | Drafts wait for your review; approvals, interjections, pause/resume/cancel and redirect are one click; nothing is filed or sent without you. |
| **Live view** | The Agents tab streams what each agent is doing *right now*: which real model is answering, its thinking, its output, every tool call with input and output, with timers and token counts. |
| **Oversight** | Firm-wide audit chain (tamper-evident), metrics, latency per model, and usage per provider/model and per user. |
| **Matter isolation** | Each run gets its own workspace; a workspace that belongs to another matter is refused, never reused. |

---

## Install (Windows)

### Requirements

| Need | Notes |
|---|---|
| Windows 10 or 11, 64-bit | Pro / Enterprise / Education recommended so the data folder can sit on a BitLocker-encrypted drive. |
| 32 GB RAM recommended | Local models reserve ~20 GB each while loaded. |
| ~40 GB free disk | Local models + your documents and indexes. |
| [Ollama](https://ollama.com/download) | Local model server. Install it before IronFleet; IronFleet starts it if it isn't running. |
| An NVIDIA NIM API key *(recommended)* | Cloud model for drafting, research and analysis. Without a cloud provider those stages refuse by design; only mechanical tasks (extraction, classification, redaction, grounding checks) run locally. Get a key at [build.nvidia.com](https://build.nvidia.com). |

Everything else — the agent runtime (opencode, pinned), the reranker server (llama.cpp)
and its model, Python and the web app — is **inside the installer**. No Python, Node or Git
needed.

### Steps

1. **Install Ollama** and pull the local models (PowerShell):
   ```powershell
   ollama pull bge-m3:567m      # embeddings (required for document search), ~1.2 GB
   ollama pull qwen3.8:27b      # local tool-calling model, ~17 GB
   ```
   Optional: `thomson1-chat` (IronFleet's in-house local chat model) if your organisation
   has provided it to you.
2. **Download** `IronFleet-Setup.exe` and `IronFleet-Setup.exe.sha256` from the
   [latest release](https://github.com/BasimBashir/ironfleet-harness/releases/latest).
3. **Verify the download** (the release is not code-signed yet, so check the hash):
   ```powershell
   (Get-FileHash .\IronFleet-Setup.exe -Algorithm SHA256).Hash
   Get-Content .\IronFleet-Setup.exe.sha256
   ```
   The two values must match. If they don't, do not run the file.
4. **Run `IronFleet-Setup.exe`.** Windows SmartScreen may say *"Windows protected your PC"*
   because the installer is unsigned: click **More info → Run anyway**. The installer
   needs no administrator rights and installs to `%LOCALAPPDATA%\Programs\IronFleet`.
5. Start **IronFleet** from the Start menu or the desktop shortcut.

---

## First run

1. A console window opens and brings the services up (Ollama, the reranker, the API),
   then your browser opens at `http://127.0.0.1:8765` (or `:8766` if 8765 is already in use).
   **Keep the console window open while you use IronFleet** — closing it stops the app.
2. **Copy the administrator password.** On the very first run the console prints:
   ```
   Your administrator password (shown once — copy it now): ...
   ```
   It is shown only once — store it in a password manager. Sign in as **`admin`** with it.
   *(Advanced: set the environment variable `HARNESS_OPERATOR_PASSWORD` before the first
   run to choose the password yourself.)*
3. **Add your model key.** Open **Model settings**, find `nvidia-nim` and
   `nvidia-nim-tool`, paste your NVIDIA API key into each, then click **Test**. The key is
   stored in Windows Credential Manager, never in a file. Each provider shows its admission:
   `full` (cloud, verified), `mechanical-only` (local Ollama) or `refused`.
4. **Invite your team (optional).** Colleagues open the same address on this machine and
   click **Request an account**. As admin, approve them in **Users & roles** and give each a
   role (admin / editor / reader). Matter access is per matter: add members on the matter's
   Overview.

---

## Using IronFleet

| Step | Where | What to do |
|---|---|---|
| 1. Open a matter | **+ New matter** | Title, client reference, matter type, jurisdiction, objectives, priority. |
| 2. Add documents | Matter → **Documents** | Upload pleadings, contracts, correspondence, judgments (PDF, DOCX, TXT, HTML…), then **Ingest documents** so agents can search them. The viewer shows the extracted text and exactly which passages agents retrieved. |
| 3. Dispatch work | Matter → **Overview → Dispatch work** | One plain-language instruction for lead counsel, e.g. *"Assess whether the limitation defence succeeds and draft a strategy memo."* The crew plans and runs its stages. |
| 4. Watch it run | Matter → **Agents** | Live activity (see below). Also **Work plan** for the stage map, with pause / resume / cancel and redirect. |
| 5. Answer questions | **Approvals** (top nav) | Agents stop and ask when they need a decision; reviews of drafts land here too. |
| 6. Review drafts | Matter → **Drafts** | Each draft lists its sources; verified quotes and unverified assertions are marked. Approve, reject or request changes. |
| 7. Keep track | **Deadlines**, **Decisions**, **Activity**, **Audit** | Court deadlines (working-day aware), decisions taken, every event, and the tamper-evident audit chain. |
| 8. Ask questions | **Counsel chat** (bottom right) | Ask about the matter at any time; answers cite the matter's records. |

**Self-rep mode** (top bar) switches to plain language and a guided view for people
representing themselves; **Reading level** and **Dark** are next to it.

---

## Watching agents live

Open a matter's **Agents** tab while a case is processing:

- **Status strip** — the agent and stage running now, the model *actually* answering
  (providers sometimes serve a different model than the one requested; both are shown),
  a turn timer, a "waiting on model" timer, and this turn's tokens and LLM calls.
- **Agent rail** — every agent in the run with its state (Running / Done / Failed /
  Stopped), the models it used, tokens, calls, tool calls and time. Click one to focus the
  timeline on it.
- **Timeline** — one card per LLM call (model, ms, tokens in/out/thinking, the tools it asked
  for), per tool call (status, duration, its file or query), per output and per thought.
  Each card opens its **Thinking**, **Output**, **Input** and **Error** in place.
- **Filters** — All · LLM calls · Tools · Thinking · Output, with live counts.

Everything shown is also written to `…\IronFleet\harness\live\<matter-id>.jsonl` on your
machine, one JSON record per event, so a run can be reviewed later.

---

## Usage and cost per account

- **Per matter:** Agents tab → *Usage by agent* (tokens in/out/thinking, calls, model time).
- **Firm-wide:** **Audit & metrics** → *Usage per account* — totals per provider/model
  (calls, errors, tokens, model time) and per user (the matter's owner), plus p50/p95 latency
  per model. Requires the `audit.read` permission (admins have it).

Every call is recorded in `trace.db` with timestamp, matter, agent, provider, model,
tokens and milliseconds.

---

## Where your data lives (privacy)

| What | Where |
|---|---|
| Matters, users, audit chain, approvals | `%LOCALAPPDATA%\IronFleet\harness\platform.db` |
| Every model call (ledger) | `%LOCALAPPDATA%\IronFleet\harness\trace.db` |
| Live agent/LLM log | `%LOCALAPPDATA%\IronFleet\harness\live\` |
| Documents, indexes, agent workspaces | `%LOCALAPPDATA%\IronFleet\harness\` (`matters\`, `workspaces\`, …) |
| Provider API keys | Windows Credential Manager |
| The application itself | `%LOCALAPPDATA%\Programs\IronFleet` |

- The app listens on **localhost only**. Nothing is sent anywhere automatically — no
  telemetry, no crash upload.
- Text leaves your machine only when a task is routed to a cloud provider you registered.
  Embeddings and reranking are structurally **local-only**: no routing table can send them
  to a cloud provider.
- Override the data folder with the `HARNESS_HOME` environment variable (e.g. to put it on
  an encrypted drive).

---

## Updating and uninstalling

- **Update:** download the newer `IronFleet-Setup.exe`, close IronFleet (close its console
  window), run the installer. Your data folder is outside the app folder and is kept.
- **Uninstall:** *Settings → Apps → IronFleet → Uninstall*. Your data in
  `%LOCALAPPDATA%\IronFleet\harness` is **not** deleted; remove it yourself if you want it
  gone.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Browser shows nothing / "can't connect" | Make sure the IronFleet console window is still open; check which port it printed (`serving on http://127.0.0.1:8766` if 8765 was busy). |
| Lost the admin password | There is no in-app password reset yet. If another admin exists, they can create you a new account in **Users & roles**; otherwise keep the first-run password safe. |
| Drafting / research stages refuse | No cloud provider is admitted: add the NVIDIA key in **Model settings** and click **Test**. |
| Document search returns nothing | Is Ollama running with `bge-m3:567m` pulled? Did you click **Ingest documents**? |
| Models are slow on first use | Local models load into memory on first call (can take minutes); later calls are fast. |
| SmartScreen blocks the installer | Unsigned build: **More info → Run anyway**, after checking the SHA-256. |

Crash reports (if any) are written to `%LOCALAPPDATA%\IronFleet\harness\crash\` and never
sent anywhere.

---

## For developers

### Prerequisites

- Python **3.12+**, Git, Node.js **18+** (for the web client)
- `opencode-ai` **1.18.25 — pinned** (`npm install -g opencode-ai@1.18.25`; never
  auto-update it — its guard hooks are version-sensitive)
- Ollama with the models above; optional `llama-server` for reranking
  (see [PREREQUISITES.md](PREREQUISITES.md) for the full list and why each is pinned)

### Set up

```powershell
git clone https://github.com/BasimBashir/ironfleet-harness.git
cd ironfleet-harness
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cd web; npm ci; npm run build; cd ..
```

### Run

```powershell
python -m harness.api seed-operator          # create admin/admin (must set a password at first sign-in)
python -m harness.api serve --worker live    # API + web on http://127.0.0.1:8765
```

`--worker demo` runs the pipeline without calling any model (useful for UI work).
The web client can also run with hot reload: `cd web; npm run dev`.

### Test

```powershell
.venv\Scripts\python.exe -m pytest tests -q   # always by path; never `-m tests.x`
cd web; npx vitest run
```

A handful of packaging tests depend on the build machine (an existing `dist/` folder, a
free port 7373); they are environmental, not regressions.

### Build the Windows installer

The complete chain — pins, what the frozen app must carry, and the post-install
verification ladder — is in **[BUILDING.md](BUILDING.md)**. In short:

```powershell
cd web; npm run build; cd ..
.venv\Scripts\python.exe scripts\pack_windows_exe.py --no-download   # → dist\IronFleet\
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" scripts\ironfleet-setup.iss   # → dist\IronFleet-Setup.exe
```

### Evaluation (golden cases)

`data/golden_cases/` holds graded legal test cases. Their source judgments are **not** in
the repository — bring your own copies, see
[data/golden_cases/sources/README.md](data/golden_cases/sources/README.md).

### Deeper docs

- [docs/DEVELOPER-NOTES.md](docs/DEVELOPER-NOTES.md) — the gate, provenance probe, routing,
  embeddings, scheduler, store root, model A/B, in depth
- [docs/enterprise/](docs/enterprise/) — architecture, API (`openapi-v1.json`), release runbook
- [design/](design/) — design tokens and UI mockups
- [CHANGELOG.md](CHANGELOG.md)

---

## Configuration reference

| Setting | Where | Purpose |
|---|---|---|
| Providers (URL, model, engine, provenance) | `data/providers.yaml` | One row per provider; swapping a model is one row. |
| Which provider serves which task | `data/routing-a1.yaml` | Task class × data classification → allowed providers. |
| `HARNESS_HOME` | env var | Data folder (default `%LOCALAPPDATA%\IronFleet\harness`). |
| `HARNESS_OPERATOR_PASSWORD` | env var | Admin password on first run (otherwise generated and printed once). |
| `IRONFLEET_<PROVIDER>_URL` / `_MODEL` / `_REVISION` | env vars | Override one provider row without editing files. |
| `HARNESS_MAX_CONCURRENT` | env var | Cap on concurrent matters (default derived from CPU cores and free RAM). |
| `HARNESS_HTTP_TIMEOUT` / `HARNESS_HTTP_STREAM_TIMEOUT` | env vars | Model call timeouts in seconds (300 / 1800). |

---

## Repository layout

```
src/harness/      Python package: gate, providers, routing, session crew, API, services
  api/            FastAPI app (REST + SSE), loopback only
  service/        business logic: matters, executions, usage, events, settings…
  session/        the agent crew: plans, stages, workspaces, driver
  substrate/      opencode integration (mount, supervised runs)
  live.py         live agent/LLM log
web/              React web client (Vite)
data/             runtime config (providers, routing), module-e packs, golden cases
scripts/          build, packaging, acceptance and evaluation tools
tests/            pytest suite
design/           design tokens + mockups
docs/             developer notes, enterprise docs, help, legal drafts
```

---

## Licence

Copyright © 2026 IronFleet. **All rights reserved.** See [LICENSE](LICENSE). Viewing and
installing the released application are permitted; copying, modifying or redistributing
the code is not, without written permission.
