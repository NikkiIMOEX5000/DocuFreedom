# Contributing to DocuFreedom

Thanks for helping make local document tools better.

1. Open an issue for a bug or a proposed feature. Include macOS version, app version, and exact reproduction steps.
2. Use synthetic or fully anonymized sample documents. Never upload private certificates, passwords, personal files, or confidential PDFs.
3. Fork the project, create a focused branch, and make your change.
4. Run the relevant tests, then `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
5. For packaging, dependency, or native integration changes, also run `./build-mac.command` and verify the resulting app.
6. Open a pull request explaining the user-visible behavior, verification, and limitations.

Keep source files intact: transformations should write unique output copies with atomic saves. Redaction must remove PDF content, not just cover it. Never treat cryptographic integrity as proof of certificate trust. Pause UI PDF rendering while background PDF work runs.

UI strings are currently primarily Russian; repository documentation is English. New tools need an explicit error state and a real implementation. Avoid cards that merely advertise future features.

Contributions are accepted under the project's AGPL-3.0-or-later license, with existing third-party notices preserved.
