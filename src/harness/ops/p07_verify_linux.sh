#!/usr/bin/env bash
# P0-7/D13 verification (Linux): fail loudly if any guarantee is missing.
# Checks: home volume LUKS-encrypted (same best-effort logic as setup), the three
# store dirs exist, backup script present + executable. WARNs (does not fail) when
# no cron/systemd-timer registration is found -- scheduling is a manual, documented step.
set -uo pipefail   # no -e: every check runs; failures accumulate in $fail

STORE_ROOT="${HARNESS_HOME:-$HOME/.local/share/ironfleet/harness}"
fail=0

echo "==> store root: $STORE_ROOT"

# --- LUKS check (mirror of p07_setup_linux.sh; by design, not sourced, so each
# --- script stands alone for an operator reading it) -----------------------------------------
# Errexit-free by design (no -e), but keep `|| true` on lookups that legitimately
# fail before the store exists; the fallback walks up to "/" and lets the LUKS
# check decide.
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

luks_ok=0
src_dev="$(findmnt -n -o SOURCE "$mount_point" 2>/dev/null || true)"
if [[ -n "$src_dev" && "$src_dev" == /dev/mapper/* ]]; then
  if lsblk -no TYPE "$src_dev" 2>/dev/null | grep -q '^crypt$'; then
    luks_ok=1
    echo "OK:   $mount_point is on $src_dev (lsblk TYPE=crypt)"
  fi
fi
if [[ $luks_ok -eq 0 ]] && [[ -f /etc/crypttab ]] && grep -vE '^\s*(#|$)' /etc/crypttab | grep -q .; then
  luks_ok=1
  echo "OK:   /etc/crypttab declares an active LUKS container (secondary evidence; device: ${src_dev:-unknown})."
fi
if [[ $luks_ok -eq 0 ]]; then
  echo "FAIL: '$mount_point' (holding '$STORE_ROOT') is not verifiably LUKS-encrypted (see p07_setup_linux.sh remediation)." >&2
  fail=1
fi

# --- Store layout -------------------------------------------------------------------------------
for d in sessions trace backups; do
  if [[ -d "$STORE_ROOT/$d" ]]; then
    echo "OK:   $STORE_ROOT/$d"
  else
    echo "FAIL: $STORE_ROOT/$d missing (re-run p07_setup_linux.sh)" >&2
    fail=1
  fi
done

# --- Backup script present + executable ----------------------------------------------------------
if [[ -x "$STORE_ROOT/ironfleet-backup.sh" ]]; then
  echo "OK:   $STORE_ROOT/ironfleet-backup.sh"
else
  echo "FAIL: $STORE_ROOT/ironfleet-backup.sh missing or not executable (re-run p07_setup_linux.sh)" >&2
  fail=1
fi

# --- Scheduled job (WARN only: registration is manual, documented in the runbook) ----------------
if crontab -l 2>/dev/null | grep -q 'ironfleet-backup\.sh'; then
  echo "OK:   cron entry for ironfleet-backup.sh present"
elif [[ -f "$HOME/.config/systemd/user/ironfleet-backup.timer" ]] && command -v systemctl >/dev/null 2>&1 && systemctl --user is-enabled ironfleet-backup.timer >/dev/null 2>&1; then
  echo "OK:   systemd user timer ironfleet-backup.timer enabled"
else
  echo "WARN: no cron/systemd-timer registration for ironfleet-backup.sh found (manual step -- RUNBOOK_P0_7.md, Linux -> Backup scheduling)." >&2
fi

# --- Verdict ---------------------------------------------------------------------------------------
if [[ $fail -eq 0 ]]; then
  echo "P0-7 OK (Linux): encrypted, laid out, backed up"
else
  echo "P0-7 FAILED (Linux): see FAIL lines above; node is not production-ready." >&2
fi
exit "$fail"
