# DocuFreedom 4.1.0

Office-to-PDF conversion now uses a bundled LibreOffice renderer. Previously, DOCX files were rebuilt as simplified HTML on a fixed page size, which could change the document's appearance and pagination. The new path reads the source document's styles, page sizes, margins, sections, tables, images, headers, and footers when exporting to PDF. XLSX, PPTX, and ODT use the same local Office engine.

- All Office-to-PDF entry points use the same renderer, including **Create PDF and edit** in the folder browser.
- The renderer is included in the macOS application. No separate Office installation or online service is required.
- The folder preview is explicitly labeled as extracted text. Open the generated PDF to review the formatted pages.
- Source documents remain unchanged; conversion saves a separate PDF copy.
- Fixed an extra 9-point offset that LibreOffice could add to inline DOCX pictures with omitted spacing attributes.
- Office images use lossless PDF export without downsampling.

LibreOffice and Microsoft Office can render complex elements differently. Missing fonts can also change line wrapping or pagination; install the fonts used in the original document for the closest result. This release does not claim pixel-identical rendering of every Office document. PDF-to-Word remains a separate reconstruction tool with its own layout limitations.

**Requirements:** Apple Silicon, macOS 15 or later. Replace the existing app in Applications with the new copy from the DMG. The build is ad-hoc signed and not Apple notarized.

Validation: **272 automated tests** and **39 source-runtime smoke checks** and **41 frozen-app smoke checks** passed, including real Office layout regressions. Signature, packaging and validation details are recorded in the [validation report](https://github.com/NikkiIMOEX5000/DocuFreedom/blob/main/docs/TEST-REPORT.md).

A special thank-you to [llamaboi55](https://github.com/llamaboi55) for [DragShift](https://github.com/llamaboi55/DragShift), whose project inspired DocuFreedom after its creator discovered it through Instagram.
