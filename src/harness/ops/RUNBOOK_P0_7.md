# RUNBOOK P0-7 — Encryption-at-rest + versioned backup (per OS)

Operator runbook for the harness store on **macOS (Mini-1 / Mini-2)**, **Windows**,
and **Linux**. Nothing here touches IronFleet containers; these are host-level,
one-time-per-machine operations executed by hand on the hardware.

**Same guarantees, same command pattern, per-OS mechanics.** On every OS the
store must be: (1) encrypted at rest before anything is written into it,
(2) excluded from any system-wide backup that is not itself encrypted,
(3) covered by a versioned encrypted backup job run nightly at 02:30, and
(4) verifiable by a fail-loud check whose non-zero exit means "not
production-ready". Only the mechanics differ — BitLocker/LUKS instead of
encrypted APFS, robocopy junctions/rsync hard links instead of rsync alone,
Task Scheduler/cron instead of launchd.

Scripts live in this repo at `src/harness/ops/` — copy them to the machine, or
run them from a checkout there:

| OS      | Setup                        | Verify                        |
|---------|------------------------------|-------------------------------|
| macOS   | `p07_setup_macos.sh`         | `p07_verify_macos.sh`         |
| Windows | `p07_setup_windows.ps1`      | `p07_verify_windows.ps1`      |
| Linux   | `p07_setup_linux.sh`         | `p07_verify_linux.sh`         |

> **Tier note:** privileged matters ultimately live on the **Mac tier** — the
> Mac Minis are where the privileged corpus store and the production privileged
> workloads run. The Windows and Linux stores are **dev-tier**: they hold
> development session transcripts, traces, and backups on the developer's own
> encrypted disk. The guarantees (encrypted at rest, versioned backup,
> fail-loud verify) are identical on all three; the blast radius is not.
>
> **`HARNESS_HOME`** sets the store root on **every OS** (it overrides the
> per-OS default in all six scripts). Point it at a location on the encrypted
> volume before running setup if you do not want the default.

---

## 1. macOS (Mini-1, Mini-2)

### 1.1 Prerequisites

- macOS **26.2 or later** on the node.
- An **admin** account on the Mini (sudo not required for the core steps, but
  admin is needed for `diskutil apfs addVolume` and writing to `/usr/local/bin`).
- A **second physical disk or APFS container** with free space for the volume
  (the setup script targets `disk3` by default — confirm with `diskutil list`
  first).
- rsync (ships with macOS; verify with `rsync --version`).

### 1.2 Setup — `p07_setup_macos.sh`

On each Mini:

```bash
bash p07_setup_macos.sh
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

### 1.3 Backup scheduling — nightly 02:30 launchd job

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

### 1.4 Key / passphrase custody

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

### 1.5 Verification — `p07_verify_macos.sh` on every node

On **every** Mini, after setup and **again after every macOS update** (OS
updates can flip FileVault/disk state or drop exclusions):

```bash
bash p07_verify_macos.sh
```

Expected output:

```
P0-7 OK: encrypted, excluded, backed up
```

It fails loudly (non-zero exit, `FAIL:` line) if any of: volume not encrypted,
Time Machine exclusion missing, `harness/sessions` missing, or
`/usr/local/bin/ironfleet-backup.sh` not executable. A `WARN: FileVault off`
line is advisory — full-disk FileVault on the OS volume is recommended but not
part of the P0-7 gate. Treat any `FAIL` as "node is not production-ready".

### 1.6 Restore drill — quarterly

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

---

## 2. Windows (dev machines)

### 2.1 Prerequisites

- Windows 10/11 **Pro, Enterprise, or Education** with **BitLocker** available
  (Home editions only ship device encryption, which `manage-bde` cannot drive —
  the scripts detect this and fail loud with remediation).
- PowerShell **5.1 or later** (inbox on every supported Windows build).
- A BitLocker-protected drive to host the store. The default store root is
  `%LOCALAPPDATA%\IronFleet\harness` (i.e. on the OS drive, protected by
  BitLocker device encryption / OS-drive protection); set **`HARNESS_HOME`** to
  move it to any other protected drive.
- No admin rights needed for setup itself; `manage-bde -status` may require an
  elevated prompt on some builds (the script says so if it hits that).

### 2.2 Setup — `p07_setup_windows.ps1`

```powershell
powershell -ExecutionPolicy Bypass -File .\p07_setup_windows.ps1
```

What it does:

1. Resolves the store root (`HARNESS_HOME` if set, else
   `%LOCALAPPDATA%\IronFleet\harness`) and the drive holding it.
2. **Fail-loud BitLocker gate** — runs `manage-bde -status <drive>:` and
   requires `Protection Status: Protection On`. If protection is off (or
   `manage-bde` is missing / unreadable), it prints the exact remediation
   (`manage-bde -on`, wait for *Fully Encrypted*, escrow the recovery
   password) and **exits 1 without creating anything** — there is never a
   silently unencrypted privileged store.
3. Creates the store layout: `<store>\sessions`, `<store>\trace`,
   `<store>\backups` (existing dirs are left untouched — idempotent).
4. Writes `<store>\ironfleet-backup.ps1`: a param-less, self-locating backup
   job. Each run `robocopy /MIR`s the store into
   `<store>\backups\<yyyyMMdd-HHmmss>\` (excluding the backups dir itself),
   then repoints a `latest` **junction** at the fresh snapshot. robocopy exit
   codes 0–7 are success (1 = files copied); ≥ 8 fails the job.

The script does **not** register the scheduled task — that is §2.3, run by hand.

### 2.3 Backup scheduling — nightly 02:30 Task Scheduler job (manual)

Register the job by hand (elevated PowerShell is easiest — `schtasks /Create`
for a per-machine task needs it):

```powershell
$store = if ($env:HARNESS_HOME) { $env:HARNESS_HOME } else { "$env:LOCALAPPDATA\IronFleet\harness" }
schtasks /Create /TN "IronFleet Backup" /SC DAILY /ST 02:30 /RU "$env:USERNAME" /RL LIMITED `
  /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$store\ironfleet-backup.ps1`""
```

(On plain cmd, the caret above becomes `^` and the backtick-escapes become
regular `\"...\"` quoting.)

Force one run and sanity-check the same night:

```powershell
schtasks /Run /TN "IronFleet Backup"
Get-ChildItem "$store\backups"                      # a new timestamped dir + 'latest' junction
Get-Content "$env:LOCALAPPDATA\IronFleet\harness\backups\latest\sessions\*" -TotalCount 1 -ErrorAction SilentlyContinue
```

The task runs whether or not the console is open (Task Scheduler wakes the
session as needed). If the drive is locked (BitLocker suspended, drive removed)
the robocopy fails into the task's Last Result — check it after registering:

```powershell
schtasks /Query /TN "IronFleet Backup" /V /FO LIST   # Last Result 0 = ok
```

### 2.4 Key / recovery-password custody

- BitLocker escrows a **48-digit recovery password** when the drive is
  encrypted. Print it with `manage-bde -protectors -get <drive>: /Type RecoveryPassword`
  (elevated). Keep one offline copy in the firm's physical key safe / sealed
  envelope, together with the other IronFleet escrowed secrets.
- If the machine is domain/AzureAD-joined, also confirm the recovery password
  is escrowed to AD / Azure (the `manage-bde -protectors -get` output shows
  the escrow state). Local escrow in the safe remains mandatory either way.
- The recovery password never appears in this repo, in scripts, or in logs.
- If the drive uses **auto-unlock** (data drives unlocked by the OS drive),
  custody of the OS drive's recovery password covers the data drive too —
  record both.

### 2.5 Verification — `p07_verify_windows.ps1`

After setup, after every Windows/BitLocker change, and after any drive
re-plug:

```powershell
powershell -ExecutionPolicy Bypass -File .\p07_verify_windows.ps1
```

Expected output:

```
OK:   BitLocker protection ON for C:
OK:   <store>\sessions
OK:   <store>\trace
OK:   <store>\backups
OK:   <store>\ironfleet-backup.ps1
OK:   Task Scheduler job 'IronFleet Backup' registered
P0-7 OK (Windows): encrypted, laid out, backed up
```

It fails loudly (non-zero exit, `FAIL:` line) if any of: BitLocker protection
off, `manage-bde` unreadable, any of the three dirs missing, or the backup
script missing. A `WARN: Task Scheduler job … not registered` line is
**advisory only** — registration is the documented manual step in §2.3; the
verify script never fails on it. Treat any `FAIL` as "machine is not
production-ready".

### 2.6 Restore drill — quarterly

Once per quarter, per machine, prove the backups are actually restorable
(PowerShell, from any prompt):

```powershell
$store  = if ($env:HARNESS_HOME) { $env:HARNESS_HOME } else { "$env:LOCALAPPDATA\IronFleet\harness" }
$drill  = "$env:TEMP\ironfleet-restore-drill"

# 1. Restore the latest snapshot to %TEMP% (does not touch the live store)
robocopy "$store\backups\latest" $drill /E /NJH /NJS

# 2. Open the trace db read-only and run a real query against it
#    (uses the inbox sqlite3 if on PATH; otherwise open it in any SQLite browser)
sqlite3 "file:///$($drill -replace '\\','/')/trace/trace.db?mode=ro" "SELECT COUNT(*), MAX(ts) FROM dispatches;"

# 3. Spot-check a session transcript is present and non-empty
Get-ChildItem "$drill\sessions" -Recurse -File | Select-Object -First 5
(Get-ChildItem "$drill\sessions" -Recurse -File | Select-Object -First 1).Length
```

Record the result (date, machine, row count, `MAX(ts)`, pass/fail, operator)
in the ops log. If the count is zero, the db won't open, or files are missing —
the backups are worthless; stop and fix before the next nightly run. Clean up
with `Remove-Item -Recurse -Force $drill` — the drill copy contains privileged
data and must not linger outside the encrypted drive.

---

## 3. Linux (dev machines / CI hosts)

### 3.1 Prerequisites

- A Linux host whose **home volume is LUKS-encrypted** (or a dedicated LUKS
  data volume you will point `HARNESS_HOME` at).
- bash, `findmnt`, `lsblk`, `df` (all in util-linux / coreutils on every
  mainstream distribution), and **rsync** for the backup job.
- No root required: the store lives under `$HOME` and the backup script is
  installed inside the store itself.

### 3.2 Setup — `p07_setup_linux.sh`

```bash
bash p07_setup_linux.sh
```

What it does:

1. Resolves the store root (`HARNESS_HOME` if set, else
   `~/.local/share/ironfleet/harness`, the XDG default).
2. **Fail-loud LUKS gate (best-effort check)** — resolves the mount holding
   the store (`findmnt -T`, falling back to `df` on the deepest existing
   ancestor). The store passes if that filesystem's source is a
   `/dev/mapper/*` device that `lsblk` types `crypt`, **or** if
   `/etc/crypttab` declares an active LUKS container (secondary evidence for
   stacked setups). Otherwise it prints remediation (move `HARNESS_HOME` onto
   a LUKS volume, or encrypt home per your distribution's docs) and **exits 1
   without creating anything**.
3. Creates the store layout: `<store>/sessions`, `<store>/trace`,
   `<store>/backups` (idempotent).
4. Writes `<store>/ironfleet-backup.sh` (mode 700): a param-less,
   self-locating backup job. Each run `rsync -a --delete --link-dest=<store>/backups/latest`s
   the store into `<store>/backups/<stamp>/` (excluding the backups dir
   itself), then repoints the `latest` symlink — unchanged files are
   hard-linked, so each snapshot costs only what changed.

The script does **not** install scheduling — that is §3.3, run by hand.

### 3.3 Backup scheduling — nightly 02:30 cron or systemd timer (manual)

**cron** (simplest; logs next to the store):

```bash
mkdir -p ~/.local/state
( crontab -l 2>/dev/null; echo '30 2 * * * $HOME/.local/share/ironfleet/harness/ironfleet-backup.sh >> $HOME/.local/state/ironfleet-backup.log 2>&1' ) | crontab -
```

(If you set `HARNESS_HOME`, change the path in the entry to match.)

**systemd user timer** (survives reboots without a lingering login only if
`enable-linger` is set):

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/ironfleet-backup.service <<'EOF'
[Unit]
Description=IronFleet harness store versioned backup (P0-7)

[Service]
Type=oneshot
ExecStart=%h/.local/share/ironfleet/harness/ironfleet-backup.sh
EOF

cat > ~/.config/systemd/user/ironfleet-backup.timer <<'EOF'
[Unit]
Description=Nightly IronFleet backup at 02:30 (P0-7)

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now ironfleet-backup.timer
loginctl enable-linger "$USER"   # timers fire without an active login session
```

Force one run and sanity-check the same night:

```bash
systemctl --user start ironfleet-backup.service   # or wait for 02:30
ls -l ~/.local/share/ironfleet/harness/backups/   # a new timestamped dir + latest -> symlink
tail ~/.local/state/ironfleet-backup.log          # cron variant only
```

Note: if the LUKS volume holding the store is not auto-unlocked at boot, the
nightly run fails until it is unlocked — the log / journal
(`journalctl --user -u ironfleet-backup.service`) is how you notice.

### 3.4 Key / passphrase custody

- The LUKS **passphrase** (and any token/TPM auto-unlock configuration) is
  whatever the machine's disk-encryption setup uses. Print active slots with
  `sudo cryptsetup luksDump <device> | grep -A3 'Key Slot'`.
- **Escrow:** keep one offline copy of the LUKS passphrase (or a printed
  LUKS header backup + passphrase: `sudo cryptsetup luksHeaderBackup
  <device> --header-backup-file <offline-path>`) in the firm's physical key
  safe / sealed envelope, together with the other IronFleet escrowed secrets.
  If the passphrase and the operator are both unavailable, the store — and
  every backup on it — is unrecoverable. This is by design
  (encryption-at-rest), so escrow is mandatory, not optional.
- The passphrase never appears in this repo, in scripts, or in logs.

### 3.5 Verification — `p07_verify_linux.sh`

After setup, after every kernel/distribution upgrade, and after any disk
re-plug:

```bash
bash p07_verify_linux.sh
```

Expected output:

```
OK:   /home is on /dev/mapper/... (lsblk TYPE=crypt)
OK:   ~/.local/share/ironfleet/harness/sessions
OK:   ~/.local/share/ironfleet/harness/trace
OK:   ~/.local/share/ironfleet/harness/backups
OK:   ~/.local/share/ironfleet/harness/ironfleet-backup.sh
OK:   cron entry for ironfleet-backup.sh present
P0-7 OK (Linux): encrypted, laid out, backed up
```

It fails loudly (non-zero exit, `FAIL:` line) if any of: the home volume not
verifiably LUKS-encrypted, any of the three dirs missing, or the backup
script missing/not executable. A `WARN: no cron/systemd-timer registration …`
line is **advisory only** — registration is the documented manual step in
§3.3; the verify script never fails on it. Treat any `FAIL` as "machine is
not production-ready".

### 3.6 Restore drill — quarterly

Once per quarter, per machine, prove the backups are actually restorable:

```bash
STORE="${HARNESS_HOME:-$HOME/.local/share/ironfleet/harness}"

# 1. Restore the latest snapshot to /tmp (does not touch the live store)
rsync -a "$STORE/backups/latest/" /tmp/ironfleet-restore-drill/

# 2. Open the trace db read-only and run a real query against it
sqlite3 "file:///tmp/ironfleet-restore-drill/trace/trace.db?mode=ro" \
  "SELECT COUNT(*), MAX(ts) FROM dispatches;"

# 3. Spot-check a session transcript is present and non-empty
find /tmp/ironfleet-restore-drill/sessions -type f | head
wc -c "$(find /tmp/ironfleet-restore-drill/sessions -type f | head -1)"
```

Record the result (date, machine, row count, `MAX(ts)`, pass/fail, operator)
in the ops log. If the count is zero, the db won't open, or files are missing —
the backups are worthless; stop and fix before the next nightly run. Clean up
with `rm -rf /tmp/ironfleet-restore-drill` — the drill copy contains privileged
data and must not linger outside the encrypted volume.
