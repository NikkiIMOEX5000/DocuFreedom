# DocuFreedom Windows runtime notices

These unmodified official engines run as separate local processes only when
needed. No system-wide Office suite, printer driver or service is installed by
DocuFreedom. Original licenses, notices, fonts, dictionaries and resources are
retained in each runtime directory. No endorsement by their authors is implied.

## LibreOffice 26.8.1.1

- Official Windows x64 binary: https://download.documentfoundation.org/libreoffice/stable/26.8.1/win/x86_64/LibreOffice_26.8.1_Win_x86-64.msi
- SHA-256: `c6298b10cfa1748bcbedad94c62ce771e240e5021bfd6d7a967cd571b04b5312`
- Official checksum: https://download.documentfoundation.org/libreoffice/stable/26.8.1/win/x86_64/LibreOffice_26.8.1_Win_x86-64.msi.sha256
- Corresponding source: https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-26.8.1.1.tar.xz
- Source SHA-256: `296ba78e7ab0d381b94c3d6342f4ebb2320ee5097ca58781b9b744cab90b9785`
- Dictionaries: https://download.documentfoundation.org/libreoffice/src/26.8.1/libreoffice-dictionaries-26.8.1.1.tar.xz
- Dictionary SHA-256: `ce366c50178f5bdf6df1c6df4a0146899cf27a0017734190d00d90f0c5acac61`
- Additional sources: https://download.documentfoundation.org/libreoffice/src/26.8.1/
- Build instructions: https://wiki.documentfoundation.org/Development/BuildingOnWindows
- License: MPL-2.0 and component-specific licenses, retained in the runtime.

LibreOffice is a registered trademark of The Document Foundation. The MSI is
administratively extracted during the build; the runtime is copied unchanged
after PyInstaller packaging. DocuFreedom makes no LibreOffice source changes.

## Ghostscript 10.08.0

- Official binary: https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/gs10080w64.exe
- SHA-256: `52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50`
- Corresponding source: https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/ghostscript-10.08.0.tar.xz
- Source SHA-256: `c20492bc8ebb96c87fa2e52a0926e1cda8cde95d66145e018ac713fed5da38cf`
- License: GNU AGPL-3.0-or-later and component licenses retained in the runtime.
- Source archive is also distributed alongside DocuFreedom release downloads.
- Build documentation: https://ghostscript.readthedocs.io/en/gs10.08.0/Make.html

The original installer runs only on the build machine to populate the vendor
directory. End-user installations simply copy the extracted runtime. No
Ghostscript source changes are made. Generic RGB/CMYK ICC profiles accompany
the engine; professional print jobs should use the receiving printer's profile.

## Windows OCR

PyWinRT 3.2.1 (MIT) projects the Windows Media.Ocr API. OCR executes locally using
Windows language packs and creates no resident background process. The required
recognition language must be installed in Windows settings. Microsoft Windows
and its OCR language packs are not redistributed with DocuFreedom.
