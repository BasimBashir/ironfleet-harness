# IronFleet — firm mode help

IronFleet in firm mode is the operator console: matters, the Matter Board, the
Swarm, approvals and the audit trail, driven from the web workspace and the
`harness` CLI. Everything runs on your machine against the local store.

## Starting and stopping

```bash
# the egress proxy (the gate): opencode mounts talk to 127.0.0.1:7373
harness serve
# the workspace (web UI + API on 127.0.0.1:8765)
python -m harness.api serve --web-dist web/dist
# one live gated dispatch through the gate (smoke or one-shot work)
harness drive --matter-ref <ref> --task-class extraction
```

Stop any of these with Ctrl-C. Ctrl-C is a clean stop: no crash log is captured
for it. An unexpected death of `harness serve` leaves a log under
`<store-root>/crash/` — read the newest one if the proxy died overnight.

## Matters and the board

- **Matter creation** (web form) flags the matter privileged at creation; a
  privileged flag forces local-only routing.
- **Matter Board** (firm-only) shows every active dispatch per matter — what ran,
  which provider/model, weights revision, and status. The same facts are in the
  trace store (`trace.db`), the system of record the Board reads.
- **Swarm** is the firm-only live view of agents at work; progress also lands on
  each case's home screen.

## Approvals and the audit ledger

Approvals gate the irreversible steps. Every dispatch, approval and matter event
lands in the hash-chained audit ledger in `platform.db`; the restore drill
verifies that chain on every run (docs/enterprise/11-release-runbook.md, backup
and restore section).

## Upgrades, backups, health

```bash
harness migrate            # after extracting a new version, before first use
scripts/restore_drill.py   # quarterly + before every release
```

`harness migrate` upgrades the SQLite stores in place, additive-only, versioned.
The drill proves the restore path end-to-end and prints an evidence block. Crash
logs (last 20 kept) are under `<store-root>/crash/`. The nightly backup job is
registered per RUNBOOK_P0_7.md. The installer's verify script re-checks the pin,
autoupdate:false, store encryption, and Ollama — re-run it after any change to
the box.

## Where things live

| What | Where |
|---|---|
| Store root | `HARNESS_HOME` or the OS standard location (`resolve_store_root()`) |
| Crash logs | `<store-root>/crash/*.log` (last 20 kept) |
| Backup script (Linux) | `<store-root>/ironfleet-backup.sh` |
| Routing | `data/routing-a1.yaml` + `data/providers.yaml` (data edits, never code) |
| Help, terms | `docs/help/`, `docs/legal/` (drafts marked PENDING R-1) |
