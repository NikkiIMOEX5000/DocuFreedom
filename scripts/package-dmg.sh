#!/bin/bash
# Package an already-built app. Retry only hdiutil's transient Resource busy error.
set -euo pipefail
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
APP_PATH=${1:-"$PROJECT_DIR/dist/DocuFreedom.app"}
VERSION=$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$PROJECT_DIR/dragshift/__init__.py")
OUTPUT_PATH=${2:-"$PROJECT_DIR/dist/DocuFreedom-$VERSION-mac-$(uname -m).dmg"}
if [ ! -d "$APP_PATH" ]; then
    echo "App bundle not found: $APP_PATH" >&2
    exit 1
fi
mkdir -p "$(dirname -- "$OUTPUT_PATH")"
STDERR_LOG="${OUTPUT_PATH%.dmg}.hdiutil.log"
stage=$(mktemp -d "${TMPDIR:-/tmp}/docufreedom-dmg.XXXXXX")
trap 'rm -rf "$stage"' EXIT
ditto "$APP_PATH" "$stage/DocuFreedom.app"
ln -s /Applications "$stage/Applications"
cp "$PROJECT_DIR/INSTALL-MAC.txt" "$stage/Начните здесь.txt"
# Keep diagnostics outside the image's staging folder.
attempt_log="$stage.hdiutil-stderr"
trap 'rm -rf "$stage"; rm -f "$attempt_log"' EXIT
: > "$STDERR_LOG"
attempt=1
while :; do
    printf 'hdiutil create attempt %s/3\n' "$attempt" >> "$STDERR_LOG"
    if LC_ALL=C hdiutil create -volname "DocuFreedom" -srcfolder "$stage" -ov -format UDZO "$OUTPUT_PATH" 2> "$attempt_log"; then
        cat "$attempt_log" >> "$STDERR_LOG"
        cat "$attempt_log" >&2
        break
    else
        status=$?
        cat "$attempt_log" >> "$STDERR_LOG"
        cat "$attempt_log" >&2
        if [ "$attempt" -ge 3 ] || ! grep -Eq '^hdiutil: create failed - Resource busy[[:space:]]*$' "$attempt_log"; then
            echo "DMG creation failed; diagnostics: $STDERR_LOG" >&2
            exit "$status"
        fi
        delay=2
        if [ "$attempt" -eq 2 ]; then delay=5; fi
        printf 'hdiutil Resource busy; retrying in %s seconds (%s/3).\n' "$delay" "$attempt" >&2
        sleep "$delay"
        attempt=$((attempt + 1))
    fi
done
echo "Created: $OUTPUT_PATH"
