#!/usr/bin/env bash
# P0-7/D13: Linux dev-tier encrypted store + versioned backup.
# LUKS-gated store creation (fail-loud: no unencrypted privileged store is ever
# created), store layout, and a versioned backup script (rsync --delete
# --link-dest snapshots + 'latest' symlink). cron/systemd-timer registration is
# deliberately NOT installed here -- see RUNBOOK_P0_7.md (Linux section).
set -euo pipefail

# --- Store root: HARNESS_HOME wins, else XDG ~/.local/share/ironfleet/harness -----------------
STORE_ROOT="${HARNESS_HOME:-$HOME/.local/share/ironfleet/harness}"
echo "==> store root: $STORE_ROOT"

# --- Best-effort LUKS check on the volume holding the store ------------------------------------
# Strategy: resolve the deepest mount containing STORE_ROOT (findmnt -T; if the
# path does not exist yet, walk up to the deepest existing ancestor via df).
# If that filesystem's source is a /dev/mapper/* device typed crypt in lsblk,
# the store is on LUKS. A non-empty /etc/crypttab is accepted as secondary
# evidence (e.g. the LUKS container is opened before this filesystem mounts).
# Anything else fails loud.
# Errexit note: df fails (pipefail) when $probe does not exist yet -- the normal
# first-run case -- so each lookup ends in `|| true` and an empty result just
# walks one level up instead of killing the script.
mount_point="$(findmnt -n -o TARGET -T "$STORE_ROOT" 2>/dev/null || true)"
probe="$STORE_ROOT"
while [[ -z "$mount_point" && "$probe" != "/" ]]; do
  mount_point="$(df -P "$probe" 2>/dev/null | awk 'END{if (NR==2) print $6}' || true)"
  probe="$(dirname "$probe")"
done
if [[ -z "$mount_point" ]]; then
  # Unreachable in practice (df on "/" always answers), but never leave it empty:
  # fall back to the root filesystem and let the LUKS check below decide.
  mount_point="/"
fi
echo "==> store lives on mount: $mount_point"

luks_ok=0
src_dev="$(findmnt -n -o SOURCE "$mount_point" 2>/dev/null || true)"
if [[ -n "$src_dev" && "$src_dev" == /dev/mapper/* ]]; then
  if lsblk -no TYPE "$src_dev" 2>/dev/null | grep -q '^crypt$'; then
    luks_ok=1
    echo "==> LUKS OK: $mount_point is on $src_dev (lsblk TYPE=crypt)"
  fi
fi
if [[ $luks_ok -eq 0 ]] && [[ -f /etc/crypttab ]] && grep -vE '^\s*(#|$)' /etc/crypttab | grep -q .; then
  luks_ok=1
  echo "==> LUKS OK (secondary evidence): $mount_point -> ${src_dev:-?} is not a crypt device,"
  echo "    but /etc/crypttab declares an unlocked LUKS container on this node."
fi
if [[ $luks_ok -eq 0 ]]; then
  echo "FAIL: '$mount_point' (holding '$STORE_ROOT') is not verifiably LUKS-encrypted" >&2
  echo "      (source device: ${src_dev:-unknown}; no active /dev/mapper crypt layer, /etc/crypttab absent/empty)." >&2
  echo "      An unencrypted privileged store is never created (P0-7 fail-loud)." >&2
  echo "      Remediation (any one, then re-run):" >&2
  echo "        1. Move the store onto an existing LUKS volume: export HARNESS_HOME=/path/on/luks/harness" >&2
  echo "        2. Encrypt home: back up, then follow distribution docs for LUKS full-disk or per-volume" >&2
  echo "           encryption (e.g. cryptsetup luksFormat on a data volume + /etc/crypttab + /etc/fstab)." >&2
  echo "        3. If the check is wrong for this box (unusual stacking), verify manually with" >&2
  echo "           'lsblk -f' that the store's device sits under a crypt node, and fix this script." >&2
  exit 1
fi

# --- Store layout: sessions/ trace/ backups/ ----------------------------------------------------
mkdir -p "$STORE_ROOT/sessions" "$STORE_ROOT/trace" "$STORE_ROOT/backups"
echo "==> created  $STORE_ROOT/{sessions,trace,backups}"

# --- Versioned backup job (param-less, self-locating via its own dir) ---------------------------
# Installed INSIDE the store root (dev-tier: no /usr/local/bin writes, no root needed).
# Single-quoted heredoc: nothing in the body is expanded at install time.
BACKUP_SCRIPT="$STORE_ROOT/ironfleet-backup.sh"
cat > "$BACKUP_SCRIPT" <<'EOF'
#!/usr/bin/env bash
# ironfleet-backup.sh -- P0-7/D13 versioned backup of the harness store (Linux).
# Param-less by design: cron or a systemd timer runs it nightly at 02:30
# (registration is a documented manual step -- see RUNBOOK_P0_7.md). Each run
# mirrors the store into backups/<stamp>, hard-linking unchanged files against
# backups/latest (rsync --link-dest), then repoints the 'latest' symlink.
# The backup script itself lives inside the store, so exclude it from the copy.
set -euo pipefail
STORE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_ROOT="$STORE_ROOT/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
rsync -a --delete --link-dest="$DEST_ROOT/latest" \
  --exclude='backups' \
  "$STORE_ROOT/" "$DEST_ROOT/$STAMP/"
ln -sfn "$DEST_ROOT/$STAMP" "$DEST_ROOT/latest"
EOF
chmod 700 "$BACKUP_SCRIPT"
echo "==> wrote    $BACKUP_SCRIPT"

# ---------------------------------------------------------------------------------------------
# Scheduling is NOT installed by this script (the runbook owns it). To register
# the 02:30 nightly job, pick one (full variants in RUNBOOK_P0_7.md, Linux ->
# Backup scheduling):
#
#   cron:    crontab -e
#            30 2 * * * "$HOME/.local/share/ironfleet/harness/ironfleet-backup.sh" >> "$HOME/.local/state/ironfleet-backup.log" 2>&1
#
#   systemd: user timer ~/.config/systemd/user/ironfleet-backup.{service,timer} + loginctl enable-linger
# ---------------------------------------------------------------------------------------------
echo "==> next: register the nightly job and run p07_verify_linux.sh (RUNBOOK_P0_7.md)"
echo "P0-7 setup OK (Linux): store ready at $STORE_ROOT"
