#!/bin/bash
# Install a locally built DocuFreedom bundle without changing macOS security settings.
set -euo pipefail
cd "$(dirname "$0")"
SOURCE="${1:-dist/DocuFreedom.app}"
DEST="/Applications/DocuFreedom.app"
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
    echo "DocuFreedom requires an Apple Silicon Mac." >&2; exit 1
fi
if [ ! -d "$SOURCE/Contents" ]; then
    echo "Build first with ./build-mac.command, or install the release DMG manually." >&2; exit 1
fi
codesign --verify --deep --strict "$SOURCE"
if [ -e "$DEST" ]; then
    echo "DocuFreedom is already installed. Quit it and replace it manually in Finder." >&2; exit 1
fi
if [ ! -w /Applications ]; then
    echo "Use Finder to copy the app to Applications; administrator permission may be needed." >&2; exit 1
fi
ditto "$SOURCE" "$DEST"
echo "Installed. Launch DocuFreedom from Applications or Spotlight."
