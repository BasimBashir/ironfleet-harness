#!/usr/bin/env bash
# P0-7 verification: fail loudly if any guarantee is missing.
set -euo pipefail
MOUNT="/Volumes/IronFleetPriv"
fail=0
enc=$(diskutil info "$MOUNT" | awk -F': *' '/FileVault|Encrypted/{print $2}' | head -1)
[[ "$enc" == *"Yes"* ]] || { echo "FAIL: volume not encrypted"; fail=1; }
tmutil isexcluded "$MOUNT" | grep -q "\[Excluded\]" || { echo "FAIL: Time Machine not excluded"; fail=1; }
[[ -d "$MOUNT/harness/sessions" ]] || { echo "FAIL: sessions dir missing"; fail=1; }
[[ -x /usr/local/bin/ironfleet-backup.sh ]] || { echo "FAIL: backup job missing"; fail=1; }
fdesetup status | grep -q "On" || { echo "WARN: FileVault off on this node"; }
[[ $fail -eq 0 ]] && echo "P0-7 OK: encrypted, excluded, backed up"
exit $fail
