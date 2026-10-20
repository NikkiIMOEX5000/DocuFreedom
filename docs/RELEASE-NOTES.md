# DocuFreedom 4.2.0

A quieter tray companion, a calmer glass menu, and a native Windows package.

- **Less background work:** on macOS, mouse events wake the Shift-drag watcher only while a button is held. The idle input-polling timer stops completely. Windows and the fallback path use a slower idle check and switch to the responsive drag interval when needed.
- **Load tools when needed:** the main workspace and document-processing libraries no longer load merely to show the tray icon. Downloads scanning is cached and runs only when the panel needs it.
- **Bounded previews:** hidden windows release rendered previews. The PDF editor keeps at most 16 nearby page thumbnails; up to 12 undo checkpoints use private temporary files instead of retaining full document copies in RAM. Unsaved text and encrypted PDF undo remain supported.
- **Calm glass:** the Shift-drag menu has neutral translucent surfaces and native macOS material, with no colored gradients, desktop screenshots, or NumPy refraction worker. Hover animation stops after settling.
- **Windows x64:** per-user installer and portable ZIP, bundled LibreOffice and Ghostscript, Windows OCR, region capture, scanner integration, Explorer reveal, and optional startup/context-menu integration.
- **Existing tools retained:** editing, pinned actions, folder previews, conversions, signatures, standards export, and theme switching remain available. Office-to-PDF still uses the local LibreOffice renderer introduced in 4.1.

**Downloads:** choose the macOS Apple Silicon DMG, Windows x64 setup EXE, or Windows x64 portable ZIP. The macOS build requires macOS 15+ and is ad-hoc signed, not notarized. Windows packages are unsigned. Extract the entire portable folder before launching DocuFreedom.exe. Windows OCR uses installed recognition languages; scanning and printing require compatible hardware.

Document processing can still use CPU and memory while a conversion or editor is active. Missing fonts and differences between LibreOffice and Microsoft Office can change complex Office layouts; install the source document's fonts for the closest result.

Completed checks and platform limits are recorded in the [validation report](https://github.com/NikkiIMOEX5000/DocuFreedom/blob/main/docs/TEST-REPORT.md).

A special thank-you to [llamaboi55](https://github.com/llamaboi55) for [DragShift](https://github.com/llamaboi55/DragShift). Its Shift-drag workflow inspired DocuFreedom after its creator found the project through Instagram.
