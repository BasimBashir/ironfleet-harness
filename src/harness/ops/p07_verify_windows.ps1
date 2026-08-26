# P0-7/D13 verification (Windows): fail loudly if any guarantee is missing.
# Checks: BitLocker protection ON, sessions\trace\backups dirs exist, backup
# script present. WARNs (does not fail) when the Task Scheduler job is absent --
# registration is a documented manual step, not something setup installs.
# -AcceptUnencryptedStore (matching setup) downgrades the BitLocker check to an
# advisory WARN for the recorded CR-7 deviation; everything else still fails loud.
#Requires -Version 5.1
param([switch]$AcceptUnencryptedStore)

$ErrorActionPreference = 'Continue'   # every check runs; failures accumulate in $fail

$fail = 0

# --- Store root: HARNESS_HOME wins, else %LOCALAPPDATA%\IronFleet\harness -------------------
$StoreRoot = if ($env:HARNESS_HOME) { $env:HARNESS_HOME } else { Join-Path (Join-Path $env:LOCALAPPDATA 'IronFleet') 'harness' }
Write-Host "==> store root: $StoreRoot"

if ($StoreRoot -notmatch '^([A-Za-z]:)') {
    Write-Host "FAIL: store root '$StoreRoot' is not on a local drive (UNC or relative path)." -ForegroundColor Red
    Write-Host "      Set HARNESS_HOME to a path on a BitLocker-protected local drive." -ForegroundColor Red
    exit 1
}
$Drive = $Matches[1]

# --- BitLocker protection must be ON (unless the CR-7 deviation flag is set) -------------------
if ($AcceptUnencryptedStore) {
    Write-Host "WARN: -AcceptUnencryptedStore -- store is NOT encrypted at rest (CR-7 deviation, operator-accepted)." -ForegroundColor Yellow
}
elseif (-not (Get-Command manage-bde.exe -ErrorAction SilentlyContinue)) {
    Write-Host "FAIL: manage-bde.exe not found -- cannot verify BitLocker (Home edition?)." -ForegroundColor Red
    $fail = 1
}
else {
    $statusText = (manage-bde.exe -status $Drive) -join "`r`n"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAIL: manage-bde -status $Drive exited $LASTEXITCODE (elevation may be required)." -ForegroundColor Red
        $fail = 1
    }
    elseif ($statusText -notmatch '(?m)^\s*Protection Status:\s*Protection On\b') {
        Write-Host "FAIL: drive $Drive is not BitLocker-protected (see p07_setup_windows.ps1 remediation)." -ForegroundColor Red
        $fail = 1
    }
    else { Write-Host "OK:   BitLocker protection ON for $Drive" }
}

# --- Store layout ------------------------------------------------------------------------------
foreach ($d in 'sessions', 'trace', 'backups') {
    $p = Join-Path $StoreRoot $d
    if (Test-Path -LiteralPath $p -PathType Container) { Write-Host "OK:   $p" }
    else { Write-Host "FAIL: $p missing (re-run p07_setup_windows.ps1)" -ForegroundColor Red; $fail = 1 }
}

# --- Backup script present ----------------------------------------------------------------------
$BackupScript = Join-Path $StoreRoot 'ironfleet-backup.ps1'
if (Test-Path -LiteralPath $BackupScript -PathType Leaf) { Write-Host "OK:   $BackupScript" }
else { Write-Host "FAIL: $BackupScript missing (re-run p07_setup_windows.ps1)" -ForegroundColor Red; $fail = 1 }

# --- Scheduled job (WARN only: registration is manual, documented in the runbook) --------------
$job = schtasks.exe /Query /TN 'IronFleet Backup' 2>$null
if (($LASTEXITCODE -eq 0) -and ($job -ne $null)) { Write-Host "OK:   Task Scheduler job 'IronFleet Backup' registered" }
else {
    Write-Host "WARN: Task Scheduler job 'IronFleet Backup' not registered (manual step -- RUNBOOK_P0_7.md, Windows -> Backup scheduling)." -ForegroundColor Yellow
}

# --- Verdict -------------------------------------------------------------------------------------
if ($fail -eq 0) {
    if ($AcceptUnencryptedStore) { Write-Host 'P0-7 OK (Windows, CR-7 deviation): laid out, backed up -- NOT encrypted at rest' }
    else { Write-Host 'P0-7 OK (Windows): encrypted, laid out, backed up' }
}
else { Write-Host 'P0-7 FAILED (Windows): see FAIL lines above; node is not production-ready.' -ForegroundColor Red }
exit $fail
