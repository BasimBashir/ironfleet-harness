# Changelog

All notable changes to the IronFleet harness. Versions follow the zip name
(`IronFleet-harness-<version>-<os>.zip`) and `pyproject.toml` (`version`, the
single source — the drift test pins `harness.__version__` to it).

## [0.2.0] — 2026-11-10

First packaged release of the platform layer (M1–M10). The engine (gate, trace,
scheduler, packaging, TUI, RAG, providers) shipped as 0.1.x.

### Added
- **M1** security hardening of the privileged store path.
- **M2** owner-rulings ledger (documented decisions with dates).
- **M3** substrate relocation (drive workspaces + mount under the installed package).
- **M4** durable execution: platform.db, executions/tasks/approvals/audit_events
  (append-only hash chain), worker with lease-claimed tasks.
- **M5** case lifecycle: cases, case_events, strategy_versions, proposals,
  predictions, outcomes, deadlines, flaws, facts, evidence tables.
- **M6** moot gate + hearing-prep stage (flaw ledger, max-4 rounds,
  `status: final` hook deny; /moot /hearing-pack /mock-hearing in the plugin).
- **M7** REST + SSE API (`python -m harness.api serve`, loopback-only, bearer
  auth, idempotency keys, roles/permissions).
- **M8** guided workspace: React client served at /, intake → matter → execution
  journey, swarm board, counsel chat, users/roles screens, observability (M10).
- **M9** enforcement / appeal / settlement post-judgment workflows.
- **M10** swarm orchestration, counsel chat, users & roles, build observability.
- **M11** reliability + deployment: store migrations (`harness migrate`,
  `PRAGMA user_version` + additive-only steps), cross-OS backup/restore drill
  (`scripts/restore_drill.py`), crash-log capture (local only), Linux
  install/verify scripts, help docs (firm + self-rep modes), terms/privacy/
  verification-disclosure drafts (pending R-1), the release runbook
  (`docs/enterprise/11-release-runbook.md`).

### Policy
- All inference stays local-first through the egress gate (127.0.0.1:7373);
  no telemetry, ever — asserted by a drift test.
- Installers ship unsigned + sha256-checksummed for this release (owner ruling
  2026-11-10); signing hooks are env-driven (`IRONFLEET_CODESIGN_ID`,
  `IRONFLEET_NOTARY_PROFILE` on macOS) for a future signed release.

## [0.1.0] — 2026-10-16

The engine: egress proxy + gate with provenance verification (CR-3), trace
store, scheduler caps + same-case queue, opencode mount (Path A), macOS
packaging recipe (S7g-W; the Mac build is S7g-M), R3 TUI research gate, RAG
connector (store-clean corpus), provider registry + keychain, R2 Windows
installer + PREREQUISITES + first-run drive smoke.
