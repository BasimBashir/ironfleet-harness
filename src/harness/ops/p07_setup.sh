#!/usr/bin/env bash
# P0-7: encrypted APFS volume for privileged stores + versioned encrypted backup.
# Run on each Mac Mini. Idempotent-ish; check output before re-running.
set -euo pipefail
VOL_NAME="IronFleetPriv"
MOUNT="/Volumes/$VOL_NAME"
STORE_SIZES="256g"                       # resizable later

if ! diskutil info "$MOUNT" &>/dev/null; then
  echo "==> creating encrypted APFS volume $VOL_NAME (prompt: passphrase)"
  diskutil apfs addVolume disk3 APFS "$VOL_NAME" -encryption AES-256 -passphrasePrompt || \
    { echo "adjust 'disk3' to the container identifier: diskutil list"; exit 1; }
else
  echo "==> $MOUNT already present"
fi

# Privileged store layout
mkdir -p "$MOUNT/harness/sessions" "$MOUNT/harness/trace" "$MOUNT/backups"

# Time Machine must never see the privileged volume (architecture doc §2)
tmutil addexclusion "$MOUNT" && echo "==> Time Machine exclusion set"

# Versioned encrypted backup job (rsync with hard-link snapshots, nightly via launchd)
cat > /usr/local/bin/ironfleet-backup.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
SRC="/Volumes/IronFleetPriv/harness"
DEST_ROOT="/Volumes/IronFleetPriv/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
rsync -a --delete --link-dest="$DEST_ROOT/latest" "$SRC/" "$DEST_ROOT/$STAMP/"
ln -sfn "$DEST_ROOT/$STAMP" "$DEST_ROOT/latest"
EOF
chmod +x /usr/local/bin/ironfleet-backup.sh
echo "==> install the nightly launchd job: see RUNBOOK_P0_7.md §schedule"
