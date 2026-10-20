param(
    [Parameter(Mandatory = $true)][string]$AppPath,
    [ValidateRange(1, 3600)][int]$TimeoutSeconds = 360
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$AppPath = (Resolve-Path $AppPath).Path
$smokeLog = Join-Path $env:LOCALAPPDATA 'DocuFreedom/log.txt'
$script:SmokeLogOffset = if (Test-Path $smokeLog) { (Get-Item $smokeLog).Length } else { 0L }
$script:SmokeSucceeded = $false

function Write-NewSmokeLog {
    if (-not (Test-Path $smokeLog)) { return }
    $stream = $null
    $reader = $null
    try {
        $sharing = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
        $stream = [System.IO.File]::Open($smokeLog, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read, $sharing)
        if ($stream.Length -lt $script:SmokeLogOffset) { $script:SmokeLogOffset = 0L }
        $stream.Position = $script:SmokeLogOffset
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
        $text = $reader.ReadToEnd()
        $script:SmokeLogOffset = $stream.Position
        if ($text) {
            Write-Host $text.TrimEnd()
            if ($text -match '(?m)^SELFTEST OK\r?$') { $script:SmokeSucceeded = $true }
        }
    } catch [System.IO.IOException] {
        # Logging can rotate at startup. The next poll retries the new file.
        Write-Host "Self-test log temporarily unavailable: $($_.Exception.Message)"
    } finally {
        if ($reader) { $reader.Dispose() }
        elseif ($stream) { $stream.Dispose() }
    }
}

function Write-SmokeProcessTree([int]$RootProcessId) {
    try {
        $processes = @(Get-CimInstance Win32_Process -OperationTimeoutSec 10)
        $owned = [System.Collections.Generic.HashSet[int]]::new()
        [void]$owned.Add($RootProcessId)
        do {
            $added = $false
            foreach ($item in $processes) {
                if ($owned.Contains([int]$item.ParentProcessId) -and $owned.Add([int]$item.ProcessId)) {
                    $added = $true
                }
            }
        } while ($added)
        Write-Host 'Self-test process tree:'
        $processes | Where-Object { $owned.Contains([int]$_.ProcessId) } |
            Select-Object ProcessId, ParentProcessId, Name, ExecutablePath, CommandLine |
            Format-List | Out-String | Write-Host
    } catch {
        Write-Host "Could not inspect self-test process tree: $($_.Exception.Message)"
    }
}

Write-Host "Starting frozen self-test: $AppPath (timeout ${TimeoutSeconds}s)"
$process = Start-Process -FilePath $AppPath -ArgumentList '--selftest' -PassThru
# Retain the handle so ExitCode is still available after the executable exits.
$null = $process.Handle
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$nextStatus = 20
try {
    while (-not $process.WaitForExit(1000)) {
        if ($watch.Elapsed.TotalSeconds -ge $nextStatus) {
            Write-Host "Frozen self-test is running ($([int]$watch.Elapsed.TotalSeconds)s, PID $($process.Id))"
            Write-NewSmokeLog
            $nextStatus += 20
        }
        if ($watch.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
            Write-NewSmokeLog
            Write-SmokeProcessTree $process.Id
            # Terminate only the executable launched above and its descendants.
            & "$env:SystemRoot/System32/taskkill.exe" /PID $process.Id /T /F | Write-Host
            [void]$process.WaitForExit(10000)
            throw "Frozen self-test exceeded ${TimeoutSeconds}s; its process tree was stopped."
        }
    }
    $process.WaitForExit()
    Write-NewSmokeLog
    if ($process.ExitCode -ne 0) {
        throw "Frozen self-test failed with exit code $($process.ExitCode)."
    }
    if (-not $script:SmokeSucceeded) {
        throw 'Application exited without a fresh SELFTEST OK result in its log.'
    }
    Write-Host "Frozen self-test passed in $([int]$watch.Elapsed.TotalSeconds)s"
} finally {
    $process.Dispose()
}
