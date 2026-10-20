# Run with PowerShell 7 on Windows 10/11 x64 and CPython 3.14.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:ONEFILE = '0'

if (-not (Test-Path '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment failed' }
}
$Python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
& $Python -m pip install --disable-pip-version-check -r requirements-windows.lock
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& "$PSScriptRoot/scripts/prepare-windows-runtimes.ps1"
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; refusing to package' }
New-Item -ItemType Directory -Force build, dist | Out-Null
& $Python -c "from PIL import Image; Image.open('dragshift/assets/branding/docufreedom.png').save('build/DocuFreedom.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed' }
& $Python -m PyInstaller DragShift.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

# Keep engines intact; PyInstaller must not rewrite their DLLs or search paths.
Copy-Item -Recurse vendor/windows/libreoffice dist/DocuFreedom/_internal/libreoffice
Copy-Item -Recurse vendor/windows/ghostscript dist/DocuFreedom/_internal/ghostscript
# The official GS installer normally installs Microsoft's shared CRT. Portable
# builds instead keep the unmodified redistributable DLLs beside each engine.
# PySide6's pinned Windows wheel already distributes this compatible VC14 CRT.
@'
from pathlib import Path
import shutil
import PySide6
source = Path(PySide6.__file__).parent
required = ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll')
assert all((source / name).is_file() for name in required), 'MSVC runtime DLL missing from Qt wheel'
for directory in ('ghostscript/bin', 'libreoffice/program'):
    target = Path('dist/DocuFreedom/_internal') / directory
    for pattern in ('msvcp140*.dll', 'vcruntime140*.dll'):
        for library in source.glob(pattern):
            if not (target / library.name).exists():
                shutil.copy2(library, target / library.name)
'@ | & $Python -
if ($LASTEXITCODE -ne 0) { throw 'App-local Microsoft runtime packaging failed' }
Copy-Item scripts/windows-runtime-notices.md dist/DocuFreedom/WINDOWS-RUNTIME-NOTICES.md
$app = Join-Path $PSScriptRoot 'dist/DocuFreedom/DocuFreedom.exe'
$smoke = Start-Process -FilePath $app -ArgumentList '--selftest' -Wait -PassThru
if ($smoke.ExitCode -ne 0) { throw 'Frozen application self-test failed' }

$env:DOCUFREEDOM_VERSION = (& $Python -c 'from dragshift import __version__; print(__version__)').Trim()
$inno = @("${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe", "$env:ProgramFiles/Inno Setup 6/ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $inno) {
    $innoCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($innoCommand) { $inno = $innoCommand.Source }
}
if (-not $inno) { throw 'Install Inno Setup 6 to build the Windows installer' }
& $inno installer/DocuFreedom.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
$portable = "DocuFreedom-$env:DOCUFREEDOM_VERSION-windows-x64-portable.zip"
$installer = "DocuFreedom-$env:DOCUFREEDOM_VERSION-windows-x64-setup.exe"
# 7-Zip preserves the directory layout and handles files > 2 GiB correctly.
$sevenZip = Join-Path $env:ProgramFiles '7-Zip/7z.exe'
if (-not (Test-Path $sevenZip)) { throw 'Install 7-Zip to package the portable ZIP' }
if (Test-Path "dist/$portable") { Remove-Item "dist/$portable" }
Push-Location dist
try {
    & $sevenZip a -tzip -mx=5 $portable DocuFreedom
    if ($LASTEXITCODE -ne 0) { throw 'Portable archive creation failed' }
    & $sevenZip t $portable
    if ($LASTEXITCODE -ne 0) { throw 'Portable archive integrity check failed' }
} finally { Pop-Location }
Copy-Item vendor/sources/ghostscript-10.08.0.tar.xz dist/ghostscript-10.08.0.tar.xz
$sums = foreach ($name in @($portable, $installer, 'ghostscript-10.08.0.tar.xz')) {
    $hash = (Get-FileHash "dist/$name" -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $name"
}
$sums | Set-Content -Encoding utf8NoBOM dist/SHA256SUMS-windows.txt
Remove-Item Env:QT_QPA_PLATFORM
Write-Host "Built DocuFreedom $env:DOCUFREEDOM_VERSION for Windows x64"
