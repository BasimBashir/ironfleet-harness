#!/usr/bin/env bash
# IronFleet harness -- the one Linux install script (M11 T5; twin of
# install_windows.ps1, spec 13 s2.1 / spec 15 s2.1). Idempotent: every step
# verifies before it acts. Run from the extracted zip root (it self-locates by
# walking up to pyproject.toml) or a checkout:
#
#   bash install_linux.sh
#   bash install_linux.sh --skip-store-setup     # dev rigs
#
# The privileged store is delegated to p07_setup_linux.sh (LUKS fail-loud -- an
# unencrypted privileged store is never created; re-running re-verifies an
# existing store too). The opencode pin is ENFORCED (re-read after install,
# drift never exits 0). Network is required for pip/npm at install.
# PREREQUISITES.md inventories every third-party prerequisite.
set -euo pipefail

# --- self-locate the distribution root -------------------------------------------------
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

fail() { echo "FAIL: $*" >&2; exit 1; }

# --- 0. third-party prerequisites on PATH ----------------------------------------------
for tool in git node npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    fail "$tool not found on PATH -- install it (PREREQUISITES.md lists every third-party tool), reopen this window, re-run"
  fi
  echo "==> $tool: $("$tool" --version 2>/dev/null | head -1)"
done

# --- 1. Python >= 3.12 + venv ----------------------------------------------------------
if [[ -x "$root/.venv/bin/python" ]]; then
  py="$root/.venv/bin/python"
else
  py=""
  for candidate in python3 python3.13 python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then
      v="$("$candidate" --version 2>&1 || true)"
      if echo "$v" | grep -qE 'Python 3\.(1[2-9]|[2-9][0-9])'; then
        "$candidate" -m venv "$root/.venv"
        py="$root/.venv/bin/python"
        break
      fi
    fi
  done
  [[ -n "$py" ]] || fail "no CPython >= 3.12 found (install python.org/uv Python 3.12+ or the distro python3)"
fi
echo "==> python: $py"

# --- 2. editable install (the product tree IS the repo tree) ---------------------------
"$py" -m pip install -q -e "$root"
echo "==> harness installed (editable)"

# --- 3. opencode pin (single source: harness.packaging.macdist.PINS) -------------------
pin="$("$py" -c "from harness.packaging.macdist import PINS; print(PINS['opencode'])")"
[[ -n "$pin" ]] || fail "cannot read the opencode pin from macdist.PINS"
pin_version="${pin#opencode-ai@}"
have="$(opencode --version 2>/dev/null || true)"
if [[ -z "$have" || "$have" != *"$pin_version"* ]]; then
  echo "==> installing opencode pin (${have:-none} -> $pin_version)"
  npm install -g "$pin"
else
  echo "==> opencode already pinned: $have"
fi
# the pin is ENFORCED: whatever the branch above did, re-read and fail on drift
now="$(opencode --version 2>/dev/null || true)"
if [[ -z "$now" || "$now" != *"$pin_version"* ]]; then
  fail "opencode pin NOT enforced: installed '${now:-none}' != pinned '$pin_version'. npm install -g $pin silently failed? PATH stale? Reopen this window and re-run."
fi
echo "==> opencode pin enforced: $now"

# --- 4. global autoupdate:false (S7c ruling 2026-10-12) --------------------------------
oc_cfg="${OPENCODE_CONFIG:-$HOME/.config/opencode/opencode.jsonc}"
mkdir -p "$(dirname "$oc_cfg")"
if [[ ! -f "$oc_cfg" ]]; then
  cat > "$oc_cfg" <<'EOF'
{
  "$schema": "https://opencode.ai/config.json",
  // IronFleet S7c ruling (2026-10-12): the binary is part of the harness -- the mount's
  // guard hooks are version-sensitive and re-verified per upgrade, so the GLOBAL config
  // pins it. The mount-level setting only ever protected mount workspaces.
  "autoupdate": false
}
EOF
  echo "==> wrote global $oc_cfg (autoupdate: false)"
elif ! grep -Eq '"autoupdate"[[:space:]]*:[[:space:]]*false' "$oc_cfg"; then
  fail "$oc_cfg exists without autoupdate:false -- the mount's guard hooks are version-sensitive (S7c ruling). Set it or remove the file and re-run."
else
  echo "==> global autoupdate:false verified"
fi

# --- 5. the privileged store (LUKS fail-loud, delegated to p07_setup_linux.sh) ---------
store_root="${HARNESS_HOME:-$HOME/.local/share/ironfleet/harness}"
if [[ "${SKIP_STORE_SETUP:-0}" == "1" ]]; then
  echo "==> store setup skipped (SKIP_STORE_SETUP=1); expected at $store_root"
else
  bash "$root/src/harness/ops/p07_setup_linux.sh"
fi

# --- 6. proof ----------------------------------------------------------------------------
"$root/.venv/bin/harness" --version
echo
echo "NEXT: every third-party tool and model a fresh box needs is listed in PREREQUISITES.md."
echo "Start Ollama with the models, then verify the install and smoke one live drive:"
echo "    ollama serve   (models: thomson1-chat, qwen3.8:27b, bge-m3)"
echo "    bash verify_linux_install.sh --with-drive-smoke"
echo "    .venv/bin/harness drive --matter-ref <uuid>   (a real matter)"
echo "    .venv/bin/harness serve   (the egress proxy, 127.0.0.1:7373)"
