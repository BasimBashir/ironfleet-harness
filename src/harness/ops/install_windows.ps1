# IronFleet harness -- the one Windows install script (S7j-W step 2, spec 13 s2.1).
# Idempotent: every step verifies before it acts. Run from the extracted zip root
# (it self-locates by walking up to pyproject.toml) or from a checkout.
#
#   powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
#
# Prerequisites checked, not installed: CPython >= 3.12, Node/npm (for the pinned
# opencode), Ollama serving thomson1-chat (+ qwen3.8:27b for the toolpath class,
# + bge-m3 for embeddings). Network required for pip/npm on a fresh machine.
# ASCII-only on purpose: PowerShell 5.1 reads a BOM-less UTF-8 script as ANSI and the
# parser chokes on multi-byte characters (observed live 2026-10-12).
#Requires -Version 5.1
param([switch]$SkipStoreSetup)
$ErrorActionPreference = 'Stop'

# --- self-locate the distribution root -------------------------------------------------
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = $null
for ($i = 0; $i -lt 6 -and $dir; $i++) {
    if (Test-Path (Join-Path $dir 'pyproject.toml')) { $root = $dir; break }
    $dir = Split-Path -Parent $dir
}
if (-not $root) { Write-Host "FAIL: cannot find pyproject.toml above $($MyInvocation.MyCommand.Path)" -ForegroundColor Red; exit 1 }
Write-Host "==> distribution root: $root"
Set-Location $root

function Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; exit 1 }

# --- 1. Python >= 3.12 + venv ----------------------------------------------------------
$py = $null
if (Test-Path (Join-Path $root '.venv\Scripts\python.exe')) {
    $py = Join-Path $root '.venv\Scripts\python.exe'
} else {
    foreach ($candidate in @(@('py', '-3'), @('python'))) {
        try {
            $v = & $candidate[0] $candidate[1] --version 2>$null
            if ($v -match 'Python (\d+)\.(\d+)' -and
                [int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge 12) {
                & $candidate[0] $candidate[1] -m venv (Join-Path $root '.venv')
                $py = Join-Path $root '.venv\Scripts\python.exe'
                break
            }
        } catch { }
    }
}
if (-not $py) { Fail "no CPython >= 3.12 found (install python.org Python or the py launcher)" }
Write-Host "==> python: $py"

# --- 2. editable install (the product tree IS the repo tree -- data/ stays at repo paths)
& $py -m pip install -q -e $root
if ($LASTEXITCODE -ne 0) { Fail "pip install -e . failed (network? pip?)" }
Write-Host "==> harness installed (editable)"

# --- 3. opencode pin (single source: harness.packaging.macdist.PINS) --------------------
$pin = & $py -c "from harness.packaging.macdist import PINS; print(PINS['opencode'])"
if ($LASTEXITCODE -ne 0 -or -not $pin) { Fail "cannot read the opencode pin from macdist.PINS" }
$pinVersion = ($pin -replace '^opencode-ai@', '')
$have = $null
try { $have = (& opencode --version 2>$null | Out-String).Trim() } catch { }
if (-not $have -or $have -notmatch [regex]::Escape($pinVersion)) {
    Write-Host "==> installing opencode pin ($have -> $pinVersion)"
    & npm install -g $pin
    if ($LASTEXITCODE -ne 0) { Fail "npm install -g $pin failed (Node/npm on PATH? network?)" }
} else {
    Write-Host "==> opencode already pinned: $have"
}

# --- 4. global autoupdate:false (S7c ruling 2026-10-12) -- create if missing, VERIFY if not
$ocCfg = Join-Path $env:USERPROFILE '.config\opencode\opencode.jsonc'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ocCfg) | Out-Null
if (-not (Test-Path $ocCfg)) {
    $body = @'
{
  "$schema": "https://opencode.ai/config.json",
  // IronFleet S7c ruling (2026-10-12): the binary is part of the harness -- the mount's
  // guard hooks are version-sensitive and re-verified per upgrade, so the GLOBAL config
  // pins it. The mount-level setting only ever protected mount workspaces.
  "autoupdate": false
}
'@
    Set-Content -Path $ocCfg -Value $body -Encoding UTF8
    Write-Host "==> wrote global $ocCfg (autoupdate: false)"
} elseif ((Get-Content $ocCfg -Raw) -notmatch '"autoupdate"\s*:\s*false') {
    Fail "$ocCfg exists without autoupdate:false -- the mount's guard hooks are version-sensitive (S7c ruling). Set it or remove the file and re-run."
} else {
    Write-Host "==> global autoupdate:false verified"
}

# --- 5. the privileged store (P0-7 fail-loud BitLocker gate; skipped when present) ------
$store = if ($env:HARNESS_HOME) { $env:HARNESS_HOME }
         else { Join-Path (Join-Path $env:LOCALAPPDATA 'IronFleet') 'harness' }
if ($SkipStoreSetup) {
    Write-Host "==> store setup skipped (-SkipStoreSetup); expected at $store"
} elseif (Test-Path $store) {
    Write-Host "==> store already present: $store"
} else {
    Write-Host "==> creating the privileged store (BitLocker-gated, P0-7)"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root 'src\harness\ops\p07_setup_windows.ps1')
    if ($LASTEXITCODE -ne 0) { Fail "store setup failed (BitLocker gate? see the message above)" }
}

# --- 6. proof ----------------------------------------------------------------------------
$ver = & (Join-Path $root '.venv\Scripts\harness.exe') --version
if ($LASTEXITCODE -ne 0) { Fail "harness --version failed" }
Write-Host "==> $ver"
Write-Host ""
Write-Host "NEXT: start Ollama with the models, then prove one drive:" -ForegroundColor Cyan
Write-Host "    ollama serve   (models: thomson1-chat, qwen3.8:27b, bge-m3)" -ForegroundColor Cyan
Write-Host "    .venv\Scripts\harness.exe drive --matter-ref <uuid>" -ForegroundColor Cyan
Write-Host "    .venv\Scripts\harness.exe serve   (the egress proxy, 127.0.0.1:7373)" -ForegroundColor Cyan
exit 0
