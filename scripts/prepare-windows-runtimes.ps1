# Official standalone runtimes. Nothing is installed on the end user's machine.
# MSI administrative extraction and NSIS payload extraction run only at build time.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectDir = Split-Path -Parent $PSScriptRoot
$Sources = Join-Path $ProjectDir 'vendor/sources'
$WindowsVendor = Join-Path $ProjectDir 'vendor/windows'
New-Item -ItemType Directory -Force $Sources, $WindowsVendor | Out-Null

function Invoke-BuildPhase([string]$Name, [string]$Executable, [string[]]$Arguments,
                           [int]$TimeoutSeconds, [int[]]$AllowedExitCodes = @(0)) {
    Write-Host "Starting $Name (timeout ${TimeoutSeconds}s)"
    $stdout = Join-Path $WindowsVendor "$Name.stdout.log"
    $stderr = Join-Path $WindowsVendor "$Name.stderr.log"
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    # Keep the handle so ExitCode remains available after the process exits.
    $null = $process.Handle
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $nextStatus = 30
    while (-not $process.WaitForExit(1000)) {
        if ($watch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
            & "$env:SystemRoot/System32/taskkill.exe" /PID $process.Id /T /F | Out-Null
            throw "$Name exceeded ${TimeoutSeconds}s; stopped its process tree. See $stderr"
        }
        if ($watch.Elapsed.TotalSeconds -ge $nextStatus) {
            Write-Host "$Name is running ($([int]$watch.Elapsed.TotalSeconds)s)"
            $nextStatus += 30
        }
    }
    $process.WaitForExit()
    foreach ($log in @($stdout, $stderr)) {
        if (Test-Path $log) { Get-Content $log -Tail 20 | Write-Host }
    }
    if ($process.ExitCode -notin $AllowedExitCodes) {
        throw "$Name failed ($($process.ExitCode)); see $stderr"
    }
    Write-Host "Completed $Name in $([int]$watch.Elapsed.TotalSeconds)s"
}

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
Invoke-BuildPhase 'libreoffice-extract' 'msiexec.exe' `
    @('/a', "`"$officeMsi`"", '/qn', "TARGETDIR=`"$officeExtraction`"", '/L*v', "`"$msiLog`"") 600 @(0, 3010)
$officeProgram = @(Get-ChildItem $officeExtraction -Filter soffice.com -Recurse -File)
if ($officeProgram.Count -ne 1) { throw 'Expected exactly one extracted LibreOffice program directory' }
Move-Item $officeProgram[0].Directory.Parent.FullName $officeRuntime
# Some MSI administrative images put program/ directly under TARGETDIR. In
# that layout Move-Item has already moved the extraction directory itself.
if (Test-Path $officeExtraction) { Remove-Item -Recurse -Force $officeExtraction }
# Retain runtime resources and notices, but not the administrative MSI database.
Get-ChildItem $officeRuntime -Filter '*.msi' -File | Remove-Item -Force

# Ghostscript 10.08.0's official NSIS .onInit calls SetSilent normal, overriding
# /S. Extract its verified payload instead of running an interactive installer.
# This also avoids modifying registry entries, PATH or other GS installations.
$sevenZip = Join-Path $env:ProgramFiles '7-Zip/7z.exe'
if (-not (Test-Path $sevenZip)) { throw 'Install 7-Zip to extract the official Ghostscript payload' }
Invoke-BuildPhase 'ghostscript-extract' $sevenZip @('x', '-y', "`"$gsInstaller`"", "-o`"$gsRuntime`"") 180
if (-not (Test-Path "$gsRuntime/bin/gswin64c.exe")) { throw 'Ghostscript executable missing' }
if (-not (Test-Path "$gsRuntime/iccprofiles/srgb.icc")) { throw 'Ghostscript ICC profiles missing' }
Copy-Item "$PSScriptRoot/windows-runtime-notices.md" "$officeRuntime/DocuFreedom-NOTICE.md"
Copy-Item "$PSScriptRoot/windows-runtime-notices.md" "$gsRuntime/DocuFreedom-NOTICE.md"

$env:PYTHONDONTWRITEBYTECODE = '1'
Invoke-BuildPhase 'libreoffice-version' "$officeRuntime/program/soffice.com" @('--headless', '--version') 30
Invoke-BuildPhase 'ghostscript-version' "$gsRuntime/bin/gswin64c.exe" @('--version') 30
