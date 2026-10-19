# Dependency sources and rebuild information

Exact Python package versions are recorded in `requirements-macos.lock`; package notices are preserved under `licenses/dependencies` and bundled in the app.

| Component | Source / instructions |
|---|---|
| DocuFreedom | This repository and the tag matching the release |
| Original DragShift | https://github.com/llamaboi55/DragShift — original MIT notice retained |
| PyMuPDF / MuPDF | https://github.com/pymupdf/PyMuPDF and https://git.ghostscript.com/?p=mupdf.git — AGPL sources corresponding to the pinned PyMuPDF version |
| Qt / PySide6 | https://code.qt.io/qt/ and https://code.qt.io/pyside/pyside-setup.git/ — versions in the lock file |
| Ghostscript 10.08.0 | Official source URL and SHA-256 in `vendor/ghostscript/NOTICE.md`; `scripts/build-ghostscript.sh` downloads, verifies, and builds it. The original source archive is attached to releases. |
| LibreOffice 26.8.1 | Official binary and corresponding source URLs/checksums in `vendor/libreoffice/NOTICE.md`; `scripts/prepare-libreoffice.sh` verifies and extracts the unmodified Apple Silicon application. Complete component and font notices remain in the nested application bundle. |
| pikepdf / qpdf | https://github.com/pikepdf/pikepdf and https://github.com/qpdf/qpdf |
| pyHanko | https://github.com/MatthiasValvekens/pyHanko |
| Other Python packages | Source distributions and repository links are published with the matching package/version on https://pypi.org/ |

Use `python -m pip download --no-deps --no-binary=:all: PACKAGE==VERSION` to retrieve a package's source distribution where available. Building third-party components may require their documented build dependencies.

The Ghostscript binary has no private modifications. Its included ICC profiles and CMaps come from the same verified source archive. PySide/Qt and other runtime libraries remain separate dynamic components in the application bundle. No Apple Developer ID keys or signing credentials are included.
