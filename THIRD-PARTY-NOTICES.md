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
| pikepdf / qpdf | MPL-2.0 / Apache-2.0; <https://github.com/pikepdf/pikepdf> |
| pyHanko | MIT; <https://github.com/MatthiasValvekens/pyHanko> |

Python, Pillow, NumPy, python-docx, openpyxl, python-pptx, PyObjC, and other
packages retain their own terms. Copies of their distributed LICENSE/NOTICE
files and a package manifest are in `licenses/dependencies/`. Ghostscript's
component notices are in `vendor/ghostscript/licenses/` in source and
`ghostscript/licenses/` in the bundled app.

The app uses dynamically bundled Python and Qt libraries. Source code,
dependency versions, upstream source locations, and rebuild instructions are
available in this repository: see `requirements-macos.lock`,
`docs/DEPENDENCY-SOURCES.md`, and `build-mac.command`. The official Ghostscript
source archive accompanies tagged releases; its checksum and download URL
are recorded in `vendor/ghostscript/NOTICE.md` and the build script.

The dog artwork is custom artwork for DocuFreedom. Drinkit and PDF24 are design
and capability references only; no affiliation or endorsement is implied.
