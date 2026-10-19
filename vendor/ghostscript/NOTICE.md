# Bundled Ghostscript

Ghostscript 10.08.0, built from the unmodified official Artifex source for arm64 macOS 14 or later.

- Release: https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/tag/gs10080
- Source: https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/ghostscript-10.08.0.tar.xz
- Source SHA-256: `c20492bc8ebb96c87fa2e52a0926e1cda8cde95d66145e018ac713fed5da38cf`
- License: GNU Affero General Public License version 3 or later; full text and component notices in `licenses/`.
- Build instructions: `scripts/build-ghostscript.sh` in the DocuFreedom source tree.
- Build downloads the original source archive to `vendor/sources/ghostscript-10.08.0.tar.xz` in the source tree.

The executable embeds Ghostscript initialization resources and fonts. It dynamically links only Apple's system libraries. No system-wide Ghostscript installation is required.

The bundled `srgb.icc` and `default_cmyk.icc` profiles come from the same Ghostscript source distribution and share its licensing. The CMYK profile is a generic engine default, not a guarantee of compatibility with a particular print shop. Users can choose their printer's CMYK ICC profile for PDF/X export.

PDF/A-2b and PDF/X-3:2002 exports use Ghostscript's strict compatibility policy (abort on unsupported features). DocuFreedom checks output standard declarations, embedded ICC output intent, embedded fonts, and page count. PDF/A output additionally must pass pikepdf's local allowlist validator; a failure or unsupported construct prevents saving the result. This is not veraPDF certification. Production print jobs should undergo the receiving printer's preflight; archival workflows can additionally validate output using veraPDF.

Engine documentation: https://ghostscript.readthedocs.io/en/gs10.08.0/VectorDevices.html
