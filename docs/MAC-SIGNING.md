# macOS signing status

DocuFreedom 4.0.0 is ad-hoc signed. `build-mac.command` verifies the app's
bundle signature and its embedded frameworks before creating the disk image.
This checks bundle integrity; it does not establish an Apple-verified developer
identity. The app and disk image are **not notarized**.

The current GitHub Actions workflow does not use signing secrets or perform
notarization. Adding secrets alone will not change that behavior. A future
Developer ID distribution needs a dedicated hardened-runtime signing and Apple
notarization step, followed by ticket stapling and validation on a clean Mac.

No certificate, private key, Apple account password or signing token belongs in
this repository. Consult Apple's official documentation before changing the
distribution workflow: <https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution>.
