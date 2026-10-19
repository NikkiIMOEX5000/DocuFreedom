# DocuFreedom 4.0.0

The first public DocuFreedom release by dna.apps, developed from DragShift.

- Editor-first workspace with local folder browsing and previews.
- Light, dark, and system themes; pinned frequent PDF tools.
- Native macOS menu-bar companion, latest files, and Finder reveal.
- PDF editor and 55-tool catalog, local Russian/English OCR, certificate signing, PDF/A and PDF/X export.
- New dog mascot and DocuFreedom identity.

**Requirements:** Apple Silicon, macOS 15 or later. The app includes its runtime; Python and Ghostscript are not needed separately.

Open the DMG and drag DocuFreedom to Applications. The build is ad-hoc signed and not Apple notarized. If blocked, use macOS Privacy & Security → Open Anyway after attempting to open it.

See README and docs/TEST-REPORT.md for tested behavior and conversion limitations. The Ghostscript source archive accompanies releases for the bundled engine; the application source is included in this Git tag.

A special thank-you to [llamaboi55](https://github.com/llamaboi55) for [DragShift](https://github.com/llamaboi55/DragShift). Discovering the original project through Instagram inspired this continuation.

Validation: 245 automated tests and 33 packaged-runtime smoke checks passed on Apple Silicon. Menu-bar placement, theme persistence and reopening were verified in the installed app. See `docs/TEST-REPORT.md` for scope and limitations.
