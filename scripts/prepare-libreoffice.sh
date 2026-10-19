#!/bin/bash
# Preserve the official app bundle; do not run a package installer or modify user Office apps.
set -euo pipefail
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=26.8.1
SHA256=ca074e0b13571efb30a31fc531c5f95e997030637325e5d5de92d67aefdf0dfc
ARCHIVE="$PROJECT_DIR/vendor/sources/LibreOffice_${VERSION}_MacOS_aarch64.dmg"
RUNTIME="$PROJECT_DIR/vendor/libreoffice/LibreOffice.app"
if [ "$(uname -m)" != arm64 ]; then
    echo 'This release bundles the Apple Silicon LibreOffice runtime; build on arm64.' >&2
    exit 1
fi
mkdir -p "$PROJECT_DIR/vendor/sources" "$PROJECT_DIR/vendor/libreoffice"
if [ ! -f "$ARCHIVE" ]; then
    curl --fail --location --show-error --retry 3 --connect-timeout 20 --max-time 900 \
        "https://download.documentfoundation.org/libreoffice/stable/$VERSION/mac/aarch64/LibreOffice_${VERSION}_MacOS_aarch64.dmg" \
        -o "$ARCHIVE.part"
    ACTUAL=$(shasum -a 256 "$ARCHIVE.part" | cut -d ' ' -f 1)
    [ "$ACTUAL" = "$SHA256" ] || { echo 'LibreOffice checksum mismatch' >&2; exit 1; }
    mv "$ARCHIVE.part" "$ARCHIVE"
fi
ACTUAL=$(shasum -a 256 "$ARCHIVE" | cut -d ' ' -f 1)
[ "$ACTUAL" = "$SHA256" ] || { echo 'LibreOffice checksum mismatch' >&2; exit 1; }
if [ ! -d "$RUNTIME" ] || [ "$(cat "$PROJECT_DIR/vendor/libreoffice/.archive-sha256" 2>/dev/null || true)" != "$SHA256" ] || ! codesign --verify --deep --strict "$RUNTIME" >/dev/null 2>&1; then
    MOUNT=$(mktemp -d "${TMPDIR:-/tmp}/docufreedom-libreoffice.XXXXXX")
    cleanup() { hdiutil detach "$MOUNT" -quiet >/dev/null 2>&1 || true; rmdir "$MOUNT" 2>/dev/null || true; }
    trap cleanup EXIT
    hdiutil attach -readonly -nobrowse -quiet -mountpoint "$MOUNT" "$ARCHIVE"
    [ -x "$MOUNT/LibreOffice.app/Contents/MacOS/soffice" ]
    codesign --verify --deep --strict "$MOUNT/LibreOffice.app"
    # Only this reproducible vendor cache is replaced; user-installed Office
    # applications are never touched. A fresh copy removes stale extra files.
    rm -rf "$RUNTIME"
    ditto "$MOUNT/LibreOffice.app" "$RUNTIME"
    printf '%s\n' "$SHA256" > "$PROJECT_DIR/vendor/libreoffice/.archive-sha256"
fi
codesign --verify --deep --strict "$RUNTIME"
PYTHONDONTWRITEBYTECODE=1 "$RUNTIME/Contents/MacOS/soffice" --headless --version
