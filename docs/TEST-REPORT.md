# Validation report — DocuFreedom 4.2.0

Date: 2026-10-20–21. Test inputs are synthetic documents; no personal documents are published.

## Source regression suite

On Apple Silicon macOS, **304 tests passed and one Windows-only OCR test was skipped**. Five upstream SWIG deprecation warnings were emitted. Coverage includes the existing conversion/editor/security suite and new idle input scheduling, lazy imports, hidden-preview cleanup, PDF thumbnail bounds, encrypted undo, disk-full recovery, tray caching, and Windows adapter contracts. Additional malformed-PDF tests verify that parser exceptions release their file handles before temporary workspace cleanup, including while the public error remains alive. Unicode fixtures use explicit UTF-8 on every platform.

A generated 400-page PDF verifies that a hidden editor rasterizes no pages, visible/nearby thumbnail caches never exceed 16 entries, scrolling evicts old icons, and hiding stops raster timers and clears decoded images. Undo tests exercise 12 retained disk checkpoints, encrypted document restoration, authentication failure, partial-write cleanup, and mapped-file closure. Unsaved text survives hiding and reopening the main workspace.

Cold-start tests verify that the tray and preference changes do not import Pillow, NumPy, PyMuPDF, Office libraries, or the document workspace. The macOS watcher uses mouse-down/up event monitors; the active timer is stopped between drags. Fallback polling is 100 ms while idle and 15 ms during a drag. The radial hover timer stops after animation settles, and no desktop capture/refraction worker remains.

## Performance measurement

`scripts/benchmark-idle.py` provides an isolated 15-second-per-phase source benchmark using temporary preferences and a generated PDF. The offscreen platform exercises the fallback watcher: approximately **10 input timer callbacks/second**, compared with approximately **67/second** in 4.1. The real macOS event backend is checked separately because offscreen Qt cannot install AppKit observers.

A separate live Cocoa cold-tray fixture measured 19.61 seconds with **zero input-timer callbacks**, two native mouse observers, no workspace or processing imports, and an inactive timer throughout. Process CPU time was 0.0086 seconds (approximately **0.044% of one core**); RSS was **69 MiB in that run**. This is an isolated source-runtime measurement, not a fixed packaged-app memory guarantee.

Process RSS varies with macOS compression, loaded libraries, file caches, and the documents opened. These checks establish bounded rendering and reduced background work; they do not promise a fixed RAM footprint or zero power use. Conversion engines still consume resources while processing documents.

## Release validation

The source-runtime self-test passed **39 checks**. A live Cocoa material fixture passed **24 checks** for light/dark native blur, Retina alpha masks, transparent windows, settled animation, and complete cleanup on hide.

The frozen macOS app passed **41 smoke checks**, including real Office conversion, OCR, PDF standards, signatures and edited-document saving. Deep strict code-signature verification passed after conversions. The macOS DMG passed `hdiutil verify` and was installed in Applications. Native UI checks confirmed version 4.2.0, the preserved dark theme, opening the full workspace and closing it to the tray. Installed diagnostics confirmed a reachable AppKit status item, accessory policy (no Dock icon), two mouse observers and an inactive input timer. After opening and closing the workspace, a later idle snapshot showed 0.0% CPU and approximately 72 MiB RSS; memory use depends on documents and macOS compression. The hosted [macOS build](https://github.com/NikkiIMOEX5000/DocuFreedom/actions/runs/39497117556) also passed the full build, tests, frozen smoke checks, signature verification and DMG verification.

On the native Windows runner, **290 tests passed and 15 platform-specific tests were skipped**. The final [Windows run 39545490100](https://github.com/NikkiIMOEX5000/DocuFreedom/actions/runs/39545490100) completed successfully on commit `38c58eb`. Its frozen executable passed **40 smoke checks** and exited successfully in 34 seconds. The installer and portable archive were built; per-user installation, an installed-app self-test and uninstall also passed. Both the verified Windows release artifacts and diagnostics were uploaded successfully. The Windows OCR smoke check verifies packaged WinRT projections; it does not establish OCR recognition accuracy. Physical printers/scanners and arbitrary user documents are outside the automated suite.

---

# Previous release: DocuFreedom 4.1.0

Date: 2026-10-19. All regression fixtures are generated documents; no personal files are included in this repository.

## Office conversion update

The former DOCX exporter rebuilt documents as simplified HTML on a fixed Letter page. DOCX, XLSX, PPTX and ODT now use the checksum-pinned LibreOffice 26.8.1.1 runtime included in the application.

**272 automated tests passed**, with five upstream SWIG deprecation warnings. The source-runtime self-test passed **39 checks**.

New coverage includes seven real-engine DOCX layout regressions and 20 renderer isolation/error tests. Generated documents cover Letter and A4, portrait and landscape sections, explicit page breaks, section-specific headers and footers, margins, type sizes, bold/italic/color, centered text, Cyrillic, numbered lists, horizontally/vertically merged cells, inline pictures and floating anchors. All three rendered fixture pages were visually reviewed; no clipping, overlap or missing glyphs was observed.

A regression exposed a 9-point shift in inline pictures when the source omitted DrawingML distance attributes. The renderer now makes only those omitted values explicit as zero in a temporary input copy. Explicit values and floating anchors are preserved. This follows ECMA-376 Part 1 §20.4.2.8; tests cover both omitted and explicit nonzero values and verify the original file remains byte-identical.

Failure tests cover missing engines, invalid/encrypted/repaired output, failed processes, timeouts, concurrent isolated profiles, output write failure and cleanup. Invalid output never replaces the previous result; there is no silent HTML fallback. Spreadsheet tests now verify real formula results and hidden-sheet handling.

The frozen application passed **41 smoke checks**, including actual Office conversion and verification that the renderer resolves inside the current app bundle. Deep, strict code-signature verification passed after those conversions. The official nested LibreOffice signature is retained; Python bytecode writes are disabled in child processes so conversions do not change signed runtime resources. All python-docx templates and their required parent resource directory are included in the frozen app. The generated DMG passed `hdiutil verify`. Installed GUI checks are pending.

The folder browser's Office preview still shows extracted text. The PDF produced by the Office renderer is the page-layout preview. PDF-to-Word uses a separate reconstruction path; improvements to Office-to-PDF do not establish equivalent fidelity in the reverse direction.

## Fidelity limits

LibreOffice reads the document's page settings and styles, but its renderer is not Microsoft Word. Missing fonts, unsupported features, and differences between Office engines may change wrapping, pagination, or complex elements. The regression suite covers representative generated inputs and does not establish pixel-identical output for every document. The user's original problematic DOCX was not supplied, so that exact file has not been validated.

The following report records completed checks for the previous release only. Its pass counts must not be presented as 4.1.0 results.

---

## Previous release: DocuFreedom 4.0.0

Local validation on Apple Silicon, macOS 26.5.2, Python 3.14 / PySide6 6.12.
Date: 2026-10-19. All fixtures are generated test documents; no personal files
are included in this repository.

### Automated suite

`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`

**245 tests passed.** Five upstream SWIG deprecation warnings were emitted.
Coverage includes PDF operations and original-file preservation, conversions,
annotation editing and redaction, output paths, signature integrity, standards
export, UI routing, folder/text/Office previews, password handling, theme
switching, pinned tools, native menu-bar bridge, reopening, and safe quitting
with unsaved changes. Hardware and GUI mocks are explicitly limited below.

### Bundle checks

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

### Hosted build and release

The first GitHub Actions run on macOS 15 ARM64 also passed all 245 tests and
the 33 source-runtime checks, built and signed the app, and completed its frozen
self-test. Its final DMG creation failed with `hdiutil: create failed - Resource
busy`. The public v4.0.0 release therefore contains the verified local build;
the uploaded installer digest matches the local checksum.

Packaging now retries this specific transient error at most three times,
preserves diagnostics, and fails immediately for other errors. Three isolated
shell checks cover recovery, exhausted retries, and non-retryable failures. A
real packaging-only run and disk-image verification passed locally.

### Limits of the 4.0.0 checks

- Physical printer and scanner output requires connected hardware and has not
  been validated in this test environment.
- PDF/A and PDF/X checks do not claim independent veraPDF or print-shop certification.
- Office conversions use approximate layout; they are not a Microsoft Office rendering engine.
- Native menu-bar bridge unit tests mock AppKit window creation. Installed-app
  validation is separate from those tests.
- Ad-hoc signing checks bundle integrity. The release is not Apple notarized,
  and testing on this Mac does not establish Gatekeeper acceptance on a clean Mac.
- A passing suite is not a claim that every possible input file or printer is supported.
