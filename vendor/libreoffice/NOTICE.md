# LibreOffice runtime

DocuFreedom includes the unmodified official LibreOffice 26.8.1 Apple Silicon
application as a separate local document rendering process. LibreOffice is a
registered trademark of The Document Foundation; no endorsement is implied.

- Binary: https://download.documentfoundation.org/libreoffice/stable/26.8.1/mac/aarch64/LibreOffice_26.8.1_MacOS_aarch64.dmg
- SHA-256: `ca074e0b13571efb30a31fc531c5f95e997030637325e5d5de92d67aefdf0dfc`
- Official checksum: https://download.documentfoundation.org/libreoffice/stable/26.8.1/mac/aarch64/LibreOffice_26.8.1_MacOS_aarch64.dmg.sha256
- Corresponding source: https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz
- Source SHA-256: `296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785`
- Dictionary source: https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-dictionaries-26.8.1.1.tar.xz
- Dictionary SHA-256: `ce366c50178f5bdf6df1c6df4a0146899cf27a0017734190d00d90f0c5acac61`
- Additional source packages: https://download.documentfoundation.org/libreoffice/src/26.8.1/
- Build instructions: https://wiki.documentfoundation.org/Development/BuildingOnMac

LibreOffice is distributed under MPL-2.0 and contains components under other
open source licenses. The complete original LICENSE, NOTICE, font licenses and
other component notices remain inside `LibreOffice.app/Contents/Resources/`.
See https://www.libreoffice.org/licenses/ for additional licensing information.
The runtime is copied intact after PyInstaller packaging; its libraries are
not merged with or rewritten by PyInstaller. No LibreOffice source changes are
made by DocuFreedom. `scripts/prepare-libreoffice.sh` downloads the pinned
archive, verifies its checksum and code signature, and extracts the bundle.

Documents are rendered on the Mac. Conversion does not upload documents to a
service. The embedded runtime needs no separately installed Office suite.
