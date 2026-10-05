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
codesign --deep --force --options runtime \                                     # S7g-M
  --sign "$IRONFLEET_CODESIGN_ID" "$APP"                                        # S7g-M

echo "==> S7g-M: notarize + staple"                                             # S7g-M
xcrun notarytool submit "$APP.zip" --keychain-profile "$IRONFLEET_NOTARY_PROFILE" --wait   # S7g-M
xcrun stapler staple "$APP"                                                     # S7g-M

echo "==> S7g-M: DMG"                                                           # S7g-M
hdiutil create -volname IronFleet -srcfolder "$DIST" -ov -format UDZO \          # S7g-M
  "$ROOT/dist/IronFleet.dmg"                                                    # S7g-M

echo "done: $ROOT/dist/IronFleet.dmg (signed + notarized)"
