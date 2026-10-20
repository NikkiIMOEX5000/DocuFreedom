# Third-party notices

DocuFreedom is published by **dna.apps** under GNU AGPL-3.0; see `LICENSE`.
It incorporates code from [DragShift](https://github.com/llamaboi55/DragShift).
Its original MIT copyright notice and permission text are preserved in
`licenses/DragShift-MIT.txt`. See `CREDITS.md` for our special thanks.

These notices do not replace the licenses of individual dependencies.

| Component | License / upstream |
| --- | --- |
| Qt / PySide6 | LGPLv3 / GPLv3 / commercial; <https://www.qt.io/licensing/> |
| PyMuPDF / MuPDF | AGPLv3 / commercial; <https://github.com/pymupdf/PyMuPDF> |
| Ghostscript 10.08.0 | AGPLv3 or later / commercial; <https://ghostscript.com/releases/gsdnld.html> |
| LibreOffice 26.8.1 | MPL-2.0 and bundled component licenses; <https://www.libreoffice.org/licenses/> |
| pikepdf / qpdf | MPL-2.0 / Apache-2.0; <https://github.com/pikepdf/pikepdf> |
| pyHanko | MIT; <https://github.com/MatthiasValvekens/pyHanko> |
| PyWinRT 3.2.1 (Windows runtime and API projections) | MIT; [upstream source](https://github.com/pywinrt/pywinrt/tree/v3.2.1), [runtime package](https://pypi.org/project/winrt-runtime/3.2.1/) |

Python, Pillow, NumPy, python-docx, openpyxl, python-pptx, PyObjC, and other
packages retain their own terms. Copies of their distributed LICENSE/NOTICE
files and a package manifest are in `licenses/dependencies/`. Ghostscript's
component notices are in `vendor/ghostscript/licenses/` in source and
`ghostscript/licenses/` in the bundled app.

The app uses dynamically bundled Python and Qt libraries. Source code,
dependency versions, upstream source locations, and rebuild instructions are
available in this repository: see `requirements-macos.lock`,
`requirements-windows.lock`, `docs/DEPENDENCY-SOURCES.md`, `build-mac.command`,
and `build-windows.ps1`. The official Ghostscript
source archive accompanies tagged releases; its checksum and download URL
are recorded in `vendor/ghostscript/NOTICE.md` and the build script.

The separate LibreOffice application bundle retains its original component
and font notices. Its exact binary checksum, corresponding source archive
URLs and source checksums are recorded in `vendor/libreoffice/NOTICE.md` in
this repository and `libreoffice/NOTICE.md` in the installed app. The source
archives are freely downloadable from The Document Foundation. No LibreOffice
source modifications are made by DocuFreedom.

Windows packages keep LibreOffice and Ghostscript as separate local runtimes
under the application's `_internal` directory. Their exact binary checksums,
source locations, and component notices are described in
[Windows runtime notices](scripts/windows-runtime-notices.md), also included
as `WINDOWS-RUNTIME-NOTICES.md` in Windows distributions. PyWinRT is used to
call the local Windows OCR API on demand. Microsoft Windows, its OCR language
packs, scanner drivers, and Microsoft Print to PDF are operating-system
components and are not redistributed by DocuFreedom.

The dog artwork is custom artwork for DocuFreedom. Drinkit and PDF24 are design
and capability references only; no affiliation or endorsement is implied.
