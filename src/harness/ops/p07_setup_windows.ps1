# P0-7/D13: Windows dev-tier encrypted store + versioned backup.
# BitLocker-gated store creation (fail-loud: no unencrypted privileged store is
# ever created silently), store layout, and a self-locating versioned backup
# script (robocopy /MIR snapshots + 'latest' junction). Task Scheduler
# registration is deliberately NOT installed here -- see RUNBOOK_P0_7.md
# (Windows section). -AcceptUnencryptedStore is the explicit, recorded CR-7
# deviation for dev machines whose operator accepts an unencrypted store.
#Requires -Version 5.1
param([switch]$AcceptUnencryptedStore)

$ErrorActionPreference = 'Stop'

# --- Store root: HARNESS_HOME wins, else %LOCALAPPDATA%\IronFleet\harness -------------------
$StoreRoot = if ($env:HARNESS_HOME) { $env:HARNESS_HOME } else { Join-Path (Join-Path $env:LOCALAPPDATA 'IronFleet') 'harness' }
Write-Host "==> store root: $StoreRoot"

# --- Fail loud unless the drive holding the store is BitLocker-protected -------------------
if ($StoreRoot -notmatch '^([A-Za-z]:)') {
    Write-Host "FAIL: store root '$StoreRoot' is not on a local drive (UNC or relative path)." -ForegroundColor Red
    Write-Host "      Set HARNESS_HOME to a path on a BitLocker-protected local drive, e.g. C:\...\harness." -ForegroundColor Red
    exit 1
}
$Drive = $Matches[1]
if (-not (Test-Path -LiteralPath "$Drive\")) {
    Write-Host "FAIL: drive $Drive is not present on this machine." -ForegroundColor Red
    exit 1
}

if ($AcceptUnencryptedStore) {
    Write-Host "==> DEVIATION (CR-7): -AcceptUnencryptedStore set -- BitLocker gate skipped;" -ForegroundColor Yellow
    Write-Host "      store will NOT be encrypted at rest. Operator-accepted risk on this machine;" -ForegroundColor Yellow
    Write-Host "      record the deviation. Default behavior without the flag is unchanged fail-loud." -ForegroundColor Yellow
}
else {
    $bde = Get-Command manage-bde.exe -ErrorAction SilentlyContinue
    if (-not $bde) {
        Write-Host "FAIL: manage-bde.exe not found -- this Windows edition has no manageable BitLocker" -ForegroundColor Red
        Write-Host "      (Home editions ship device encryption only, which manage-bde cannot drive)." -ForegroundColor Red
        Write-Host "      Remediation: use Windows Pro/Enterprise/Education, or host the store on a" -ForegroundColor Red
        Write-Host "      BitLocker-protected data drive and set HARNESS_HOME to it, then re-run:" -ForegroundColor Red
        Write-Host "      powershell -ExecutionPolicy Bypass -File .\p07_setup_windows.ps1" -ForegroundColor Red
        exit 1
    }

    # Do not redirect stderr to stdout here: under $ErrorActionPreference='Stop' on PS 5.1 a
    # redirected native stderr line becomes a terminating error. stderr (if any) just prints.
    $statusText = (manage-bde.exe -status $Drive) -join "`r`n"
    $bdeExit = $LASTEXITCODE
    if ($bdeExit -ne 0) {
        Write-Host "FAIL: cannot determine BitLocker status for drive $Drive (manage-bde exit code $bdeExit)." -ForegroundColor Red
        Write-Host "      manage-bde needs an elevated prompt on some builds. Open one and re-run:" -ForegroundColor Red
        Write-Host "        Start-Process powershell -Verb RunAs" -ForegroundColor Red
        Write-Host "        powershell -ExecutionPolicy Bypass -File .\p07_setup_windows.ps1" -ForegroundColor Red
        exit 1
    }
    if ($statusText -notmatch '(?m)^\s*Protection Status:\s*Protection On\b') {
        Write-Host "FAIL: drive $Drive is not BitLocker-protected (manage-bde -status: Protection Off)." -ForegroundColor Red
        Write-Host "      An unencrypted privileged store is never created (P0-7 fail-loud)." -ForegroundColor Red
        Write-Host "      Remediation, in an elevated PowerShell (Start-Process powershell -Verb RunAs):" -ForegroundColor Red
        Write-Host "        1. manage-bde -on $Drive -RecoveryPassword    # prints a 48-digit recovery password" -ForegroundColor Red
        Write-Host "        2. manage-bde -status $Drive                    # wait for: Conversion Status: Fully Encrypted" -ForegroundColor Red
        Write-Host "        3. manage-bde -protectors -get $Drive           # escrow the recovery password (RUNBOOK, custody)" -ForegroundColor Red
        Write-Host "        4. re-run: powershell -ExecutionPolicy Bypass -File .\p07_setup_windows.ps1" -ForegroundColor Red
        exit 1
    }
    Write-Host "==> BitLocker protection ON for $Drive"
}

# --- Store layout: sessions\, trace\, backups\ ------------------------------------------------
foreach ($d in 'sessions', 'trace', 'backups') {
    $p = Join-Path $StoreRoot $d
    if (Test-Path -LiteralPath $p) { Write-Host "==> exists   $p" }
    else { New-Item -ItemType Directory -Path $p | Out-Null; Write-Host "==> created  $p" }
}

# --- Versioned backup job (param-less, self-locating via $PSScriptRoot) -----------------------
# Single-quoted here-string: nothing in the body is interpolated when written.
$BackupScript = Join-Path $StoreRoot 'ironfleet-backup.ps1'
@'
# ironfleet-backup.ps1 -- P0-7/D13 versioned backup of the harness store (Windows).
# Param-less by design: Task Scheduler runs it nightly at 02:30 (registration is a
# documented manual step -- see RUNBOOK_P0_7.md). Each run mirrors the store into
# backups\<yyyyMMdd-HHmmss> (robocopy /MIR, backups dir itself excluded) and repoints
# the 'latest' junction at the fresh snapshot.
# robocopy exit codes 0-7 are success (1 = files copied); >= 8 is a real failure.
$ErrorActionPreference = 'Stop'

$storeRoot  = $PSScriptRoot
$backupRoot = Join-Path $storeRoot 'backups'
$stamp      = Get-Date -Format 'yyyyMMdd-HHmmss'
$dest       = Join-Path $backupRoot $stamp

New-Item -ItemType Directory -Path $dest -Force | Out-Null
robocopy $storeRoot $dest /MIR /XD $backupRoot /R:2 /W:5 /NJH /NJS /NDL /NP
if ($LASTEXITCODE -ge 8) {
    Write-Error "ironfleet-backup: robocopy failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

# Repoint 'latest' (a junction: no admin rights needed, NTFS only). Directory.Delete
# removes the reparse point itself, never the previous snapshot's contents.
$latest = Join-Path $backupRoot 'latest'
if (Test-Path -LiteralPath $latest) { [System.IO.Directory]::Delete($latest) }
New-Item -ItemType Junction -Path $latest -Target $dest | Out-Null
exit 0
'@ | Set-Content -LiteralPath $BackupScript -Encoding ASCII
Write-Host "==> wrote    $BackupScript"

# ---------------------------------------------------------------------------------------------
# Task Scheduler registration is NOT installed by this script (the runbook owns
# scheduling). To register the 02:30 nightly job, run in an elevated PowerShell
# (full copy-paste variants in RUNBOOK_P0_7.md, Windows -> Backup scheduling):
#
#   schtasks /Create /TN "IronFleet Backup" /SC DAILY /ST 02:30 ^
#     /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"<store-root>\ironfleet-backup.ps1\""
# ---------------------------------------------------------------------------------------------
Write-Host "==> next: register the nightly job and run p07_verify_windows.ps1 (RUNBOOK_P0_7.md)"
Write-Host "P0-7 setup OK (Windows): store ready at $StoreRoot"
exit 0
