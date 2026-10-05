#!/usr/bin/env bash
# S7g: install-time verification, companion to p07_verify_macos.sh (spec §4.4).
#
# Runs AFTER the installer lays down the app and bootstraps the pinned opencode.
# Fails loudly if any guarantee is missing. The pin and the volume name are read from
# the Python modules rather than restated, so the script cannot drift from the code.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${IRONFLEET_ROOT:-$(cd "$HERE/../.." && pwd)}"     # harness-core
PY="${PYTHON:-python3}"
EGRESS_URL="${EGRESS_URL:-http://127.0.0.1:7373/v1/models}"   # stand_up_opencode.py:30
fail=0

# 1. the bootstrapped opencode matches the pin (PINS is the single source of truth)
PIN="$("$PY" -c "from harness.packaging.macdist import PINS; print(PINS['opencode'])")"
INSTALLED="$(opencode --version 2>/dev/null || true)"
if [[ -z "$INSTALLED" ]]; then
  echo "FAIL: opencode not on PATH — bootstrap the pinned $PIN"; fail=1
elif [[ "$INSTALLED" != *"${PIN#*@}"* ]]; then
  echo "FAIL: opencode drift — installed '$INSTALLED' != pinned '$PIN'"; fail=1
fi

# 2. autoupdate is off in the GLOBAL config. S7c decision (b): the mount's own setting
#    does not protect mount workspaces, so the global file is where the pin is defended.
CFG="${OPENCODE_CONFIG:-$HOME/.config/opencode/opencode.jsonc}"
if ! grep -Eq '"autoupdate"[[:space:]]*:[[:space:]]*false' "$CFG" 2>/dev/null; then
  echo "FAIL: autoupdate:false missing from the global config $CFG"; fail=1
fi

# 3. the egress-proxy launchd agent is loaded (KeepAlive means it should also be alive)
if ! launchctl list 2>/dev/null | grep -q 'ai.ironfleet.egress-proxy'; then
  echo "FAIL: launchd agent ai.ironfleet.egress-proxy not loaded"; fail=1
fi

# 4. the proxy is reachable — it is the only path opencode has to the gate
if ! curl -sf "$EGRESS_URL" >/dev/null 2>&1; then
  echo "FAIL: egress proxy not reachable at $EGRESS_URL"; fail=1
fi

# 5. the store resolves onto the encrypted volume. The SOURCE string says which; a
#    library-fallback means the store is off IronFleetPriv and the operator must decide
#    (CR-7 discipline: state the downgrade, don't hide it).
SRC="$("$PY" -c "from harness.paths import resolve_store_root; print(resolve_store_root()[1])")"
if [[ "$SRC" == "library-fallback" ]]; then
  echo "FAIL: store is off the encrypted volume (source=$SRC) — run p07_setup_macos.sh"; fail=1
fi
echo "store source: $SRC"

if [[ $fail -eq 0 ]]; then
  echo "S7g install OK: opencode pinned to $PIN, autoupdate off, agent loaded, proxy up, store on $SRC"
fi
exit $fail
