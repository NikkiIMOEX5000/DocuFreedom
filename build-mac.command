#!/bin/bash
# Reproducible build of local sources; never runs the upstream binary installer.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements-macos.lock
fi

if [ ! -x vendor/ghostscript/bin/gs ]; then
    ./scripts/build-ghostscript.sh
fi

QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
QT_QPA_PLATFORM=offscreen .venv/bin/python run.py --selftest

# Generate a standards-compliant icon container from the original artwork.
mkdir -p build/DragShift.iconset
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" dragshift/assets/dragshift.png --out "build/DragShift.iconset/icon_${size}x${size}.png" >/dev/null
    doubled=$((size * 2))
    sips -z "$doubled" "$doubled" dragshift/assets/dragshift.png --out "build/DragShift.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns build/DragShift.iconset -o dragshift/assets/dragshift.icns

.venv/bin/pyinstaller DragShift.spec --noconfirm
codesign --force --deep --sign - dist/DocuFreedom.app
codesign --verify --deep --strict dist/DocuFreedom.app
QT_QPA_PLATFORM=offscreen dist/DocuFreedom.app/Contents/MacOS/DocuFreedom --selftest

stage=$(mktemp -d "${TMPDIR:-/tmp}/dragshift-dmg.XXXXXX")
trap 'rm -rf "$stage"' EXIT
ditto dist/DocuFreedom.app "$stage/DocuFreedom.app"
ln -s /Applications "$stage/Applications"
cp INSTALL-MAC.txt "$stage/Начните здесь.txt"
hdiutil create -volname "DocuFreedom" -srcfolder "$stage" -ov -format UDZO "dist/DocuFreedom-4.0.0-mac-$(uname -m).dmg"
(cd dist && shasum -a 256 DocuFreedom-4.0.0-mac-$(uname -m).dmg > SHA256SUMS.txt)
echo "Готово: dist/DocuFreedom.app и установочный DMG."
