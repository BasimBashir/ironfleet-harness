# P0-7: register the nightly 'IronFleet Backup' scheduled task (Windows).
# Wraps Register-ScheduledTask so the manual §2.3 step in RUNBOOK_P0_7.md is
# paste-safe: S4U logon (no stored password, runs whether the user is logged on
# or not) and -StartWhenAvailable (a missed run catches up at next wake/boot).
# Elevated prompt required (per-machine task). Idempotent: re-registering
# replaces the existing task.
#Requires -Version 5.1
param([string]$At = '02:30')   # override for testing, e.g. -At 14:30

$ErrorActionPreference = 'Stop'

$StoreRoot    = if ($env:HARNESS_HOME) { $env:HARNESS_HOME } else { Join-Path (Join-Path $env:LOCALAPPDATA 'IronFleet') 'harness' }
$BackupScript = Join-Path $StoreRoot 'ironfleet-backup.ps1'
if (-not (Test-Path -LiteralPath $BackupScript -PathType Leaf)) {
    Write-Host "FAIL: $BackupScript not found -- run p07_setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

$action    = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$BackupScript`""
$trigger   = New-ScheduledTaskTrigger -Daily -At $At
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# LogonType lives on the Principal, not on Register-ScheduledTask (PS 5.1 has no -LogonType there)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U

Unregister-ScheduledTask -TaskName 'IronFleet Backup' -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName 'IronFleet Backup' -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal | Out-Null
Write-Host "==> registered 'IronFleet Backup' (daily at $At, S4U, catch-up on wake) for $BackupScript"

Start-ScheduledTask -TaskName 'IronFleet Backup'
Start-Sleep -Seconds 5
$info = Get-ScheduledTask -TaskName 'IronFleet Backup' | Get-ScheduledTaskInfo
Write-Host ("==> forced one run: LastTaskResult={0} (0 = ok, 267009 = still running) NextRunTime={1}" -f $info.LastTaskResult, $info.NextRunTime)
Write-Host "==> confirm a new snapshot: Get-ChildItem `"$StoreRoot\backups`"  (new timestamped dir; 'latest' repointed)"
