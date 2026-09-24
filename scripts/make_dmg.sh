#!/bin/bash
# Package a built Momito.app as the release DMG and zip.
#
#   ./scripts/make_dmg.sh [path/to/Momito.app]     (default: dist/Momito.app)
#
# Writes Momito-v<version>.dmg and Momito-v<version>.zip next to the bundle.
# macOS only (hdiutil, sips, ditto); the release workflow calls it after
# scripts/make_release.sh. Publishing lives in the workflow, not here.
#
# Branding is derived from assets/, per the launch spec: the volume icon is
# the app's icns, and the background is icon-1024.png resized and padded in
# the landing page's --bg color. One honest limitation: positioning icons on
# the background needs a Finder session, which CI doesn't have — the branding
# ships inside the image, and Finder lays items out on its default grid.
# Cosmetic only; drag-to-Applications works regardless.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "error: the DMG is assembled with hdiutil — macOS only." >&2
  exit 1
fi

BUNDLE="${1:-$PROJECT_DIR/dist/Momito.app}"
if [ ! -d "$BUNDLE" ]; then
  echo "error: no bundle at $BUNDLE — run scripts/make_release.sh first." >&2
  exit 1
fi
OUT_DIR="$(cd "$(dirname "$BUNDLE")" && pwd)"

if [ ! -f "$PROJECT_DIR/VERSION" ]; then
  echo "error: VERSION is missing from the checkout." >&2
  exit 1
fi
VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/VERSION")"

DMG="$OUT_DIR/Momito-v$VERSION.dmg"
ZIP="$OUT_DIR/Momito-v$VERSION.zip"
ICONS="$PROJECT_DIR/assets"

# site/index.html's --bg; the DMG reads as the same product as the page.
BG_COLOR="0f1114"

STAGE_ROOT="$(mktemp -d)"
MOUNT=""
cleanup() {
  if [ -n "$MOUNT" ]; then
    hdiutil detach "$MOUNT" -force >/dev/null 2>&1 || true
  fi
  rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT

echo "==> Staging the volume ($VERSION)"
VOL="$STAGE_ROOT/volume"
mkdir -p "$VOL"
ditto "$BUNDLE" "$VOL/Momito.app"
ln -s /Applications "$VOL/Applications"
cp "$ICONS/Momito.icns" "$VOL/.VolumeIcon.icns"
mkdir -p "$VOL/.background"

echo "==> Rendering the background from assets/icon-1024.png"
BG="$STAGE_ROOT/bg.png"
sips -z 240 240 "$ICONS/icon-1024.png" --out "$BG" >/dev/null
sips --padToHeightWidth 400 660 --padColor "$BG_COLOR" "$BG" \
  --out "$VOL/.background/background.png" >/dev/null

echo "==> Building the read-write image"
RW_DMG="$STAGE_ROOT/momito-rw.dmg"
SIZE_MB="$(du -sk "$VOL" | awk '{print int($1 / 1024) + 128}')"
hdiutil create -volname "Momito $VERSION" -fs HFS+ -size "${SIZE_MB}m" \
  -srcfolder "$VOL" -format UDRW -ov "$RW_DMG"

echo "==> Stamping the volume icon"
MOUNT="$STAGE_ROOT/mnt"
mkdir -p "$MOUNT"
hdiutil attach "$RW_DMG" -mountpoint "$MOUNT" -nobrowse -noautoopen -quiet
# The custom-icon bit lives on the volume root, so it can only be set after
# attach. SetFile ships with the extra Xcode tools and is often missing on
# CI; without it Finder may show the generic volume icon — cosmetic only.
if [ -x /usr/bin/SetFile ]; then
  /usr/bin/SetFile -a C "$MOUNT"
else
  echo "    SetFile not present; skipping the custom-icon flag (cosmetic)."
fi
hdiutil detach "$MOUNT"
MOUNT=""

echo "==> Compressing"
hdiutil convert "$RW_DMG" -format UDZO -ov -o "$DMG"

echo "==> Zipping the bundle"
# ditto keeps the code signature's xattrs, which Finder's compress drops.
ditto -c -k --keepParent "$BUNDLE" "$ZIP"

echo ""
echo "Built: $DMG"
echo "Built: $ZIP"
ls -lh "$DMG" "$ZIP"
