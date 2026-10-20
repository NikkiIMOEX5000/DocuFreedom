# Official standalone runtimes. Nothing is installed on the end user's machine.
# MSI administrative extraction and the Ghostscript installer run only at build time.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectDir = Split-Path -Parent $PSScriptRoot
$Sources = Join-Path $ProjectDir 'vendor/sources'
$WindowsVendor = Join-Path $ProjectDir 'vendor/windows'
New-Item -ItemType Directory -Force $Sources, $WindowsVendor | Out-Null

function Get-VerifiedFile([string]$Url, [string]$Name, [string]$Sha256) {
    $path = Join-Path $Sources $Name
    if (-not (Test-Path $path)) {
        $partial = "$path.part"
        & curl.exe --fail --location --show-error --retry 3 --connect-timeout 20 --max-time 1200 $Url -o $partial
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Name" }
        if ((Get-FileHash $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256) {
            throw "Checksum mismatch: $Name"
        }
        Move-Item -Force $partial $path
    }
    if ((Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256) {
        throw "Checksum mismatch: $Name"
    }
    return $path
}

$officeMsi = Get-VerifiedFile `
    'https://download.documentfoundation.org/libreoffice/stable/26.8.1/win/x86_64/LibreOffice_26.8.1_Win_x86-64.msi' `
    'LibreOffice_26.8.1_Win_x86-64.msi' `
    'c6298b10cfa1748bcbedad94c62ce771e240e5021bfd6d7a967cd571b04b5312'
$gsInstaller = Get-VerifiedFile `
    'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/gs10080w64.exe' `
    'gs10080w64.exe' `
    '52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50'
$gsSource = Get-VerifiedFile `
    'https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/ghostscript-10.08.0.tar.xz' `
    'ghostscript-10.08.0.tar.xz' `
    'c20492bc8ebb96c87fa2e52a0926e1cda8cde95d66145e018ac713fed5da38cf'

$officeExtraction = Join-Path $WindowsVendor 'office-extraction'
$officeRuntime = Join-Path $WindowsVendor 'libreoffice'
$gsRuntime = Join-Path $WindowsVendor 'ghostscript'
# These paths are reproducible vendor caches, not installed Office applications.
foreach ($path in @($officeExtraction, $officeRuntime, $gsRuntime)) {
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}
New-Item -ItemType Directory $officeExtraction | Out-Null
$msiLog = Join-Path $WindowsVendor 'libreoffice-extract.log'
$msi = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @('/a', "`"$officeMsi`"", '/qn', "TARGETDIR=`"$officeExtraction`"", '/L*v', "`"$msiLog`"")
if ($msi.ExitCode -notin @(0, 3010)) { throw "LibreOffice extraction failed ($($msi.ExitCode)); see $msiLog" }
$officeProgram = @(Get-ChildItem $officeExtraction -Filter soffice.com -Recurse -File)
if ($officeProgram.Count -ne 1) { throw 'Expected exactly one extracted LibreOffice program directory' }
Move-Item $officeProgram[0].Directory.Parent.FullName $officeRuntime
Remove-Item -Recurse -Force $officeExtraction

# NSIS /D must be the final argument and must not be quoted, even with spaces.
$gsInstall = Start-Process -FilePath $gsInstaller -Wait -PassThru -ArgumentList "/S /D=$gsRuntime"
if ($gsInstall.ExitCode -ne 0) { throw "Ghostscript extraction failed ($($gsInstall.ExitCode))" }
if (-not (Test-Path "$gsRuntime/bin/gswin64c.exe")) { throw 'Ghostscript executable missing' }
if (-not (Test-Path "$gsRuntime/iccprofiles/srgb.icc")) { throw 'Ghostscript ICC profiles missing' }
Copy-Item "$PSScriptRoot/windows-runtime-notices.md" "$officeRuntime/DocuFreedom-NOTICE.md"
Copy-Item "$PSScriptRoot/windows-runtime-notices.md" "$gsRuntime/DocuFreedom-NOTICE.md"

$env:PYTHONDONTWRITEBYTECODE = '1'
& "$officeRuntime/program/soffice.com" --headless --version
if ($LASTEXITCODE -ne 0) { throw 'LibreOffice runtime does not launch' }
& "$gsRuntime/bin/gswin64c.exe" --version
if ($LASTEXITCODE -ne 0) { throw 'Ghostscript runtime does not launch' }
