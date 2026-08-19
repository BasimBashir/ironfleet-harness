# RUNBOOK P0-7 — Encryption-at-rest + backup (Mac Minis)

Operator runbook for the privileged store volume on **Mini-1** and **Mini-2**.
Nothing here touches IronFleet containers; these are host-level, one-time-per-node
operations executed by hand on the hardware.

Scripts referenced below live in this repo at `src/harness/ops/`
(`p07_setup.sh`, `p07_verify.sh`) — copy them to the Mini, or run them from a
checkout there.

---

## 1. Prerequisites

- macOS **26.2 or later** on the node.
- An **admin** account on the Mini (sudo not required for the core steps, but
  admin is needed for `diskutil apfs addVolume` and writing to `/usr/local/bin`).
- A **second physical disk or APFS container** with free space for the volume
  (the setup script targets `disk3` by default — confirm with `diskutil list`
  first).
- rsync (ships with macOS; verify with `rsync --version`).

> **Windows dev machine note:** these scripts are **macOS-only**. Phase-0
> development happens anywhere (Windows/Linux/Mac); the encrypted privileged
> volume and the nightly backup job exist **only on the Mac Minis**. Do not
> attempt to run `p07_setup.sh` / `p07_verify.sh` anywhere else — they call
> `diskutil`, `tmutil`, and `fdesetup`, which exist only on macOS.

## 2. Setup — run `p07_setup.sh`

On each Mini:

```bash
bash p07_setup.sh
```

What it does:

1. Creates the encrypted APFS volume `IronFleetPriv` (AES-256, passphrase
   prompted interactively) mounted at `/Volumes/IronFleetPriv` — skipped if
   already present. If `disk3` is not the right container, the script prints a
   reminder; find yours with `diskutil list` and adjust.
2. Creates the privileged store layout:
   `/Volumes/IronFleetPriv/harness/sessions`,
   `/Volumes/IronFleetPriv/harness/trace`, `/Volumes/IronFleetPriv/backups`.
3. Adds a **Time Machine exclusion** for the volume — Time Machine must never
   see the privileged volume (architecture doc §2); backups are the versioned
   encrypted snapshots below instead.
4. Installs `/usr/local/bin/ironfleet-backup.sh` (rsync hard-link snapshots:
   each run copies `/Volumes/IronFleetPriv/harness` into
   `/Volumes/IronFleetPriv/backups/<timestamp>/`, hard-linking unchanged files
   against `backups/latest`, then repoints the `latest` symlink).

The script is idempotent-ish; read its output before re-running.

## 3. Schedule — nightly 02:30 launchd job

The backup script must run nightly. Create
`/Library/LaunchDaemons/com.ironfleet.backup.plist` on each Mini with exactly
this content:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ironfleet.backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/usr/local/bin/ironfleet-backup.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>2</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/var/log/ironfleet-backup.log</string>
  <key>StandardErrorPath</key>
  <string>/var/log/ironfleet-backup.log</string>
</dict>
</plist>
```

Then load it:

```bash
sudo chown root:wheel /Library/LaunchDaemons/com.ironfleet.backup.plist
sudo chmod 644 /Library/LaunchDaemons/com.ironfleet.backup.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.ironfleet.backup.plist
sudo launchctl enable system/com.ironfleet.backup
```

Sanity-check the same night (or force one run):

```bash
sudo launchctl kickstart system/com.ironfleet.backup
ls -l /Volumes/IronFleetPriv/backups/     # a new timestamped dir + latest symlink
tail /var/log/ironfleet-backup.log
```

Note: a LaunchDaemon runs before any user logs in. The encrypted volume must be
mounted for the backup to succeed — after a reboot, unlock/mount
`IronFleetPriv` once (the passphrase prompt or `diskutil apfs unlockVolume`)
and it stays mounted for the session. An unmounted volume makes the rsync fail
into the log; the log is how you notice.

## 4. Key / passphrase custody

- The `IronFleetPriv` passphrase is prompted once at volume creation. Store it
  in the **macOS Keychain** on that Mini (Keychain Access → new item, or
  `security add-generic-password -a "$USER" -s IronFleetPriv-volume -l "IronFleetPriv volume passphrase" -w`).
- **Escrow:** keep one offline copy of each node's passphrase (Mini-1 and
  Mini-2 use **different passphrases**) in the firm's physical key safe /
  sealed envelope, together with the other IronFleet escrowed secrets. If the
  Keychain item and the operator are both unavailable, the volume — and every
  backup on it — is unrecoverable. This is by design (encryption-at-rest), so
  escrow is mandatory, not optional.
- The passphrase never appears in this repo, in scripts, or in logs.

## 5. Verification — `p07_verify.sh` on every node

On **every** Mini, after setup and **again after every macOS update** (OS
updates can flip FileVault/disk state or drop exclusions):

```bash
bash p07_verify.sh
```

Expected output:

```
==> Time Machine exclusion set    (from setup; verify prints its own lines)
P0-7 OK: encrypted, excluded, backed up
```

It fails loudly (non-zero exit, `FAIL:` line) if any of: volume not encrypted,
Time Machine exclusion missing, `harness/sessions` missing, or
`/usr/local/bin/ironfleet-backup.sh` not executable. A `WARN: FileVault off`
line is advisory — full-disk FileVault on the OS volume is recommended but not
part of the P0-7 gate. Treat any `FAIL` as "node is not production-ready".

## 6. Restore drill — quarterly

Once per quarter, per node, prove the backups are actually restorable:

```bash
# 1. Restore the latest snapshot to /tmp (does not touch the live store)
rsync -a /Volumes/IronFleetPriv/backups/latest/ /tmp/ironfleet-restore-drill/

# 2. Open the trace db read-only and run a real query against it
sqlite3 "file:///tmp/ironfleet-restore-drill/trace/trace.db?mode=ro" \
  "SELECT COUNT(*), MAX(ts) FROM dispatches;"

# 3. Spot-check a session transcript is present and non-empty
find /tmp/ironfleet-restore-drill/sessions -type f | head
wc -c "$(find /tmp/ironfleet-restore-drill/sessions -type f | head -1)"
```

Record the result (date, node, row count, `MAX(ts)`, pass/fail, operator) in
the ops log. If the count is zero, the db won't open, or files are missing —
the backups are worthless; stop and fix before the next nightly run. Clean up
with `rm -rf /tmp/ironfleet-restore-drill` — the drill copy contains
privileged data and must not linger outside the encrypted volume.
