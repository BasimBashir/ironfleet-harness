#!/usr/bin/env bash
# S7g: build the macOS distribution (spec §4.3).
#
# AUTHORED, NOT RUN on Windows. The guard below is why this script cannot silently emit
# a half-built artifact from the wrong OS: PyInstaller does not cross-compile, so a
# Windows run would otherwise stage a layout whose MacOS/ binary is a placeholder note
# and present it as a build. Exit 2 = due-for-Mac, matching the acceptance driver.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "pack_macos.sh: due-for-Mac (S7g-M) — PyInstaller cannot cross-compile from $(uname -s)." >&2
  echo "  The staging tree builds on any OS; the binary does not. Run this on a Mac with" >&2
  echo "  Xcode and a Developer ID Application certificate." >&2
  exit 2
fi

# --- S7g-W boundary: everything above runs on any OS; everything below needs macOS ---
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"          # harness-core
DIST="$ROOT/dist"
PY="${PYTHON:-python3}"
LAUNCHER="$("$PY" -c "from harness.packaging.macdist import LAUNCHER_NAME; print(LAUNCHER_NAME)")"
APP="$DIST/IronFleet.app"

echo "==> staging the bundle layout (harness.packaging.macdist)"
"$PY" -c "
from pathlib import Path
from harness.packaging.macdist import stage_distribution, validate_distribution
app = stage_distribution(Path('$DIST'))
problems = validate_distribution(Path('$DIST'))
if problems:
    for p in problems:
        print('  FAIL  ' + p)
    raise SystemExit(1)
print('  staged + validated: ' + str(app))
"

echo "==> S7g-M: PyInstaller -> Contents/MacOS/$LAUNCHER"                        # S7g-M
"$PY" -m PyInstaller --noconfirm --onefile --name "$LAUNCHER" \
  "$ROOT/src/harness/ops/ironfleet_launcher.py"                                 # S7g-M
mv "$ROOT/dist/$LAUNCHER" "$APP/Contents/MacOS/$LAUNCHER"                       # S7g-M

echo "==> S7g-M: codesign (Developer ID Application required)"                   # S7g-M
if [[ -n "${IRONFLEET_CODESIGN_ID:-}" ]]; then                                  # S7g-M
  codesign --deep --force --options runtime --sign "$IRONFLEET_CODESIGN_ID" "$APP"
else
  # M11 release ruling (plan 2026-11-10): this release ships UNSIGNED; the
  # sha256 checksum next to the artifact is the integrity guarantee. Gate says
  # macOS will still flag an unsigned app — that friction is accepted and the
  # operator documents it in the fresh-OS record.
  echo "==> UNSIGNED build (IRONFLEET_CODESIGN_ID unset): Gatekeeper will flag the app; the .sha256 checksum is the integrity guarantee this release"
fi

if [[ -n "${IRONFLEET_NOTARY_PROFILE:-}" ]]; then                               # S7g-M
  echo "==> S7g-M: notarize + staple"                                           # S7g-M
  xcrun notarytool submit "$APP.zip" --keychain-profile "$IRONFLEET_NOTARY_PROFILE" --wait   # S7g-M
  xcrun stapler staple "$APP"                                                   # S7g-M
else
  echo "==> notarization skipped (IRONFLEET_NOTARY_PROFILE unset)"
fi

echo "==> S7g-M: DMG"                                                           # S7g-M
hdiutil create -volname IronFleet -srcfolder "$DIST" -ov -format UDZO \          # S7g-M
  "$ROOT/dist/IronFleet.dmg"                                                    # S7g-M

# M11 T6: the checksum travels WITH the artifact — verify before install:
#   shasum -a 256 -c IronFleet.dmg.sha256
dmg="$ROOT/dist/IronFleet.dmg"
( cd "$ROOT/dist" && shasum -a 256 "$(basename "$dmg")" > "$(basename "$dmg").sha256" )
echo "==> checksum: $(cat "$ROOT/dist/IronFleet.dmg.sha256")"

if [[ -n "${IRONFLEET_CODESIGN_ID:-}" ]]; then
  echo "done: $ROOT/dist/IronFleet.dmg (signed$( [[ -n "${IRONFLEET_NOTARY_PROFILE:-}" ]] && echo ' + notarized' ))"
else
  echo "done: $ROOT/dist/IronFleet.dmg (UNSIGNED; integrity = the .sha256 checksum above)"
fi
