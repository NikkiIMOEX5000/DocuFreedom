#!/bin/bash
# Reproducible build of local sources; never runs the upstream binary installer.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements-macos.lock
fi

if [ ! -x vendor/ghostscript/bin/gs ]; then
    ./scripts/build-ghostscript.sh
fi
./scripts/prepare-libreoffice.sh
VERSION=$(.venv/bin/python -c 'from dragshift import __version__; print(__version__)')

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
mkdir -p dist/DocuFreedom.app/Contents/Resources/libreoffice
ditto vendor/libreoffice/LibreOffice.app dist/DocuFreedom.app/Contents/Resources/libreoffice/LibreOffice.app
cp vendor/libreoffice/NOTICE.md dist/DocuFreedom.app/Contents/Resources/libreoffice/NOTICE.md
# PyInstaller signs its native libraries. Keep the official nested LibreOffice
# signature intact, then seal the containing app and verify all nested code.
codesign --force --sign - dist/DocuFreedom.app
codesign --verify --deep --strict dist/DocuFreedom.app
QT_QPA_PLATFORM=offscreen dist/DocuFreedom.app/Contents/MacOS/DocuFreedom --selftest
codesign --verify --deep --strict dist/DocuFreedom.app

./scripts/package-dmg.sh dist/DocuFreedom.app "dist/DocuFreedom-$VERSION-mac-$(uname -m).dmg"
(cd dist && shasum -a 256 "DocuFreedom-$VERSION-mac-$(uname -m).dmg" > SHA256SUMS.txt)
echo "Готово: dist/DocuFreedom.app и установочный DMG."
