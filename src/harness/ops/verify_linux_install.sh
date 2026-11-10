#!/usr/bin/env bash
# IronFleet harness -- first-run verify + drive smoke (M11 T5; Linux twin of
# verify_windows_install.ps1, in the family of verify_macos_install.sh). Run
# AFTER install_linux.sh, once Ollama is up. Every value is read from the code
# (PINS, resolve_store_root) so the script cannot drift from it. Every check
# runs; failures accumulate; exit 0 only when all pass.
#
#   bash verify_linux_install.sh
#   bash verify_linux_install.sh --with-drive-smoke
#
# --with-drive-smoke runs ONE real gated dispatch (harness drive, extraction
# class) -- the end-to-end proof the install can serve a matter. ~2-in-7
# opencode startup hangs are known on some boxes; this script does not retry,
# just re-run it.
set -uo pipefail   # no -e: every check runs; failures accumulate in $fail

# --- self-locate the distribution root (same walk as the installer) --------------------
dir="$(cd "$(dirname "$0")" && pwd)"
root=""
for _ in 1 2 3 4 5 6; do
  if [[ -f "$dir/pyproject.toml" ]]; then root="$dir"; break; fi
  dir="$(dirname "$dir")"
  [[ "$dir" == "/" ]] && break
done
if [[ -z "$root" ]]; then
  echo "FAIL: cannot find pyproject.toml above $0" >&2; exit 1
fi
echo "==> distribution root: $root"
py="$root/.venv/bin/python"
harness="$root/.venv/bin/harness"
fail=0
fail_() { echo "FAIL: $*" >&2; fail=1; }
warn() { echo "WARN: $*"; }

# --- 1. venv + the CLI runs --------------------------------------------------------------
if [[ ! -x "$py" ]]; then
  fail_ "no venv at $root/.venv -- run install_linux.sh first"
else
  ver="$("$harness" --version 2>/dev/null || true)"
  if [[ -z "$ver" ]]; then fail_ "harness --version failed under the venv"
  else echo "OK:   $ver"; fi
fi

# --- 2. opencode on PATH and matching the pin (PINS is the single source) ----------------
if [[ -x "$py" ]]; then
  pin="$("$py" -c "from harness.packaging.macdist import PINS; print(PINS['opencode'])" 2>/dev/null || true)"
  if [[ -z "$pin" ]]; then
    fail_ "cannot read the opencode pin from macdist.PINS"
  else
    pin_version="${pin#opencode-ai@}"
    have="$(opencode --version 2>/dev/null || true)"
    if [[ -z "$have" ]]; then
      fail_ "opencode not on PATH -- bootstrap the pinned $pin (npm install -g $pin)"
    elif [[ "$have" != *"$pin_version"* ]]; then
      fail_ "opencode drift: installed '$have' != pinned '$pin' -- the mount's guard hooks are version-sensitive (S7c ruling). Re-run install_linux.sh to restore the pin."
    else
      echo "OK:   opencode pinned: $have"
    fi
  fi

  # --- 3. autoupdate is off in the GLOBAL config (S7c ruling) ----------------------------
  oc_cfg="${OPENCODE_CONFIG:-$HOME/.config/opencode/opencode.jsonc}"
  if ! grep -Eq '"autoupdate"[[:space:]]*:[[:space:]]*false' "$oc_cfg" 2>/dev/null; then
    fail_ "autoupdate:false missing from $oc_cfg -- an auto-updated binary breaks the guard-hook pin (S7c ruling)"
  else
    echo "OK:   global autoupdate:false"
  fi

  # --- 4. the store resolves (never the library fallback) + deep P0-7 checks -------------
  src="$("$py" -c "from harness.paths import resolve_store_root; print(resolve_store_root()[1])" 2>/dev/null || true)"
  if [[ -z "$src" ]]; then
    fail_ "resolve_store_root() failed"
  elif [[ "$src" == "library-fallback" ]]; then
    fail_ "store is off the encrypted volume (source=library-fallback) -- run p07_setup_linux.sh or set HARNESS_HOME"
  else
    echo "OK:   store source: $src"
  fi
  bash "$root/src/harness/ops/p07_verify_linux.sh" || fail_ "P0-7 store verification failed (see its FAIL lines above)"
fi

# --- 5. Ollama reachable + the three bootstrap models present ----------------------------
OLLAMA="${OLLAMA_URL:-http://127.0.0.1:11434}"
required=(thomson1-chat:latest qwen3.8:27b bge-m3:567m)
tags_json="$(curl -sf --max-time 5 "$OLLAMA/api/tags" || true)"
if [[ -z "$tags_json" ]]; then
  fail_ "Ollama not reachable at $OLLAMA -- start it ('ollama serve') and re-run"
else
  tags_json_names="$("$py" -c 'import json,sys
for x in json.load(sys.stdin)["models"]: print(x["name"])' <<<"$tags_json")"
  for r in "${required[@]}"; do
    if grep -qxF "$r" <<<"$tags_json_names"; then
      echo "OK:   ollama model $r"
    else
      fail_ "ollama model $r missing -- run: ollama pull $r"
    fi
  done
  # rerank engine (llama-server --reranking, R1 D3): WARN only -- only the corpus
  # rerank class needs it, and it is started/stopped around retrieval.
  if curl -sf --max-time 3 "http://127.0.0.1:8778/models" >/dev/null 2>&1; then
    echo "OK:   llama-rerank engine up on 127.0.0.1:8778"
  else
    warn "llama-rerank not reachable on 127.0.0.1:8778 -- corpus retrieval (rerank class) will refuse until llama-server is started (PREREQUISITES.md, research/06)"
  fi
fi

# --- 6. the first-run drive smoke ----------------------------------------------------------
with_smoke=0
[[ "${1:-}" == "--with-drive-smoke" ]] && with_smoke=1
if [[ $with_smoke -eq 1 ]]; then
  if [[ $fail -ne 0 ]]; then
    warn "skipping the drive smoke -- fix the FAIL lines above first"
  else
    echo "==> drive smoke: one real gated dispatch (extraction through thomson1-chat)..."
    ref="smoke-$(date +%Y%m%d-%H%M%S)"
    if ! "$harness" drive --matter-ref "$ref" --task-class extraction --timeout 600; then
      fail_ "drive smoke failed (matter $ref). Known cause: opencode startup hang (~2-in-7 on some boxes) -- just re-run this script."
    else
      echo "OK:   drive smoke traced a real gated dispatch (matter $ref)"
    fi
  fi
fi

# --- verdict ---------------------------------------------------------------------------------
if [[ $fail -eq 0 ]]; then
  if [[ $with_smoke -eq 1 ]]; then
    echo "install OK (Linux) INCLUDING the first-run drive smoke."
  else
    echo "install OK (Linux). Re-run with --with-drive-smoke for the live dispatch proof."
  fi
else
  echo "verify FAILED (Linux): see FAIL lines above." >&2
fi
exit "$fail"
