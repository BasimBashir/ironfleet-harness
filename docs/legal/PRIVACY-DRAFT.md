# Privacy statement — IronFleet harness

> **DRAFT — PENDING R-1.** Working draft for the R-1 lawyer consultation
> (DECISIONS-2026-11-04, R-1, especially Q7 on Privacy Act 2020 IPP 12 /
> cross-border). Not for publication until ruled. Decision points marked **[DP]**.

## 1. The short version

The harness keeps your case material on your machine. It has **no telemetry** —
there is no analytics, no crash reporting service, and no sender in the code
(enforced by automated tests). The only network calls the software itself makes
are to services **you** run locally: the egress proxy, the local models, and the
local rerank engine, all on 127.0.0.1. If a cloud model leg is configured, only
the matter classes the routing config admits can use it, and each dispatch is
traced in the local trace store with its provider and model.

## 2. What is stored, where

| Data | Where | Notes |
|---|---|---|
| Case materials, corpora, vectors | `<store-root>/` on an encrypted volume (BitLocker/LUKS/FileVault — fail-loud at setup) | local SQLite + files |
| Dispatch trace (what ran, which model) | `<store-root>/trace.db` | provenance record, local |
| Audit ledger (who did what, hash-chained) | `<store-root>/platform.db` | append-only, local |
| Crash logs (when a long-running surface dies) | `<store-root>/crash/*.log` | written locally, never sent |
| Backups | operator-chosen local folder | versioned by the P0-7 backup script |

The store root is resolved by `harness.paths.resolve_store_root()`: the
`HARNESS_HOME` environment variable wins, else the OS standard location
(`%LOCALAPPDATA%\IronFleet\harness` on Windows, `~/.local/share/ironfleet/harness`
on Linux, the FileVault volume on macOS).

## 3. What leaves the machine

- **By default: nothing.** No telemetry, no phone-home, no update check that
  sends data (opencode autoupdate is pinned off at install for guard-hook
  integrity, not to phone home).
- **Cloud model leg (only if configured and the matter class admits it):** the
  dispatch prompt is sent to the configured provider endpoint to generate text.
  Whether self-rep matters containing dispute facts may use the cloud leg is
  **[DP — R-1 Q7: Privacy Act 2020 IPP 12 cross-border disclosure]**. Privileged
  and LOCAL_ONLY task classes are structurally barred from cloud routing.
- **Court-bound documents:** produced locally; you file them yourself.

## 4. People and roles

Single-operator design: the operator account is created locally
(`python -m harness.api seed-operator`); passwords are stored as salted hashes in
the local store; API keys for cloud providers live in the OS keychain, never on
disk. There is no central account, no third-party processor, and no marketing
list. **[DP — lawyer to confirm this shape satisfies IPPs 1–13 for a paid
multi-user-in-one-household tool.]**

## 5. Retention and deletion

You own the store. Deletion surfaces: matter deletion in the workspace, corpus
drop (`harness corpus drop --matter <ref> --yes`), vector purge
(`harness vectors delete --matter <ref> --yes`), and removing the store folder
itself. Backups are operator-managed — delete them with the store when a matter
ends. **[DP — retention schedule for the supervised pilot (Release B) pending.]**

## 6. Contact **[DP — placeholder pending support-channel ruling]**

Privacy contact: **[insert ruling]**. Until ruled, contact the operator directly.
