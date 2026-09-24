#!/bin/bash
# Fail a finished Momito.app that would not survive leaving the build machine.
#
#   scripts/validate_bundle.sh path/to/Momito.app
#
# Two checks, from the launch spec:
# 1. No build-machine or checkout paths anywhere in the bundle — a hit means
#    the app would break on a Mac that never had this checkout.
# 2. Info.plist CFBundleShortVersionString equals the repo's VERSION file —
#    the whole point of single-sourcing the version.
#
# Exit 0 only when both pass. Needs python3 (any 3.x) for the plist read.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -f "$PROJECT_DIR/VERSION" ]; then
  echo "error: VERSION is missing from the checkout." >&2
  exit 1
fi
VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/VERSION")"

BUNDLE="${1:?usage: validate_bundle.sh path/to/Momito.app}"
if [ ! -d "$BUNDLE" ]; then
  echo "error: no bundle at $BUNDLE" >&2
  exit 1
fi

fail=0

echo "==> Scanning for build-machine paths"
# -a: code signatures and .so files are binary but greppable; -l: report the
# file, not every line inside it. /Users/runner is the CI runner home,
# /home/ any unix home, PROJECT_DIR this checkout.
if grep -r -a -l -F -e '/Users/runner' -e '/home/' -e "$PROJECT_DIR" \
    "$BUNDLE"; then
  echo "error: build-machine or checkout paths found in the bundle (above)." >&2
  fail=1
fi

echo "==> Checking bundle version against VERSION ($VERSION)"
PLIST_VERSION="$(python3 -c '
import plistlib, sys
try:
    with open(sys.argv[1], "rb") as f:
        info = plistlib.load(f)
    version = info["CFBundleShortVersionString"]
    if not isinstance(version, str):
        raise ValueError("not a string")
    print(version)
except Exception as exc:
    sys.exit(f"error: cannot read CFBundleShortVersionString from {sys.argv[1]}: {exc}")
' "$BUNDLE/Contents/Info.plist")"
if [ "$PLIST_VERSION" != "$VERSION" ]; then
  echo "error: Info.plist says $PLIST_VERSION, VERSION says $VERSION." >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "Bundle validation FAILED." >&2
else
  echo "Bundle validation passed."
fi
exit "$fail"
