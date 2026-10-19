# PyInstaller spec. ONEFILE=1 -> portable single exe; otherwise a folder for the installer.
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata, collect_dynamic_libs

onefile = os.environ.get("ONEFILE") == "1"
heif_datas, heif_bins, heif_hidden = collect_all("pillow_heif")
extra_data = []
for package in ("pyhanko", "pyhanko_certvalidator", "pikepdf", "certifi", "docx", "pptx", "openpyxl", "jsonschema_specifications"):
    extra_data += collect_data_files(package)
for package in ("pyHanko", "pyhanko-certvalidator", "pikepdf"):
    extra_data += copy_metadata(package)
if sys.platform == "darwin":
    extra_data += [("vendor/ghostscript/iccprofiles", "ghostscript/iccprofiles"),
                   ("vendor/ghostscript/licenses", "ghostscript/licenses"),
                   ("vendor/ghostscript/NOTICE.md", "ghostscript")]

a = Analysis(
    ["run.py"],
    datas=[("dragshift/assets", "dragshift/assets"), ("licenses", "licenses"), ("THIRD-PARTY-NOTICES.md", "."), ("LICENSE", "."), ("CREDITS.md", "."), ("docs/FEATURES-RU.md", "."),
           ("scripts/runtime/docx-parts.txt", "docx/parts")] + heif_datas + extra_data,
    binaries=heif_bins + collect_dynamic_libs("pikepdf", search_patterns=["*.dylib", "*.so"]) + ([("vendor/ghostscript/bin/gs", "ghostscript/bin")] if sys.platform == "darwin" else []),
    hiddenimports=(["win32com.client"] if sys.platform == "win32" else ["AppKit", "Quartz", "Vision", "CoreML", "objc"]) + ["PySide6.QtNetwork", "PySide6.QtPrintSupport"] + heif_hidden + collect_submodules("pyhanko") + collect_submodules("pyhanko_certvalidator") + collect_submodules("asn1crypto") + collect_submodules("oscrypto") + collect_submodules("fontTools"),
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest",
              "PySide6.QtOpenGL", "PySide6.QtSvgWidgets", "PySide6.QtDesigner", "matplotlib", "scipy"],
)

DROP = ("Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6WebEngine", "Qt63D", "Qt6Multimedia", "Qt6Charts",
        "Qt6VirtualKeyboard", "Qt6Designer", "Qt6ShaderTools", "Qt6Sql", "Qt6Test", "opengl32sw",
        "Qt6OpenGL", "Qt6DataVisualization", "Qt6Positioning", "Qt6Sensors", "Qt6SerialPort",
        "Qt6Bluetooth", "Qt6Nfc", "Qt6RemoteObjects", "Qt6Scxml", "Qt6SpatialAudio", "Qt6TextToSpeech",
        "Qt6WebChannel", "Qt6WebSockets", "Qt6Svg", "qtquick", "qml")
# On macOS Qt plugin dependencies are frameworks with aliases and resource
# links. Removing individual binaries breaks both dyld and codesign.
if sys.platform != "darwin":
    a.binaries = [b for b in a.binaries if not any(d.lower() in b[0].lower() for d in DROP)]
a.datas = [d for d in a.datas if "translations" not in d[0].replace("\\", "/")]

pyz = PYZ(a.pure)
IS_MAC = sys.platform == "darwin"
common = dict(name="DocuFreedom" if IS_MAC else "DragShift", console=False, upx=False)
if IS_MAC:
    common.update(icon="dragshift/assets/dragshift.icns")
else:
    common.update(icon="dragshift/assets/dragshift.ico", version="installer/version_info.txt")

if IS_MAC:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, argv_emulation=False, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="DocuFreedom", upx=False)
    app = BUNDLE(
        coll,
        name="DocuFreedom.app",
        icon="dragshift/assets/dragshift.icns",
        bundle_identifier="apps.dna.DocuFreedom",
        info_plist={
            "CFBundleName": "DocuFreedom",
            "CFBundleDisplayName": "DocuFreedom",
            "CFBundleShortVersionString": "4.1.0",
            "CFBundleVersion": "410",
            "LSUIElement": True,
            "LSMinimumSystemVersion": "15.0",
            "CFBundleDevelopmentRegion": "ru",
            "CFBundleLocalizations": ["ru", "en"],
            "NSDocumentsFolderUsageDescription": "DocuFreedom открывает выбранные файлы и сохраняет рядом результаты обработки.",
            "NSDownloadsFolderUsageDescription": "DocuFreedom показывает последнюю загрузку и сохраняет результаты обработки.",
            "NSDesktopFolderUsageDescription": "DocuFreedom открывает выбранные файлы и сохраняет рядом результаты обработки.",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            # Finder Open With; never claim default ownership.
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "DocuFreedom documents",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.image", "com.adobe.pdf", "public.text", "org.openxmlformats.wordprocessingml.document", "org.openxmlformats.spreadsheetml.sheet", "org.openxmlformats.presentationml.presentation"],
            }],
        },
    )
elif onefile:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="DragShift", upx=False)
