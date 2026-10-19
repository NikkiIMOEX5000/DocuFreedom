#!/bin/sh
# Reproducible local-only build. Requires Xcode Command Line Tools, not Homebrew.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
GS_VERSION=10.08.0
GS_ARCHIVE="$PROJECT_DIR/vendor/sources/ghostscript-$GS_VERSION.tar.xz"
GS_SOURCE="$PROJECT_DIR/vendor/sources/ghostscript-$GS_VERSION"
GS_PREFIX="$PROJECT_DIR/vendor/ghostscript"
mkdir -p "$PROJECT_DIR/vendor/sources" "$GS_PREFIX/bin" "$GS_PREFIX/iccprofiles" "$GS_PREFIX/licenses"
if [ ! -f "$GS_ARCHIVE" ]; then
    curl -L --fail --show-error "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/ghostscript-$GS_VERSION.tar.xz" -o "$GS_ARCHIVE"
fi
GS_SHA=$(shasum -a 256 "$GS_ARCHIVE" | cut -d ' ' -f 1)
[ "$GS_SHA" = c20492bc8ebb96c87fa2e52a0926e1cda8cde95d66145e018ac713fed5da38cf ] || { echo 'Ghostscript checksum mismatch' >&2; exit 1; }
if [ ! -d "$GS_SOURCE" ]; then
    tar -xJf "$GS_ARCHIVE" -C "$PROJECT_DIR/vendor/sources"
fi
cd "$GS_SOURCE"
export MACOSX_DEPLOYMENT_TARGET=14.0
./configure --prefix="$GS_PREFIX" --without-x --disable-cups --disable-gtk --with-drivers=FILES --without-tesseract --disable-contrib --disable-dbus --disable-fontconfig
make clean
make -j6
cp bin/gs "$GS_PREFIX/bin/gs"
cp iccprofiles/srgb.icc iccprofiles/default_cmyk.icc "$GS_PREFIX/iccprofiles/"
cp LICENSE "$GS_PREFIX/licenses/Ghostscript-LICENSE.txt"
cp doc/COPYING "$GS_PREFIX/licenses/Ghostscript-AGPL-3.0.txt"
for GS_LICENSE in zlib/LICENSE jbig2dec/LICENSE jbig2dec/COPYING freetype/LICENSE.TXT freetype/docs/FTL.TXT freetype/docs/GPLv2.TXT libpng/LICENSE lcms2mt/COPYING openjpeg/LICENSE brotli/LICENSE extract/COPYING jpeg/README; do
    if [ -f "$GS_LICENSE" ]; then
        GS_LICENSE_NAME=$(echo "$GS_LICENSE" | tr '/' '-')
        cp "$GS_LICENSE" "$GS_PREFIX/licenses/$GS_LICENSE_NAME.txt"
    fi
done
sed -n 's/^%%Copyright: *//p' Resource/CMap/Adobe-Japan1-0 > "$GS_PREFIX/licenses/Adobe-CMap-LICENSE.txt"
"$GS_PREFIX/bin/gs" --version
