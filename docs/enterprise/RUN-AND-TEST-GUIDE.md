# Run the harness like production — and take a real matter through, in the UI

Step by step: install the app the production way, start the server on the real
store, let a real user in, and take one real matter from creation to reviewed
drafts in the browser. Commands are PowerShell, run from `harness-core\`.

"Production" here means five things:

1. The app is installed by the installer — venv, pinned opencode, store setup.
2. The store is the real one at `%LOCALAPPDATA%\IronFleet\harness`, encrypted
   and backed up nightly — not a throwaway `$env:TEMP` folder.
3. The admin signs in with a real password, chosen before the account exists.
4. The live worker runs the stages: the real opencode crew on your models,
   through the egress gate.
5. Real people use it: they request accounts, an admin approves them into
   roles, and the work happens under those accounts.

## 0. Prerequisites (once)

1. Windows Pro/Enterprise/Education — the store gate needs BitLocker
   (`manage-bde.exe`). Home editions only have device encryption; see section 1
   for the options.
2. `git`, `node`, `npm` on PATH (the installer checks them up front).
3. For live runs: Ollama running with your models — open
   `http://127.0.0.1:11434/api/tags` in a browser; it must list the models your
   providers point at. Cloud providers need their API key (step 8).

## 1. Install the app

One command, idempotent — every step verifies before it acts, so re-running is
safe (including after pulling an update):

```powershell
powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
```

What it does: checks git/node/npm → builds `.venv` → installs the package →
installs opencode at the pinned version (`1.18.25`) → creates the store and
holds it to the BitLocker rule.

- If it stops at the BitLocker gate: enable BitLocker on the store drive
  (Settings → Privacy & security → Device encryption), then re-run.
- If this machine will not use BitLocker, re-run with `-AcceptUnencryptedStore`.
  That records the CR-7 deviation — "store not encrypted at rest,
  operator-accepted" — and continues. An unencrypted store is never created
  silently.

## 2. Verify the store and turn on backups

Confirm the store is production-ready, from an **elevated** PowerShell (the
BitLocker check needs `manage-bde`, which refuses a normal window). Fail-loud:
a non-zero exit means fix something before going further:

```powershell
powershell -ExecutionPolicy Bypass -File .\src\harness\ops\p07_verify_windows.ps1
```

It checks BitLocker protection ON (or warns, if you took the CR-7 deviation),
the store layout (`sessions`, `trace`, `backups`), and the backup script.

Then register the nightly backup — elevated PowerShell. This registers the
`IronFleet Backup` scheduled task (daily 02:30, catches up after sleep) and
runs one backup straight away:

```powershell
powershell -ExecutionPolicy Bypass -File .\src\harness\ops\p07_register_backup_windows.ps1
```

Backups are versioned snapshots under `<store>\backups`, with a `latest` view.

**The store lives at `%LOCALAPPDATA%\IronFleet\harness`** (unless `HARNESS_HOME`
is set — see Troubleshooting). From here on, do **not** set `HARNESS_HOME`;
every command below uses the default store.

## 3. Build the web client

```powershell
cd web
npm run build
cd ..
```

The installer does not build the client. Do this again after **any** change
under `web\src` — the server serves `web\dist`, so without a rebuild you see
the old screens.

## 4. Create the admin account (once)

```powershell
$env:HARNESS_OPERATOR_PASSWORD = '<a real password>'
.venv\Scripts\python.exe -m harness.api seed-operator
Remove-Item Env:HARNESS_OPERATOR_PASSWORD
```

- Creates `admin` in the default store **with your password** — no forced
  change at first sign-in. It prints the store it wrote; check it is the
  `%LOCALAPPDATA%` one.
- Without the env var you get `admin/admin` and a forced password change at
  first sign-in — fine for a scratch rig, not production posture.
- Run it once. Re-running fails with `user_exists`; the account persists in the
  store.

## 5. Start the server

```powershell
.venv\Scripts\python.exe -m harness.api serve --worker live
```

- Serves the default store and binds `127.0.0.1:8765` only. Port taken? Add
  `--port 8766` and use that port everywhere below.
- The worker runs inside the server process: keep this window open. Ctrl+C
  stops the server.
- `serve` does not print the store path. It is on
  `%LOCALAPPDATA%\IronFleet\harness` as long as `HARNESS_HOME` is unset in this
  window.
- Restarting is the same one command: matters, users, settings and the audit
  chain all live in the store and survive it.

## 6. Check it is up

Open `http://127.0.0.1:8765/healthz`. You should get JSON with `"stores":"ok"`
and `"proxy_bound":true` (the egress gate is up). The `providers` text should
say `installed 1.18.25 OK`. If it also says `autoupdate: DRIFT`, set
`"autoupdate": false` in `~\.config\opencode\opencode.jsonc` so opencode stays
on the pinned version.

## 7. Sign in

Sign in as `admin` with the password from step 4. You land on **Matters** (the
board).

## 8. Configure the models (once per machine)

**Model settings** (admin nav):

1. Each provider row shows its base URL, model and key state. Local providers
   should say **no key**. Cloud providers need a key: paste it and save. The
   key is write-only and is never shown again.
2. Press **Test** on each provider you will use. You want **reachable** for it.
   An unreachable provider is skipped at dispatch time.
3. Optional: under the per-stage table, assign a provider to a stage. Leave it
   blank to use the routing defaults.

## 9. Let a real user in

1. Sign out → **Request an account** → the real user requests one.
2. Sign back in as admin → **Users & roles** → approve the request and pick a
   role: **Admin**, **Editor** or **Reader**. An approval without a picked role
   defaults to **Reader**.
3. The user signs in. Non-admins see only **Matters / Approvals / New matter**
   — none of the admin screens (Users & roles, Model settings, Audit).

## 10. Create the matter

**New matter**:

- **Title**: e.g. `Harbour Freight v Blue Anchor — unpaid invoices`
- **Type**: e.g. `Debt recovery`
- **Jurisdiction**: pick the one the matter is in.
- Press **Create**. You land on the matter workspace (Overview tab).

## 11. Add the case documents

**Documents** tab:

1. **Upload documents**: pick the real files (contracts, invoices, letters).
   Each one appears in the table. Click a row to read its text and the passages
   retrieval will see.
2. Optional, to add law: under **Ingest**, enter a source path or a
   sources-spec YAML of files *you downloaded yourself*, then press **Ingest**.

Check: the **Evidence** tab lists the uploaded material.

## 12. Dispatch the work

**Overview** tab → **Dispatch work**:

1. Under **Instruction for lead counsel**, describe the job in plain words, e.g.
   *"Assess the claim for the unpaid invoices, draft a pre-action letter, and
   plan the filings."*
2. Press **Dispatch**. It shows *Pending… waiting for the worker to confirm*.
   That clears when the execution appears under **Current executions**.

With no plan given, the server uses the default legal pipeline.

## 13. Watch it run

- **Work plan** tab: the stages and their states (pending → running → completed
  / failed). Click a run to open the run drawer (self-represented mode) or the
  swarm view (firm mode), or go to its full page at `#/runs/<execution id>`.
- **Agents** tab: tokens by agent as stages finish.
- On the board, the matter's state chip updates live (SSE). A refresh is not needed.
- Live stages take minutes, not seconds. Leave the machine alone while they run:
  on this box opencode can hang at startup, and the driver's watchdog (480 s)
  retries it once.

## 14. Answer what the crew asks

**Approvals** (nav):

- **Review** items: read them, add an optional **Note for the record**, then
  **Approve** or **Reject**.
- **Questions**: type into **Your answer** and submit.
- The matter shows under the board's **Waiting on you** filter while anything is open.

## 15. Review the drafts

**Drafts** tab: each deliverable the crew produced is listed as a pending draft.
Open it, read it, then **Mark reviewed**. If something is wrong, dispatch a new
instruction from Overview. A re-run marks the earlier rows as superseded.

## 16. Move the case on

**Overview → Case stage**:

- When an execution completes, the matter moves forward one legal step by
  itself. It never moves backwards. If you moved the case yourself mid-run, your
  move wins.
- To move it by hand, use the **Move to …** buttons. Only legal next stages are offered.

## 17. Check the record

- **Decisions** tab: decided approvals, with who decided them and their notes.
- **Activity** tab: the timeline, filterable by type.
- **Audit** tab: the hash-chained audit log for this matter.

A real-matter test passes when all of these hold: the execution completed, the
drafts are reviewed, the approvals are decided, the case stage moved forward,
and the audit chain shows each step.

---

## Operations

- **Stop / start**: Ctrl+C in the server window, then the section 5 command again.
- **Back up now**: `Start-ScheduledTask 'IronFleet Backup'`, or run the script
  directly:
  `powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\IronFleet\harness\ironfleet-backup.ps1"`
- **Crash logs**: a startup crash is written under `<store>\crash\`.
- **After a change under `web\src`**: rebuild (section 3), then reload the browser.
- **After pulling an update**: re-run the installer (section 1), then restart
  the server (section 5).

## Demo mode (smoke tests only — not production)

`.venv\Scripts\python.exe scripts\dev_m8.py --store $env:TEMP\ironfleet-demo --fresh`
starts a demo server on 8765: stages produce a labelled demo body (no models),
and it prints the `operator` password **once** (or use `HARNESS_OPERATOR_PASSWORD`).
`--fresh` wipes that store. Use it for a UI tour or the automated checks below —
never for real matters. It exits 2 with `web/dist/index.html missing` if the
client was not built (section 3).

## Automated checks (no browser)

- Build + start the demo server, then
  `.venv\Scripts\python.exe scripts\e2e_full.py --base http://127.0.0.1:8765 --round 1 --password <pw>`
  runs 44 HTTP tests against it. The full round-by-round process lives in
  `E2E-TEST-LEDGER.md`.
- `.venv\Scripts\python.exe -m pytest tests\test_api.py tests\test_api_authz.py -q`
  runs the API unit suites (182 tests).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Installer stops at the BitLocker gate | Enable BitLocker on the store drive, or re-run with `-AcceptUnencryptedStore` (records the CR-7 deviation) |
| `p07_verify_windows.ps1` fails "not BitLocker-protected" | Same options as the installer row |
| Server opens a store you did not expect | A stray `$env:HARNESS_HOME` in this window. `Remove-Item Env:HARNESS_HOME`, restart `serve` |
| `seed-operator` says `user_exists` | The admin already exists — that is fine, sign in |
| Old screens after a code change | Rebuild: `cd web; npm run build`, then reload |
| Clicking a link to the page you are on does nothing | Hash navigation on the same URL. Use the in-app back link or reload |
| Dispatch stays *Pending…* forever | The server was started without `--worker`. Restart it with `--worker live` (section 5) |
| Stage fails at once on live | opencode missing or wrong version, or no reachable provider. Check section 0 and **Test** in section 8 |
| Stage hangs a long time | The opencode startup hang. It is retried once after 480 s, so keep the machine quiet |
| Login says "bad username or password" for a new user | The account is still pending. An admin must approve it in **Users & roles** |
| Moot stage fails with `moot CAPPED` | The filing guard found blocking flaws in the drafts. That is a real verdict, not a crash |
| Server crash at startup | A local crash log is written under `<store>\crash\` |
