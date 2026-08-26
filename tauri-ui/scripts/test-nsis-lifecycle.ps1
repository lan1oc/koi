param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,

    [string]$ExpectedVersion = "4.0.0"
)

$ErrorActionPreference = "Stop"

if (-not $env:CI -and $env:KOI_ALLOW_LOCAL_NSIS_TEST -ne "1") {
    throw "NSIS lifecycle testing is restricted to CI. Set KOI_ALLOW_LOCAL_NSIS_TEST=1 only in an isolated Windows user profile."
}

$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$tempRootBase = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
$testRoot = Join-Path $tempRootBase ("koi-nsis-lifecycle-" + [Guid]::NewGuid().ToString("N"))
$installRoot = Join-Path $testRoot "install"
# Keep self-test data outside the installation tree. The executable is
# verified while its runtime files remain untouched, and each run still uses a
# unique temporary directory that starts empty.
$firstSelfTestData = Join-Path $tempRootBase ("koi-nsis-self-test-install-" + [Guid]::NewGuid().ToString("N"))
$updateSelfTestData = Join-Path $tempRootBase ("koi-nsis-self-test-update-" + [Guid]::NewGuid().ToString("N"))
$userDataRoot = Join-Path $env:LOCALAPPDATA "Koi"
$markerPath = Join-Path $userDataRoot ("ci-uninstall-preserve-" + [Guid]::NewGuid().ToString("N") + ".marker")

New-Item -ItemType Directory -Force -Path $testRoot | Out-Null

function Invoke-Nsis([string[]]$Arguments, [string]$Label) {
    $process = Start-Process -FilePath $installerPath -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "$Label failed with exit code $($process.ExitCode)"
    }
}

function Assert-InstalledRuntime([string]$Label) {
    $required = @(
        "probe-runtime.lock.json",
        "probe-runtime\python.exe",
        "probe-runtime\libcrypto-3.dll",
        "archive-runtime.lock.json",
        "pdfium-runtime.lock.json"
    )
    $missing = @($required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $installRoot $_) -PathType Leaf) })
    if ($missing.Count -gt 0) {
        throw "$Label is missing required installed runtime files: $($missing -join ', ')"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $installRoot "koi.exe") -PathType Leaf) -and
        -not (Test-Path -LiteralPath (Join-Path $installRoot "koi-tauri.exe") -PathType Leaf)) {
        throw "$Label is missing the installed Koi executable"
    }
}

function Find-KoiExecutable {
    $candidate = Get-ChildItem -LiteralPath $installRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @("koi.exe", "koi-tauri.exe") } |
        Select-Object -First 1
    if (-not $candidate) {
        throw "Installed koi.exe was not found under $installRoot"
    }
    return $candidate.FullName
}

function Wait-InstalledRuntime {
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    do {
        $executable = Get-ChildItem -LiteralPath $installRoot -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @("koi.exe", "koi-tauri.exe") } |
            Select-Object -First 1
        $probeLock = Join-Path $installRoot "probe-runtime.lock.json"
        $archiveLock = Join-Path $installRoot "archive-runtime.lock.json"
        $ready = $null -ne $executable -and
            (Test-Path -LiteralPath $probeLock -PathType Leaf) -and
            (Test-Path -LiteralPath $archiveLock -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $installRoot "probe-runtime\python.exe") -PathType Leaf)
        if ($ready) {
            return $executable.FullName
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "NSIS install did not expose the complete Rust/probe runtime before timeout"
}

function Invoke-SelfTest([string]$Executable, [string]$DataDirectory, [string]$Label) {
    if (Test-Path -LiteralPath $DataDirectory) {
        Remove-Item -LiteralPath $DataDirectory -Recurse -Force
    }
    # `--self-test` accepts an absent path and creates it itself. Creating the
    # directory in the parent process can race an NSIS file-copy worker on
    # some Windows configurations.
    $originalPath = $env:PATH
    try {
        # The packaged probe must use its locked CPython runtime. Keep system
        # DLL resolution available while removing every system Python entry.
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        Assert-InstalledRuntime $Label
        $process = Start-Process -FilePath $Executable -ArgumentList @("--self-test", "--data-dir", $DataDirectory) -Wait -PassThru -WindowStyle Hidden
        if ($process.ExitCode -ne 0) {
            throw "$Label self-test failed with exit code $($process.ExitCode)"
        }
    }
    finally {
        $env:PATH = $originalPath
    }
}

try {
    # NSIS requires /D to be the final argument.
    Invoke-Nsis @("/S", "/D=$installRoot") "NSIS install"
    $appExecutable = Wait-InstalledRuntime
    Assert-InstalledRuntime "NSIS install"
    Invoke-SelfTest $appExecutable $firstSelfTestData "Installed product"

    New-Item -ItemType Directory -Force -Path $userDataRoot | Out-Null
    Set-Content -LiteralPath $markerPath -Value "KOI $ExpectedVersion uninstall retention test" -Encoding Ascii

    Invoke-Nsis @("/S", "/UPDATE", "/D=$installRoot") "NSIS update"
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "NSIS update removed the user-data retention marker"
    }
    $appExecutable = Wait-InstalledRuntime
    Assert-InstalledRuntime "NSIS update"
    Invoke-SelfTest $appExecutable $updateSelfTestData "Updated product"

    $uninstaller = Get-ChildItem -LiteralPath $installRoot -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "(?i)uninstall.*\.exe$" } |
        Select-Object -First 1
    if (-not $uninstaller) {
        throw "NSIS uninstaller was not found under $installRoot"
    }
    $uninstallProcess = Start-Process -FilePath $uninstaller.FullName -ArgumentList "/S" -Wait -PassThru -WindowStyle Hidden
    if ($uninstallProcess.ExitCode -ne 0) {
        throw "NSIS uninstall failed with exit code $($uninstallProcess.ExitCode)"
    }
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "NSIS uninstall removed user data; the default must preserve it"
    }
    if (Test-Path -LiteralPath $appExecutable -PathType Leaf) {
        throw "NSIS uninstall left koi.exe installed: $appExecutable"
    }

    Write-Host "NSIS install, update, self-test, uninstall, and user-data retention checks passed."
}
finally {
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        Remove-Item -LiteralPath $markerPath -Force
    }
    foreach ($dataDirectory in @($firstSelfTestData, $updateSelfTestData)) {
        if (Test-Path -LiteralPath $dataDirectory) {
            Remove-Item -LiteralPath $dataDirectory -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path -LiteralPath $testRoot) {
        for ($attempt = 0; $attempt -lt 12; $attempt++) {
            try {
                Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction Stop
                break
            }
            catch {
                if ($attempt -eq 11) { throw }
                Start-Sleep -Milliseconds 500
            }
        }
    }
}
