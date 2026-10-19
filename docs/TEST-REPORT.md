# Validation report — DocuFreedom 4.0.0

Local validation on Apple Silicon, macOS 26.5.2, Python 3.14 / PySide6 6.12.
Date: 2026-10-19. All fixtures are generated test documents; no personal files
are included in this repository.

## Automated suite

`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`

**245 tests passed.** Five upstream SWIG deprecation warnings were emitted.
Coverage includes PDF operations and original-file preservation, conversions,
annotation editing and redaction, output paths, signature integrity, standards
export, UI routing, folder/text/Office previews, password handling, theme
switching, pinned tools, native menu-bar bridge, reopening, and safe quitting
with unsaved changes. Hardware and GUI mocks are explicitly limited below.

## Bundle checks

The packaging script also runs `run.py --selftest` in source and in the frozen
application. This checks embedded native dependencies with real PDFs, Office
files, Unicode fonts, QPDF linearization, Ghostscript PDF/A and PDF/X export,
Apple Vision Russian/English OCR, temporary PKCS#12 certificates, and tamper
detection. It constructs the desktop, tray panel, and PDF editor and saves a
real edited document. A self-signed test certificate is expected to be
untrusted; integrity and certificate trust are checked separately.

The packaged application passed **33 smoke checks** and returned exit code 0.
`codesign --verify --deep --strict` passed for the installed bundle; `hdiutil
verify` passed for the disk image. Native UI checks confirmed dark theme,
editor-first navigation, PDF preview, and opening a PDF directly in the editor.
Installed AppKit diagnostics confirmed `visible=true`, `window_visible=true`,
`outside_notch_safe_area=false`, `reachable=true`, and accessory activation
policy (no Dock icon), including after restart. Light/dark switching and dark
selection persistence were verified in the installed UI. The folder selection
was restored and reopening the running app opened the full workspace.

A real blocked filesystem call exposed a startup freeze during validation.
Recent-file scanning and metadata checks now run in bounded daemon workers.
The installed menu stayed responsive and quit/restarted normally while the
Downloads check was still waiting for OS access. Filesystem permissions must
still be granted by the user; the app does not bypass macOS permission dialogs.
After folder access became available, the installed app detected the new DMG
in Downloads and its Reveal in Finder action opened that folder with the exact
DMG selected. This completed the Downloads card end-to-end check.

The final eye refinement changes only icon assets. The PNG and macOS ICNS were
updated in the installed bundle and disk image, with strict signature and DMG
verification repeated. The new icon was visually verified in the running menu
panel; application code and the tested functionality are unchanged.

## Limits

- Physical printer and scanner output requires connected hardware and has not
  been validated in this test environment.
- PDF/A and PDF/X checks do not claim independent veraPDF or print-shop certification.
- Office conversions use approximate layout; they are not a Microsoft Office rendering engine.
- Native menu-bar bridge unit tests mock AppKit window creation. Installed-app
  validation is separate from those tests.
- Ad-hoc signing checks bundle integrity. The release is not Apple notarized,
  and testing on this Mac does not establish Gatekeeper acceptance on a clean Mac.
- A passing suite is not a claim that every possible input file or printer is supported.
