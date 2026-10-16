# IronFleet harness -- first-run verify + drive smoke (R2, spec 15 s2.2).
# The Windows twin of verify_macos_install.sh. Run AFTER install_windows.ps1, once
# Ollama is up. Every value is read from the code (PINS, resolve_store_root) so the
# script cannot drift from it. Fails loudly; exit 0 only when every check passes.
#
#   powershell -ExecutionPolicy Bypass -File .\verify_windows_install.ps1
#   powershell -ExecutionPolicy Bypass -File .\verify_windows_install.ps1 -WithDriveSmoke
#
# -WithDriveSmoke runs ONE real gated dispatch (harness drive, extraction class) --
# the end-to-end proof that the install can serve a matter. ~2-in-7 opencode startup
# hangs are known on some boxes; this script does not retry, just re-run it.
# -AcceptUnencryptedStore downgrades the store encryption check to the recorded CR-7
# deviation (same flag the installer and p07 scripts take). ASCII-only on purpose
# (PS 5.1 reads BOM-less UTF-8 as ANSI -- observed live 2026-10-12).
#Requires -Version 5.1
param([switch]$WithDriveSmoke, [switch]$AcceptUnencryptedStore)
$ErrorActionPreference = 'Continue'   # every check runs; failures accumulate in $fail
$fail = 0
function Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; $script:fail = 1 }
function Warn($msg) { Write-Host "WARN: $msg" -ForegroundColor Yellow }

# --- self-locate the distribution root (same walk as the installer) --------------------
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = $null
for ($i = 0; $i -lt 6 -and $dir; $i++) {
    if (Test-Path (Join-Path $dir 'pyproject.toml')) { $root = $dir; break }
    $dir = Split-Path -Parent $dir
}
if (-not $root) { Write-Host "FAIL: cannot find pyproject.toml above $($MyInvocation.MyCommand.Path)" -ForegroundColor Red; exit 1 }
Write-Host "==> distribution root: $root"
$py = Join-Path $root '.venv\Scripts\python.exe'
$harness = Join-Path $root '.venv\Scripts\harness.exe'

# --- 1. venv + the CLI runs --------------------------------------------------------------
if (-not (Test-Path $py)) { Fail "no venv at $root\.venv -- run install_windows.ps1 first" }
else {
    $ver = & $harness --version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $ver) { Fail "harness --version failed under the venv" }
    else { Write-Host "OK:   $ver" }
}

# --- 2. opencode on PATH and matching the pin (PINS is the single source) -----------------
if (Test-Path $py) {
    $pin = & $py -c "from harness.packaging.macdist import PINS; print(PINS['opencode'])"
    if ($LASTEXITCODE -ne 0 -or -not $pin) { Fail "cannot read the opencode pin from macdist.PINS" }
    else {
        $pinVersion = ($pin -replace '^opencode-ai@', '')
        $have = $null
        try { $have = (& opencode --version 2>$null | Out-String).Trim() } catch { }
        if (-not $have) { Fail "opencode not on PATH -- bootstrap the pinned $pin (npm install -g $pin)" }
        elseif ($have -notmatch [regex]::Escape($pinVersion)) {
            Fail "opencode drift: installed '$have' != pinned '$pin' -- the mount's guard hooks are version-sensitive (S7c ruling). Re-run install_windows.ps1 to restore the pin."
        } else { Write-Host "OK:   opencode pinned: $have" }
    }

    # --- 3. autoupdate is off in the GLOBAL config (S7c decision, macOS twin check 2) -------
    $ocCfg = Join-Path $env:USERPROFILE '.config\opencode\opencode.jsonc'
    if (-not (Test-Path $ocCfg)) { Fail "$ocCfg missing -- re-run install_windows.ps1" }
    elseif ((Get-Content $ocCfg -Raw) -notmatch '"autoupdate"\s*:\s*false') {
        Fail "autoupdate:false missing from $ocCfg -- an auto-updated binary breaks the guard-hook pin (S7c ruling)"
    } else { Write-Host "OK:   global autoupdate:false" }

    # --- 4. the store resolves (never the library fallback) + deep P0-7 checks ---------------
    $src = & $py -c "from harness.paths import resolve_store_root; print(resolve_store_root()[1])"
    if ($LASTEXITCODE -ne 0 -or -not $src) { Fail "resolve_store_root() failed" }
    elseif ($src -eq 'library-fallback') {
        Fail "store is off the encrypted volume (source=library-fallback) -- run p07_setup_windows.ps1 or set HARNESS_HOME"
    } else { Write-Host "OK:   store source: $src" }
    # deep store checks (layout, backup script, BitLocker) stay in ONE verifier:
    $p07args = @('-NoProfile', '-ExecutionPolicy', 'Bypass',
                 '-File', (Join-Path $root 'src\harness\ops\p07_verify_windows.ps1'))
    if ($AcceptUnencryptedStore) { $p07args += '-AcceptUnencryptedStore' }
    & powershell @p07args
    if ($LASTEXITCODE -ne 0) { Fail "P0-7 store verification failed (see its FAIL lines above)" }
}

# --- 5. Ollama reachable + the three bootstrap models present ------------------------------
$OLLAMA = 'http://127.0.0.1:11434'
$required = @('thomson1-chat:latest', 'qwen3.8:27b', 'bge-m3:567m')
$tags = $null
try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri "$OLLAMA/api/tags" -TimeoutSec 5
    $tags = ($resp.Content | ConvertFrom-Json).models | ForEach-Object { $_.name }
} catch { }
if (-not $tags) {
    Fail "Ollama not reachable at $OLLAMA -- start it ('ollama serve') and re-run"
} else {
    foreach ($m in $required) {
        if ($tags -contains $m) { Write-Host "OK:   ollama model $m" }
        else { Fail "ollama model $m missing -- run: ollama pull $m" }
    }
    # rerank engine (llama-server --reranking, R1 D3): WARN only -- only the corpus
    # rerank class needs it, and it is started/stopped around retrieval.
    try {
        Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8778/models' -TimeoutSec 3 | Out-Null
        Write-Host "OK:   llama-rerank engine up on 127.0.0.1:8778"
    } catch {
        Warn "llama-rerank not reachable on 127.0.0.1:8778 -- corpus retrieval (rerank class) will refuse until llama-server is started (PREREQUISITES.md, research/06)"
    }
}

# --- 6. the first-run drive smoke -----------------------------------------------------------
if ($WithDriveSmoke) {
    if ($fail -ne 0) {
        Warn "skipping the drive smoke -- fix the FAIL lines above first"
    } else {
        Write-Host "==> drive smoke: one real gated dispatch (extraction through thomson1-chat)..."
        $ref = "smoke-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        & $harness drive --matter-ref $ref --task-class extraction --timeout 600
        if ($LASTEXITCODE -ne 0) {
            Fail "drive smoke failed (matter $ref). Known cause: opencode startup hang (~2-in-7 on some boxes) -- just re-run this script."
        } else { Write-Host "OK:   drive smoke traced a real gated dispatch (matter $ref)" }
    }
}

# --- verdict ---------------------------------------------------------------------------------
if ($fail -eq 0) {
    if ($WithDriveSmoke) {
        Write-Host "R2 install OK (Windows) INCLUDING the first-run drive smoke." -ForegroundColor Green
    } else {
        Write-Host "R2 install OK (Windows). Re-run with -WithDriveSmoke for the live dispatch proof." -ForegroundColor Green
    }
}
else { Write-Host "R2 verify FAILED (Windows): see FAIL lines above." -ForegroundColor Red }
exit $fail
