# Dependency sources and rebuild information

Exact Python package versions are recorded in `requirements-macos.lock` and `requirements-windows.lock`; package notices are preserved under `licenses/dependencies` and bundled in the app. DocuFreedom 4.2.0 build entry points are `build-mac.command` for Apple Silicon/macOS 15+ and `build-windows.ps1` for Windows 10/11 x64.

| Component | Source / instructions |
|---|---|
| DocuFreedom | This repository and the tag matching the release |
| Original DragShift | https://github.com/llamaboi55/DragShift — original MIT notice retained |
| PyMuPDF / MuPDF | https://github.com/pymupdf/PyMuPDF and https://git.ghostscript.com/?p=mupdf.git — AGPL sources corresponding to the pinned PyMuPDF version |
| Qt / PySide6 | https://code.qt.io/qt/ and https://code.qt.io/pyside/pyside-setup.git/ — versions in the lock file |
| Ghostscript 10.08.0 | Official source URL and SHA-256 in `vendor/ghostscript/NOTICE.md`; `scripts/build-ghostscript.sh` downloads, verifies, and builds the Mac runtime. The Windows binary/source checksums are in [Windows runtime notices](../scripts/windows-runtime-notices.md). The original source archive is attached to releases. |
| LibreOffice 26.8.1 | Official Mac binary and corresponding source URLs/checksums in `vendor/libreoffice/NOTICE.md`; `scripts/prepare-libreoffice.sh` verifies and extracts the unmodified Apple Silicon application. Windows MSI/source checksums and extraction details are in [Windows runtime notices](../scripts/windows-runtime-notices.md). Complete component and font notices remain in each runtime. |
| pikepdf / qpdf | https://github.com/pikepdf/pikepdf and https://github.com/qpdf/qpdf |
| pyHanko | https://github.com/MatthiasValvekens/pyHanko |
| PyWinRT 3.2.1 | [Tagged MIT source](https://github.com/pywinrt/pywinrt/tree/v3.2.1), [runtime source distribution](https://pypi.org/project/winrt-runtime/3.2.1/); the runtime and required Windows API projection packages are pinned in `requirements-windows.lock`. |
| Other Python packages | Source distributions and repository links are published with the matching package/version on https://pypi.org/ |

Use `python -m pip download --no-deps --no-binary=:all: PACKAGE==VERSION` to retrieve a package's source distribution where available. Building third-party components may require their documented build dependencies.

The Ghostscript binaries have no private modifications. Their included ICC profiles and CMaps come from the corresponding official distribution. `scripts/prepare-windows-runtimes.ps1` verifies the Windows engine downloads before extraction; no system-wide Office suite or printer driver is installed for end users. Windows OCR uses operating-system language packs, which are not bundled.

PySide/Qt and other runtime libraries remain separate dynamic components in the application bundle or Windows `_internal` directory. No Apple Developer ID keys or Windows code-signing credentials are included. Build outputs are `DocuFreedom-4.2.0-mac-arm64.dmg`, `DocuFreedom-4.2.0-windows-x64-setup.exe`, and `DocuFreedom-4.2.0-windows-x64-portable.zip`. Consult the CI workflows and test report for the validation completed for each platform.
