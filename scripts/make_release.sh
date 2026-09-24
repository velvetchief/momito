#!/bin/bash
# Build the distributable Momito.app: a self-contained bundle that survives
# being dragged to /Applications and having this checkout deleted.
#
#   ./scripts/make_release.sh [output-dir]     (default: dist/)
#
# macOS, Apple silicon only: the app runs MLX, which is Apple-GPU only. CI
# (release workflow) calls this on a version tag push; DMG assembly and
# publishing live there, not here.
#
# Bundle layout — every path resolves from inside the app at runtime, via the
# launcher's bundle-relative resolution (installer/launcher.c
# -DMOMITO_PACKAGED) and momito.paths (MOMITO_PACKAGED=1):
#
#   Momito.app/Contents/MacOS/Momito                      the launcher
#             /Contents/Info.plist                        version from VERSION
#             /Contents/Resources/run.py                  entry script
#             /Contents/Resources/momito/                 app source
#             /Contents/Resources/assets/                 icons, cue sounds
#             /Contents/Resources/site-packages/          pip install --target
#             /Contents/Resources/python/lib/             libpython + deps
#             /Contents/Resources/python/lib/pythonX.Y/   the stdlib
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> Checking this Mac"
if [ "$(uname -s)" != "Darwin" ]; then
  echo "error: release bundles are built on macOS." >&2
  exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "error: release bundles need Apple silicon; the app runs on MLX." >&2
  exit 1
fi
if ! command -v cc >/dev/null 2>&1; then
  echo "error: a C compiler is missing. The Xcode command line tools provide" >&2
  echo "       it: xcode-select --install" >&2
  exit 1
fi

echo "==> Reading the version"
if [ ! -f "$PROJECT_DIR/VERSION" ]; then
  echo "error: VERSION is missing from the checkout." >&2
  exit 1
fi
VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/VERSION")"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: VERSION must read like 1.2.3, got '$VERSION'." >&2
  exit 1
fi

# The Python whose runtime gets bundled. Override with PYTHON_BIN=... —
# whatever it is must be 3.11+ (same floor as install.sh).
PYTHON_BIN="${PYTHON_BIN:-python3}"
version_ok() { "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; }
if ! version_ok "$PYTHON_BIN"; then
  echo "error: $PYTHON_BIN needs Python 3.11 or later ($("$PYTHON_BIN" -V 2>&1))." >&2
  exit 1
fi

OUT_DIR="${1:-$PROJECT_DIR/dist}"
BUNDLE_ID="com.momito.Momito"
STAGE_ROOT="$(mktemp -d)"
trap 'rm -rf "$STAGE_ROOT"' EXIT
STAGE="$STAGE_ROOT/Momito.app"
CONTENTS="$STAGE/Contents"
RESOURCES="$CONTENTS/Resources"
RES_PY="$RESOURCES/python"
RES_LIB="$RES_PY/lib"
SITE_PKGS="$RESOURCES/site-packages"
mkdir -p "$CONTENTS/MacOS" "$RESOURCES"

echo "==> Stamping Info.plist ($VERSION)"
# Shared with install.sh so the mic usage string and bundle attributes stay
# in sync across both builders.
sed -e "s/@BUNDLE_ID@/$BUNDLE_ID/g" -e "s/@VERSION@/$VERSION/g" \
  "$PROJECT_DIR/installer/Info.plist.in" > "$CONTENTS/Info.plist"

echo "==> Copying app source and assets"
ditto "$PROJECT_DIR/momito" "$RESOURCES/momito"
ditto "$PROJECT_DIR/assets" "$RESOURCES/assets"
cp -p "$PROJECT_DIR/run.py" "$RESOURCES/run.py"
find "$RESOURCES" -name __pycache__ -type d -prune -exec rm -rf {} +

echo "==> Preparing the build venv"
# The venv exists for pip's sake (deps resolve against one interpreter and no
# EXTERNALLY-MANAGED marker gets in the way); sysconfig inside a venv still
# reports the base install's runtime, which is what gets bundled.
"$PYTHON_BIN" -m venv "$STAGE_ROOT/venv"
VENV_PY="$STAGE_ROOT/venv/bin/python"

# Same lookup install.sh uses: PYTHONFRAMEWORKPREFIX + LDLIBRARY point at the
# shared library the launcher dlopens.
PY_DYLIB="$("$VENV_PY" - <<'PY'
import os, sysconfig
prefix = sysconfig.get_config_var("PYTHONFRAMEWORKPREFIX")
ld = sysconfig.get_config_var("LDLIBRARY")
libdir = sysconfig.get_config_var("LIBDIR")
print(os.path.join(prefix, ld) if prefix else os.path.join(libdir, ld))
PY
)"
if [ ! -e "$PY_DYLIB" ]; then
  echo "error: this Python has no shared library, so the launcher cannot" >&2
  echo "       embed it. Looked for: $PY_DYLIB" >&2
  exit 1
fi
PY_MM="$("$VENV_PY" -c 'import sysconfig; print(sysconfig.get_python_version())')"
PY_STDLIB="$("$VENV_PY" -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')"
DYLIB_BASE="$(basename "$PY_DYLIB")"
PY_LIB_DIR="$RES_LIB/python$PY_MM"
DYNLOAD="$PY_LIB_DIR/lib-dynload"

echo "==> Bundling the Python runtime ($PY_MM)"
mkdir -p "$RES_LIB" "$PY_LIB_DIR"
cp "$PY_DYLIB" "$RES_LIB/$DYLIB_BASE"
ditto "$PY_STDLIB" "$PY_LIB_DIR"
# Nothing in the bundle builds C extensions at runtime; the stdlib's own
# site-packages and build-config dirs would only duplicate or fight the
# bundle's copies.
rm -rf "$PY_LIB_DIR/site-packages" "$PY_LIB_DIR"/config-*
find "$PY_LIB_DIR" -name __pycache__ -type d -prune -exec rm -rf {} +
if [ ! -d "$DYNLOAD" ]; then
  echo "error: no lib-dynload in the copied stdlib ($PY_STDLIB); this Python" >&2
  echo "       has an unexpected layout." >&2
  exit 1
fi

echo "==> Installing dependencies into the bundle"
"$VENV_PY" -m pip install --quiet --target "$SITE_PKGS" \
  -r "$PROJECT_DIR/requirements.txt"

# _sysconfigdata records the build machine's paths (compilers, prefixes).
# Only building C extensions ever reads them, which never happens inside the
# bundle — but the validator forbids build-machine paths, so neuter the
# well-known ones the interpreter itself ships.
find "$PY_LIB_DIR" -name '_sysconfigdata*.py' -exec sed -i '' \
  -e 's|/Users/runner|/bundled|g' -e 's|/home/|/bundled/home/|g' {} +

echo "==> Rewriting dylib references into the bundle"
# Extension modules and copied dylibs reference each other by absolute
# build-machine paths; on a Mac without those paths, imports die. Copy every
# referenced dylib into Resources/python/lib and repoint each reference at
# its bundled copy with a @loader_path-relative load command. System
# libraries stay put: every Mac has them. Loop until a pass copies nothing —
# dependencies have dependencies. Third-party wheels usually arrive
# self-contained (@loader_path already), so this mostly rides guard for the
# interpreter's own modules.
chmod -R u+w "$RESOURCES"
REWRITE_LOG="$STAGE_ROOT/rewritten.txt"
while :; do
  new_copies=0
  for f in $(find "$RES_LIB" -type f; \
             find "$DYNLOAD" "$SITE_PKGS" -type f \
               \( -name '*.so' -o -name '*.dylib' \) 2>/dev/null); do
    otool -L "$f" >/dev/null 2>&1 || continue
    for dep in $(otool -L "$f" | tail -n +2 | awk '{print $1}'); do
      case "$dep" in @*|/System/*|/usr/lib/*) continue ;; esac
      base="$(basename "$dep")"
      if [ ! -f "$RES_LIB/$base" ]; then
        cp "$dep" "$RES_LIB/$base"
        chmod u+w "$RES_LIB/$base"
        new_copies=1
      fi
      # Already-bundled dylibs sit together; everything else climbs out of
      # its directory back up to Resources, then down into python/lib.
      case "$f" in
        "$RES_LIB"/*) target="@loader_path/$base" ;;
        *)
          depth="$(printf '%s' "${f#"$RESOURCES"/}" | awk -F/ '{print NF - 1}')"
          ups=""
          i=0; while [ "$i" -lt "$depth" ]; do ups="${ups}../"; i=$((i+1)); done
          target="@loader_path/${ups}python/lib/$base"
          ;;
      esac
      install_name_tool -change "$dep" "$target" "$f"
      echo "$f" >> "$REWRITE_LOG"
    done
  done
  [ "$new_copies" -eq 0 ] && break
done
# Give every bundled dylib a bundle-relative install name, so no build
# prefix survives inside them either.
for f in "$RES_LIB"/*; do
  [ -f "$f" ] || continue
  install_name_tool -id "@loader_path/$(basename "$f")" "$f"
  echo "$f" >> "$REWRITE_LOG"
done
# Rewriting a Mach-O invalidates its linker signature; re-sign each touched
# file or Apple silicon refuses to execute it.
if [ -f "$REWRITE_LOG" ]; then
  sort -u "$REWRITE_LOG" | while IFS= read -r f; do
    codesign --force --sign - "$f"
  done
fi

echo "==> Byte-compiling"
# Compiled in place from the staged tree, so code objects carry no checkout
# paths; the bundle keeps precompiled stdlib for a fast first launch.
( cd "$RESOURCES" && "$VENV_PY" -m compileall -q momito "python/lib/python$PY_MM" )

echo "==> Compiling the launcher"
cc -O2 -o "$CONTENTS/MacOS/Momito" "$PROJECT_DIR/installer/launcher.c" \
  -framework CoreFoundation \
  -DMOMITO_PACKAGED \
  -DPYTHON_DYLIB_RELPATH="\"python/lib/$DYLIB_BASE\"" \
  -DPY_VERSION="\"$PY_MM\""

echo "==> Ad-hoc signing"
codesign --force --sign - "$STAGE"

echo "==> Validating the bundle"
"$SCRIPT_DIR/validate_bundle.sh" "$STAGE"

mkdir -p "$OUT_DIR"
rm -rf "$OUT_DIR/Momito.app"
ditto "$STAGE" "$OUT_DIR/Momito.app"
echo ""
echo "Built: $OUT_DIR/Momito.app (version $VERSION)"
