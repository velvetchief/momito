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

# Mach-O magic, all three container formats and both byte orders: 32-bit and
# 64-bit MH_MAGIC/MH_CIGAM, plus the fat header.
_is_macho() {
  python3 - "$1" <<'PY'
import sys

try:
    with open(sys.argv[1], "rb") as f:
        magic = f.read(4)
except OSError:
    sys.exit(1)  # unreadable: never exempt
MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",  # 32-bit, both orders
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",  # 64-bit, both orders
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # fat, both orders
}
sys.exit(0 if magic in MAGICS else 1)
PY
}

# Exit 0 when no load command macOS consults at load time names a forbidden
# path. LC_RPATH values are exempt: a stale search prefix is never forced,
# only consulted for bare install names, and the packager's rewrite loop
# guarantees every active reference points inside the bundle.
_macho_load_refs_clean() {
  python3 - "$1" "${FORBIDDEN_PATTERNS[@]}" <<'PY'
import re
import subprocess
import sys

DYLIB_CMDS = {
    "LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_LAZY_LOAD_DYLIB",
    "LC_LOAD_UPWARD_DYLIB", "LC_REEXPORT_DYLIB", "LC_ID_DYLIB",
}
file = sys.argv[1]
forbidden = sys.argv[2:]

proc = subprocess.run(["otool", "-l", file], capture_output=True, text=True)
if proc.returncode != 0 or not proc.stdout.strip():
    print(f"error: otool could not read {file}", file=sys.stderr)
    sys.exit(1)
refs = []
cmd = None
for line in proc.stdout.splitlines():
    m = re.match(r"\s*cmd (LC_\w+)\s*$", line)
    if m:
        cmd = m.group(1)
        continue
    m = re.match(r"\s*name (.+?) \(offset \d+\)\s*$", line)
    if m and cmd in DYLIB_CMDS:
        refs.append((cmd, m.group(1)))
# otool -D prints "<file>:" then the install ID the loader records.
ident = subprocess.run(
    ["otool", "-D", file], capture_output=True, text=True,
).stdout.splitlines()
if len(ident) >= 2:
    refs.append(("LC_ID_DYLIB (otool -D)", ident[1].strip()))

found = False
for cmd, ref in refs:
    for pattern in forbidden:
        if pattern in ref:
            print(f"  {cmd}: {ref} — matches '{pattern}'", file=sys.stderr)
            found = True
            break
sys.exit(1 if found else 0)
PY
}

echo "==> Scanning for build-machine paths"
# /Users/runner is the CI runner home, /home/ any unix home, PROJECT_DIR this
# checkout. Text files leak a baked path the moment anything reads it, so a
# raw hit there stays a hard fail. Wheel-built Mach-O binaries legitimately
# carry stale build strings, though — the PortAudio binary in the sounddevice
# wheel was built on a GitHub Actions runner and still names /Users/runner in
# its debug strings — so a hit inside a Mach-O file is adjudicated against
# the load commands macOS actually consults at load time (otool -l plus
# otool -D): an active reference is fatal, inert metadata is noted and
# exempt. Active load references are dependence; strings are not.
FORBIDDEN_PATTERNS=('/Users/runner' '/home/' "$PROJECT_DIR")
OTOOL="$(command -v otool || true)"
# A raw byte scan, not grep: BSD grep (macOS) skips files it deems binary
# even with -a — it matched the text leaks but silently ignored the
# libportaudio.dylib fixture — while GNU grep matches. The bundle must be
# scanned identically on both platforms, and python3 is already a hard
# dependency of this script.
leaks="$(python3 - "$BUNDLE" "${FORBIDDEN_PATTERNS[@]}" <<'PY'
import os
import sys

bundle = sys.argv[1]
patterns = [pattern.encode() for pattern in sys.argv[2:]]
for root, dirs, files in os.walk(bundle):
    for name in files:
        path = os.path.join(root, name)
        try:
            with open(path, "rb") as data:
                blob = data.read()
        except OSError:
            continue
        for pattern in patterns:
            if pattern in blob:
                print(f"{path}\t{pattern.decode()}")
                break
PY
)"
TAB="$(printf '\t')"
if [ -n "$leaks" ]; then
  [ -n "$OTOOL" ] || echo "note: otool not found — Mach-O hits fall back to the raw scan" >&2
  while IFS="$TAB" read -r leak matched; do
    [ -n "$leak" ] || continue
    echo "$leak"
    if [ -n "$OTOOL" ] && _is_macho "$leak"; then
      if _macho_load_refs_clean "$leak"; then
        echo "note: inert build-path metadata in ${leak#"$BUNDLE"/} (matched ${matched}) — load commands clean, exempt" >&2
        continue
      fi
      # The offending load commands were reported in place; nothing to add.
    else
      echo "  (matched ${matched})" >&2
    fi
    echo "error: build-machine or checkout paths found in the bundle (above)." >&2
    fail=1
  done <<<"$leaks"
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
