#!/bin/bash
# Install Momito: set up the venv, then create Momito.app in /Applications.
# Run again any time; it rebuilds the app bundle in place.
#
#   ./install.sh            install (or reinstall)
#   ./install.sh --login    also add Momito to Login Items so it starts at boot
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$PROJECT_DIR/.venv"
BUNDLE_ID="com.momito.Momito"

echo "==> Checking this Mac"
if [ "$(uname -s)" != "Darwin" ]; then
  echo "error: Momito is macOS only." >&2
  exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "error: Momito needs Apple silicon. The speech model runs on MLX, which" >&2
  echo "       is Apple-GPU only, so an Intel Mac cannot run it." >&2
  exit 1
fi
if ! xcode-select -p >/dev/null 2>&1 || ! command -v cc >/dev/null 2>&1; then
  echo "error: the Xcode command line tools are missing. They provide the C" >&2
  echo "       compiler that builds the launcher. Install them with:" >&2
  echo "" >&2
  echo "         xcode-select --install" >&2
  echo "" >&2
  echo "       then run ./install.sh again." >&2
  exit 1
fi

echo "==> Python environment"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
# Runtime deps only. requirements-dev.txt (pytest, mypy) stays out of the venv
# that the installed app runs from: Momito holds Accessibility and Microphone,
# and test tooling has no business inside that blast radius.
"$VENV/bin/pip" install --quiet -r "$PROJECT_DIR/requirements.txt"

echo "==> Building Momito.app"
APPS_DIR="/Applications"
if [ ! -w "$APPS_DIR" ]; then
  APPS_DIR="$HOME/Applications"
  mkdir -p "$APPS_DIR"
fi
APP="$APPS_DIR/Momito.app"

# Build into a staging bundle first. macOS pins permission grants (TCC) to the
# launcher's ad-hoc code signature, so we only touch the installed app when the
# new build actually differs; otherwise existing grants would be silently
# orphaned on every reinstall (System Settings shows Momito ON, macOS ignores it).
STAGE_ROOT="$(mktemp -d)"
STAGE="$STAGE_ROOT/Momito.app"
mkdir -p "$STAGE/Contents/MacOS" "$STAGE/Contents/Resources"
cp "$PROJECT_DIR/assets/Momito.icns" "$STAGE/Contents/Resources/Momito.icns"

cat > "$STAGE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Momito</string>
  <key>CFBundleDisplayName</key><string>Momito</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>Momito</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleIconFile</key><string>Momito</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Momito records while you hold Right Option so it can transcribe your dictation locally.</string>
</dict>
</plist>
PLIST

mkdir -p "$PROJECT_DIR/logs"

# Compiled launcher (not a shell script): it embeds Python in-process so macOS
# treats the running app as Momito.app, not Python.app. See installer/launcher.c.
PY_DYLIB="$("$VENV/bin/python" - <<'PY'
import os, sysconfig
prefix = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
ld = sysconfig.get_config_var("LDLIBRARY")
libdir = sysconfig.get_config_var("LIBDIR")
print(os.path.join(prefix, ld) if prefix else os.path.join(libdir, ld))
PY
)"
if [ ! -e "$PY_DYLIB" ]; then
  echo "error: this Python has no shared library, so the launcher cannot embed it." >&2
  echo "       Looked for: $PY_DYLIB" >&2
  echo "       Some pyenv builds are static-only. The Homebrew and python.org" >&2
  echo "       builds both work: brew install python@3.14, then delete .venv and" >&2
  echo "       run ./install.sh again." >&2
  exit 1
fi
cc -O2 -o "$STAGE/Contents/MacOS/Momito" "$PROJECT_DIR/installer/launcher.c" \
  -DPYTHON_DYLIB="\"$PY_DYLIB\"" \
  -DRUN_PY="\"$PROJECT_DIR/run.py\"" \
  -DLOG_PATH="\"$PROJECT_DIR/logs/momito.log\""

codesign --force --sign - "$STAGE"

cdhash() { codesign -dvvv "$1" 2>&1 | awk -F= '/^CDHash/{print $2}'; }

NEW_HASH="$(cdhash "$STAGE")"
OLD_HASH=""
OLD_BUNDLE_ID=""
if [ -d "$APP" ]; then
  OLD_HASH="$(cdhash "$APP" || true)"
  OLD_BUNDLE_ID="$(defaults read "$APP/Contents/Info" CFBundleIdentifier 2>/dev/null || true)"
fi

if [ -n "$OLD_HASH" ] && [ "$OLD_HASH" = "$NEW_HASH" ]; then
  echo "    App unchanged; keeping the installed copy so permissions stay valid."
  rm -rf "$STAGE_ROOT"
else
  rm -rf "$APP"
  ditto "$STAGE" "$APP"
  rm -rf "$STAGE_ROOT"
  if [ -n "$OLD_HASH" ]; then
    # New signature orphans any old Accessibility grant; clear the dead row so
    # System Settings doesn't show an ON switch that macOS ignores. If the
    # installed copy carried a different bundle id, its row is keyed under that
    # id, so clear that one too or it lingers forever.
    tccutil reset Accessibility "$BUNDLE_ID" >/dev/null 2>&1 || true
    if [ -n "$OLD_BUNDLE_ID" ] && [ "$OLD_BUNDLE_ID" != "$BUNDLE_ID" ]; then
      tccutil reset Accessibility "$OLD_BUNDLE_ID" >/dev/null 2>&1 || true
      echo "    Bundle id changed ($OLD_BUNDLE_ID -> $BUNDLE_ID)."
    fi
    echo "    App changed: the old Accessibility grant no longer applies and was cleared."
    echo "    Re-enable Momito in System Settings > Privacy & Security > Accessibility."
  fi
fi

if [ "${1:-}" = "--login" ]; then
  echo "==> Adding Momito to Login Items"
  osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$APP\", hidden:false}" >/dev/null
fi

echo ""
echo "Installed: $APP"
echo ""
echo "First launch checklist:"
echo "  1. Open Momito from $APPS_DIR. The schnauzer appears in the menu bar,"
echo "     wearing a ⏳ for the minute or two the speech model takes to load."
echo "     First launch also downloads the model: about 2.3 GB, once."
echo "  2. macOS will ask for Microphone access on your first dictation. Allow it."
echo "  3. Grant Accessibility: System Settings > Privacy & Security >"
echo "     Accessibility > enable Momito. Needed for the hotkey and the paste."
echo ""
echo "Note: Momito.app runs the code in this folder. If you move or delete"
echo "$PROJECT_DIR, rerun ./install.sh from the new location."
