param(
    [switch]$SkipInstall = $false,
    [switch]$Verify = $false,
    [string]$NodeVersion = '22.16.0',
    [string]$ReleaseBase = '',
    [string]$CargoTargetDir = '',
    [switch]$SkipNsis = $false,
    [switch]$AllowMigrationOwners = $false,
    [switch]$StrictRelease = $false,
    [switch]$DryRun = $false
)

$ErrorActionPreference = 'Stop'
if ($StrictRelease -and $AllowMigrationOwners) {
    throw '-StrictRelease and -AllowMigrationOwners cannot be used together.'
}
$strictRelease = [bool]$StrictRelease

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Label"
    & $Action
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )

    Write-Host (">> {0} {1}" -f $FilePath, ($Arguments -join ' '))
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("Command failed with exit code {0}: {1} {2}" -f $LASTEXITCODE, $FilePath, ($Arguments -join ' '))
    }
}

function Test-WindowsRustToolchain {
    if (-not (Get-Command link.exe -CommandType Application -ErrorAction SilentlyContinue) -or
        -not (Get-Command cl.exe -CommandType Application -ErrorAction SilentlyContinue) -or
        -not (Get-Command rc.exe -CommandType Application -ErrorAction SilentlyContinue)) {
        return $false
    }
    $libraries = @($env:LIB -split ';' | Where-Object { $_ })
    foreach ($name in @('kernel32.lib', 'libcmt.lib', 'ucrt.lib')) {
        if (-not @($libraries | Where-Object { Test-Path -LiteralPath (Join-Path $_ $name) -PathType Leaf }).Count) {
            return $false
        }
    }
    return $true
}

function Import-VisualStudioToolchain {
    $installerRoots = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft Visual Studio\Installer\vswhere.exe')
    )
    foreach ($vswhere in $installerRoots) {
        if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) { continue }
        $installation = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
        if (-not $installation) { continue }
        $vcvars = Join-Path $installation 'VC\Auxiliary\Build\vcvars64.bat'
        if (-not (Test-Path -LiteralPath $vcvars -PathType Leaf)) { continue }
        # Use a raw cmd command line so PowerShell 5/7 native argument modes
        # cannot add another quote layer around Program Files paths. /u makes
        # the internal `set` output UTF-16, preserving Unicode environment values.
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $env:ComSpec
        $startInfo.Arguments = '/d /u /s /c call "{0}" >nul && set' -f $vcvars
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.StandardOutputEncoding = [Text.Encoding]::Unicode
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        try {
            [void]$process.Start()
            $outputTask = $process.StandardOutput.ReadToEndAsync()
            $errorTask = $process.StandardError.ReadToEndAsync()
            $process.WaitForExit()
            $environment = $outputTask.GetAwaiter().GetResult() -split '\r?\n'
            $errorOutput = $errorTask.GetAwaiter().GetResult()
            $exitCode = $process.ExitCode
        } finally {
            $process.Dispose()
        }
        if ($exitCode -ne 0) {
            Write-Warning "Visual Studio C++ environment initialization failed at $vcvars (exit $exitCode): $($errorOutput.Trim())"
            continue
        }
        foreach ($line in $environment) {
            if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
                [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
            }
        }
        if (Test-WindowsRustToolchain) {
            Write-Host "Using Visual Studio C++ tools from $installation"
            return $true
        }
    }
    return $false
}

function Import-PortableWindowsRustToolchain {
    $workspaceRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
    $portableRoot = Join-Path $workspaceRoot 'build\windows-toolchain'
    $portableVcRoot = Join-Path $portableRoot 'vc\Contents\VC\Tools\MSVC'
    $portableSdkRoot = Join-Path $portableRoot 'microsoft.windows.sdk.cpp\c\Include'
    $portableLibRoot = Join-Path $portableRoot 'microsoft.windows.sdk.cpp.x64\c'
    if ((Test-Path -LiteralPath $portableVcRoot) -and (Test-Path -LiteralPath $portableSdkRoot) -and (Test-Path -LiteralPath $portableLibRoot)) {
        $vcVersion = Get-ChildItem -LiteralPath $portableVcRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
        $sdkVersion = Get-ChildItem -LiteralPath $portableSdkRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
        if ($vcVersion -and $sdkVersion) {
            $vcBin = Join-Path $vcVersion.FullName 'bin\Hostx64\x64'
            $sdkBin = Join-Path $portableRoot ("microsoft.windows.sdk.buildtools\bin\{0}\x64" -f $sdkVersion.Name)
            $sdkLib = $portableLibRoot
            $libraries = @((Join-Path $vcVersion.FullName 'lib\x64'),(Join-Path $sdkLib 'um\x64'),(Join-Path $sdkLib 'ucrt\x64'))
            $required = @((Join-Path $vcBin 'link.exe'),(Join-Path $vcBin 'cl.exe'),(Join-Path $sdkBin 'rc.exe'),(Join-Path $libraries[0] 'libcmt.lib'),(Join-Path $libraries[1] 'kernel32.lib'),(Join-Path $libraries[2] 'ucrt.lib'))
            if (-not @($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count) {
                $env:PATH = "$vcBin;$sdkBin;$env:PATH"
                $env:LIB = (@($libraries + $env:LIB) | Where-Object { $_ }) -join ';'
                $env:INCLUDE = (@((Join-Path $vcVersion.FullName 'include'),(Join-Path $sdkVersion.FullName 'ucrt'),(Join-Path $sdkVersion.FullName 'um'),(Join-Path $sdkVersion.FullName 'shared'),$env:INCLUDE) | Where-Object { $_ }) -join ';'
                if (Test-WindowsRustToolchain) { Write-Host "Using portable Microsoft C++ tools from $portableRoot"; return $true }
            }
        }
    }
    foreach ($drive in Get-PSDrive -PSProvider FileSystem) {
        $vcRoot = Join-Path $drive.Root 'koi-msvc-tools-14.44\expanded\Contents\VC\Tools\MSVC'
        $sdkRoot = Join-Path $drive.Root 'koi-windows-sdk-buildtools-10.0.26100.7705\expanded\bin'
        $xwinRoot = Join-Path $drive.Root 'koi-xwin-sdk-4.0.0\splat'
        if (-not (Test-Path -LiteralPath $vcRoot) -or -not (Test-Path -LiteralPath $sdkRoot) -or -not (Test-Path -LiteralPath $xwinRoot)) {
            continue
        }
        $vcVersion = Get-ChildItem -LiteralPath $vcRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
        $sdkVersion = Get-ChildItem -LiteralPath $sdkRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $vcVersion -or -not $sdkVersion) { continue }
        $vcBin = Join-Path $vcVersion.FullName 'bin\Hostx64\x64'
        $sdkBin = Join-Path $sdkVersion.FullName 'x64'
        $crtLib = Join-Path $xwinRoot 'crt\lib\x86_64'
        $sdkUmLib = Join-Path $xwinRoot 'sdk\lib\um\x86_64'
        $sdkUcrtLib = Join-Path $xwinRoot 'sdk\lib\ucrt\x86_64'
        $required = @(
            (Join-Path $vcBin 'link.exe'), (Join-Path $sdkBin 'rc.exe'),
            (Join-Path $crtLib 'libcmt.lib'), (Join-Path $sdkUmLib 'kernel32.lib'),
            (Join-Path $sdkUcrtLib 'ucrt.lib')
        )
        if (@($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count) { continue }
        $env:PATH = "$vcBin;$sdkBin;$env:PATH"
        $env:LIB = (@($crtLib, $sdkUmLib, $sdkUcrtLib, $env:LIB) | Where-Object { $_ }) -join ';'
        $env:INCLUDE = (@(
            (Join-Path $xwinRoot 'crt\include'), (Join-Path $xwinRoot 'sdk\include\ucrt'),
            (Join-Path $xwinRoot 'sdk\include\um'), (Join-Path $xwinRoot 'sdk\include\shared'),
            $env:INCLUDE
        ) | Where-Object { $_ }) -join ';'
        if (Test-WindowsRustToolchain) {
            Write-Host "Using local MSVC and Windows SDK tools from $($drive.Root)"
            return $true
        }
    }
    return $false
}

function Initialize-WindowsRustToolchain {
    param([bool]$SkipInstall)
    if ($env:OS -ne 'Windows_NT' -or (Test-WindowsRustToolchain)) { return }
    if ((Import-VisualStudioToolchain) -or (Import-PortableWindowsRustToolchain)) { return }
    if ($SkipInstall) {
        throw 'MSVC C++ Build Tools and Windows SDK were not found. Rerun without -SkipInstall to install them.'
    }

    $installer = Join-Path ([System.IO.Path]::GetTempPath()) ("koi-vs_BuildTools-{0}.exe" -f [Guid]::NewGuid().ToString('N'))
    Write-Host 'Downloading official Visual Studio 2022 C++ Build Tools...'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://aka.ms/vs/17/release/vs_BuildTools.exe' -OutFile $installer
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft') {
        throw 'Downloaded Visual Studio Build Tools installer failed Microsoft signature verification.'
    }
    Write-Host 'Installing Visual Studio C++ Build Tools and Windows SDK...'
    $installOptions = @{
        FilePath = $installer
        ArgumentList = @(
            '--quiet', '--wait', '--norestart', '--nocache',
            '--add', 'Microsoft.VisualStudio.Workload.VCTools', '--includeRecommended'
        )
        PassThru = $true
        Wait = $true
        WindowStyle = 'Hidden'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        $installOptions.Verb = 'RunAs'
    }
    $process = Start-Process @installOptions
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "Visual Studio C++ Build Tools installation failed (exit $($process.ExitCode))."
    }
    if (-not (Import-VisualStudioToolchain) -and -not (Test-WindowsRustToolchain)) {
        throw 'Build Tools installer finished, but MSVC linker, Windows resource compiler, or libraries are still unavailable.'
    }
}

function New-CleanPortableData {
    param(
        [string]$ReleaseOutput
    )

    # The release tree may intentionally retain a user's existing data for a
    # local upgrade test. Never copy that state into a distributable archive:
    # config.json, DPAPI state, sessions, and checkpoints can contain secrets
    # or private paths. Build a clean sibling koi-data from immutable seeds;
    # the application will create/migrate user state on first launch.
    $stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("koi-portable-data-" + [Guid]::NewGuid().ToString("N"))
    $stagedData = Join-Path $stageRoot 'koi-data'
    New-Item -ItemType Directory -Force -Path $stagedData | Out-Null
    try {
        foreach ($name in @('Report_Template', 'templates', 'enterprise_classification.db')) {
            $source = Join-Path $ReleaseOutput ("seed\{0}" -f $name)
            if (-not (Test-Path -LiteralPath $source)) {
                throw "Immutable release seed is missing: $source"
            }
            Copy-Item -LiteralPath $source -Destination (Join-Path $stagedData $name) -Recurse -Force
        }
        return [PSCustomObject]@{ Root = $stageRoot; Data = $stagedData }
    }
    catch {
        if (Test-Path -LiteralPath $stageRoot) {
            Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Assert-CleanPortableArchive {
    param([string]$ArchivePath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $entries = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/').TrimStart('/') })
        foreach ($required in @('koi/koi.exe', 'koi-data/enterprise_classification.db')) {
            if ($entries -notcontains $required) {
                throw "Portable archive is missing required entry: $required"
            }
        }
        if (-not ($entries | Where-Object { $_ -like 'koi-data/Report_Template/*' })) {
            throw 'Portable archive is missing report-template seed entries'
        }
        if (-not ($entries | Where-Object { $_ -like 'koi-data/templates/*' })) {
            throw 'Portable archive is missing data-template seed entries'
        }
        $forbidden = @($entries | Where-Object {
            $_ -match '(?i)(^|/)(config\.json|secrets\.dpapi\.json|\.env(?:\.local)?|cookies(?:\.sqlite)?|local state|login data|web data|\.koi_agent_sessions|\.retest-control|\.koi-runtime|\.koi_notice_process_state\.json|\.koi-notice-tasks\.json|\.koi-batch-tasks\.json|\.koi-native-runtime\.json|aiqicha_browser_profile|tyc_browser_profile|ebwebview|webview2(?:-data)?|logs)(/|$)' -or
            $_ -match '(?i)(^|/)(koi-backend[^/]*|[^/]*pyinstaller[^/]*|__pycache__|[^/]+\.(py|pyc|pyo|log))$'
        })
        if ($forbidden.Count -gt 0) {
            throw "Portable archive contains private or legacy backend entries: $($forbidden -join ', ')"
        }
    }
    finally {
        $archive.Dispose()
    }
}

function New-PortableArchive {
    param(
        [string]$ReleaseOutput,
        [string]$PortableData,
        [string]$ReleaseManifest,
        [string]$PortableMarker,
        [string]$Destination
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $records = New-Object System.Collections.Generic.List[object]
    foreach ($tree in @(
        [PSCustomObject]@{ Root = $ReleaseOutput; Prefix = 'koi' },
        [PSCustomObject]@{ Root = $PortableData; Prefix = 'koi-data' }
    )) {
        $root = [System.IO.Path]::GetFullPath($tree.Root).TrimEnd('\')
        foreach ($file in @(Get-ChildItem -LiteralPath $root -Recurse -Force -File | Sort-Object FullName)) {
            if (($file.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Portable source contains a reparse-point file: $($file.FullName)"
            }
            $relative = $file.FullName.Substring($root.Length).TrimStart('\').Replace('\', '/')
            $records.Add([PSCustomObject]@{
                Source = $file.FullName
                Entry = "$($tree.Prefix)/$relative"
            })
        }
    }
    $records.Add([PSCustomObject]@{ Source = $ReleaseManifest; Entry = 'release-manifest.json' })
    $records.Add([PSCustomObject]@{ Source = $PortableMarker; Entry = 'koi-portable.marker' })

    $stream = [System.IO.File]::Open(
        $Destination,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        $archive = [System.IO.Compression.ZipArchive]::new(
            $stream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false
        )
        try {
            foreach ($record in $records) {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $archive,
                    $record.Source,
                    $record.Entry,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
        }
        finally {
            $archive.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Install-PortableNode {
    param(
        [string]$RepoRoot,
        [string]$Version
    )

    $nodePackage = "node-v$Version-win-x64"
    $toolsDir = Join-Path $RepoRoot '.build-tools'
    $nodeDir = Join-Path $toolsDir $nodePackage
    $npmCmd = Join-Path $nodeDir 'npm.cmd'

    if (Test-Path $npmCmd) {
        return $npmCmd
    }

    $archivePath = Join-Path $toolsDir "$nodePackage.zip"
    $downloadUrl = "https://nodejs.org/dist/v$Version/$nodePackage.zip"

    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null

    Invoke-Step "Downloading portable Node.js/npm $Version" {
        Write-Host (">> {0}" -f $downloadUrl)
        Invoke-WebRequest -Uri $downloadUrl -OutFile $archivePath -UseBasicParsing | Out-Null
    }

    Invoke-Step "Extracting portable Node.js/npm" {
        Expand-Archive -Path $archivePath -DestinationPath $toolsDir -Force | Out-Null
    }

    if (-not (Test-Path $npmCmd)) {
        throw "Portable Node.js download finished, but npm.cmd was not found: $npmCmd"
    }

    return $npmCmd
}

function Resolve-Npm {
    param(
        [string]$RepoRoot,
        [string]$Version
    )

    $npmCommand = Get-Command npm.cmd -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($npmCommand) {
        return $npmCommand.Source
    }

    $npmCommand = Get-Command npm -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($npmCommand) {
        return $npmCommand.Source
    }

    $portableNpm = Install-PortableNode -RepoRoot $RepoRoot -Version $Version
    return $portableNpm
}

function Get-UiDeclaredDependencies {
    param(
        [string]$PackageJsonPath
    )

    $package = Get-Content -Raw -Encoding UTF8 $PackageJsonPath | ConvertFrom-Json
    $names = New-Object System.Collections.Generic.List[string]
    foreach ($section in @('dependencies', 'devDependencies')) {
        if (-not $package.$section) {
            continue
        }
        foreach ($property in $package.$section.PSObject.Properties) {
            $names.Add($property.Name)
        }
    }
    return $names
}

function Test-NodePackageInstalled {
    param(
        [string]$NodeModules,
        [string]$PackageName
    )

    return Test-Path (Join-Path $NodeModules $PackageName)
}

function Ensure-UiDependencies {
    param(
        [string]$UiDir,
        [string]$Npm,
        [bool]$SkipInstall
    )

    $uiNodeModules = Join-Path $UiDir 'node_modules'
    $tauriCli = Join-Path $uiNodeModules '.bin\tauri.cmd'
    $packageJson = Join-Path $UiDir 'package.json'
    $missingDeclaredDependencies = @()
    if (Test-Path $uiNodeModules) {
        $missingDeclaredDependencies = @(Get-UiDeclaredDependencies -PackageJsonPath $packageJson | Where-Object {
            -not (Test-NodePackageInstalled -NodeModules $uiNodeModules -PackageName $_)
        })
    }
    $missingUiDependencies = -not (Test-Path $uiNodeModules) -or -not (Test-Path $tauriCli) -or $missingDeclaredDependencies.Count -gt 0

    if ($missingUiDependencies -and $SkipInstall) {
        $missingList = if ($missingDeclaredDependencies.Count -gt 0) { $missingDeclaredDependencies -join ', ' } else { 'node_modules or Tauri CLI' }
        throw "UI dependencies are incomplete: $missingList. Run build_release.cmd without -SkipInstall so npm ci can restore them."
    }

    if ($missingUiDependencies) {
        Invoke-Step "Installing UI dependencies" { Invoke-External $Npm @('ci', '--include=dev') }
    }

    if (-not (Test-Path $tauriCli)) {
        throw "Tauri CLI is still missing after npm ci: $tauriCli"
    }
}

$repoRoot = if ($PSScriptRoot) {
    (Resolve-Path $PSScriptRoot).Path
} else {
    (Get-Location).Path
}

$uiDir = Join-Path $repoRoot 'tauri-ui'
$packageJson = Join-Path $uiDir 'package.json'
$cargoToml = Join-Path $uiDir 'src-tauri\Cargo.toml'
if (-not (Test-Path $packageJson)) {
    throw "Missing tauri-ui/package.json: $packageJson"
}
if (-not (Test-Path $cargoToml)) {
    throw "Missing Rust package manifest: $cargoToml"
}

$cargoVersionText = Get-Content -Raw -Encoding UTF8 $cargoToml
if ($cargoVersionText -notmatch '(?m)^version\s*=\s*"([^\"]+)"') {
    throw "Unable to read Rust application version from $cargoToml"
}
$appVersion = $matches[1]
if ($appVersion -ne '4.0.0') {
    throw "Release builds are pinned to KOI 4.0.0; Cargo.toml contains $appVersion"
}

$npm = Resolve-Npm -RepoRoot $repoRoot -Version $NodeVersion
$npmDir = Split-Path -Parent $npm
$env:PATH = "$npmDir;$env:PATH"

$resolvedReleaseBase = ''
if ($ReleaseBase) {
    $resolvedReleaseBase = if ([System.IO.Path]::IsPathRooted($ReleaseBase)) {
        [System.IO.Path]::GetFullPath($ReleaseBase)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $repoRoot $ReleaseBase))
    }
    $env:KOI_RELEASE_BASE = $resolvedReleaseBase
} else {
    $resolvedReleaseBase = Join-Path $repoRoot 'dist-tauri\4.0.0'
    $env:KOI_RELEASE_BASE = $resolvedReleaseBase
}
if ($CargoTargetDir) {
    $resolvedCargoTargetDir = if ([System.IO.Path]::IsPathRooted($CargoTargetDir)) {
        [System.IO.Path]::GetFullPath($CargoTargetDir)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $repoRoot $CargoTargetDir))
    }
    $env:CARGO_TARGET_DIR = $resolvedCargoTargetDir
}

$cargoCommand = Get-Command cargo.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $cargoCommand) {
    $cargoCommand = Get-Command cargo -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
}
if (-not $cargoCommand) {
    throw "cargo not found on PATH. Install the Rust stable toolchain before building KOI."
}

if ($strictRelease) {
    $gitCommand = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $gitCommand) {
        $gitCommand = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $gitCommand) {
        throw "git is required to stamp the strict release with its source revision."
    }
    $revisionOutput = & $gitCommand.Source rev-parse --verify 'HEAD^{commit}' 2>$null
    $revisionExitCode = $LASTEXITCODE
    $revision = ([string]$revisionOutput).Trim()
    if ($revisionExitCode -ne 0 -or $revision -notmatch '^(?:[0-9a-f]{40}|[0-9a-f]{64})$') {
        throw "Unable to resolve the full Git source revision for the release."
    }
    $requestedRevision = if ($env:GITHUB_SHA) { $env:GITHUB_SHA } else { $env:KOI_SOURCE_REVISION }
    if ($requestedRevision -and $requestedRevision.ToLowerInvariant() -ne $revision.ToLowerInvariant()) {
        throw "Requested release revision $requestedRevision does not equal checkout HEAD $revision."
    }
    $env:KOI_SOURCE_REVISION = $revision
}

$env:KOI_EXPECTED_VERSION = $appVersion
$env:KOI_RELEASE_STRICT = if ($strictRelease) { '1' } else { '0' }
if (-not $strictRelease) {
    $env:KOI_SOURCE_REVISION = ''
    $env:GITHUB_SHA = ''
}

if (-not $SkipInstall) {
    Write-Host "Python dependencies are not installed: the production backend is compiled Rust."
}

if ($DryRun) {
    Write-Host "Dry run: Rust/Tauri release pipeline is configured."
    Write-Host ("Version: {0}" -f $appVersion)
    Write-Host ("Release base: {0}" -f $(if ($resolvedReleaseBase) { $resolvedReleaseBase } else { Join-Path $repoRoot 'dist-tauri\4.0.0' }))
    Write-Host ("NSIS: {0}" -f (-not $SkipNsis))
    Write-Host ("Strict Rust owner gate: {0}" -f $strictRelease)
    return
}

Initialize-WindowsRustToolchain -SkipInstall ([bool]$SkipInstall)

Push-Location $uiDir
try {
    Ensure-UiDependencies -UiDir $uiDir -Npm $npm -SkipInstall $SkipInstall

    if ($Verify) {
        Invoke-Step "Verifying backend contract" { Invoke-External $npm @('run', 'verify:backend-contract', '--', '--strict-rust') }
        Invoke-Step "Verifying 97-command behavior matrix" { Invoke-External $npm @('run', 'verify:behavior-matrix') }
    }

    Invoke-Step "Building Rust portable release" { Invoke-External $npm @('run', 'release:portable') }

    if (-not $SkipNsis) {
        Invoke-Step "Building per-user NSIS installer" { Invoke-External $npm @('run', 'release:nsis') }
    }

    Write-Host ""
    Write-Host "Done."
    $releaseRoot = if ($resolvedReleaseBase) { (Resolve-Path $resolvedReleaseBase).Path } else { Join-Path $repoRoot 'dist-tauri\4.0.0' }
    $releaseOutput = Join-Path $releaseRoot 'koi'
    $releaseData = Join-Path $releaseRoot 'koi-data'
    if (-not (Test-Path (Join-Path $releaseOutput 'koi.exe'))) {
        throw "Rust release executable is missing: $(Join-Path $releaseOutput 'koi.exe')"
    }
    if (-not (Test-Path $releaseData)) {
        throw "Portable user-data directory is missing: $releaseData"
    }

    $forbidden = @(Get-ChildItem -LiteralPath $releaseOutput -Recurse -Force -File -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match '(?i)^koi-backend|pyinstaller|\.py$'
    })
    if ($forbidden.Count -gt 0) {
        throw "Rust-only release contains forbidden Python artifacts: $($forbidden.FullName -join ', ')"
    }

    $portableArchive = Join-Path $releaseRoot ("koi-v{0}-windows-x64-portable.zip" -f $appVersion)
    if (Test-Path $portableArchive) {
        Remove-Item -LiteralPath $portableArchive -Force
    }
    $portableDataStage = New-CleanPortableData -ReleaseOutput $releaseOutput
    try {
        New-PortableArchive `
            -ReleaseOutput $releaseOutput `
            -PortableData $portableDataStage.Data `
            -ReleaseManifest (Join-Path $releaseRoot 'release-manifest.json') `
            -PortableMarker (Join-Path $releaseRoot 'koi-portable.marker') `
            -Destination $portableArchive
    }
    finally {
        if (Test-Path -LiteralPath $portableDataStage.Root) {
            Remove-Item -LiteralPath $portableDataStage.Root -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    Assert-CleanPortableArchive -ArchivePath $portableArchive
    $env:KOI_REQUIRE_NSIS = if ($SkipNsis) { '0' } else { '1' }
    Invoke-Step "Finalizing checksums and supply-chain manifest" { Invoke-External $npm @('run', 'finalize:release') }
    $env:KOI_REQUIRE_SUPPLY_CHAIN = '1'
    Invoke-Step "Verifying finalized release manifest" { Invoke-External $npm @('run', 'verify:release') }
    Write-Host ("Release output: {0}" -f $releaseOutput)
    Write-Host ("User data: {0}" -f $releaseData)
    Write-Host ("Portable archive: {0}" -f $portableArchive)
    if (-not $SkipNsis) {
        Write-Host ("NSIS installer: {0}" -f (Join-Path $releaseRoot ("koi-v{0}-windows-x64-setup.exe" -f $appVersion)))
    }
}
finally {
    Pop-Location
}
