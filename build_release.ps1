param(
    [switch]$SkipInstall = $false,
    [switch]$Verify = $false,
    [string]$NodeVersion = '22.16.0',
    [string]$ReleaseBase = '',
    [string]$CargoTargetDir = '',
    [switch]$SkipNsis = $false,
    [switch]$AllowMigrationOwners = $false,
    [switch]$DryRun = $false
)

$ErrorActionPreference = 'Stop'

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

    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npmCommand) {
        return $npmCommand.Source
    }

    $npmCommand = Get-Command npm -CommandType Application -ErrorAction SilentlyContinue
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
}
if ($CargoTargetDir) {
    $resolvedCargoTargetDir = if ([System.IO.Path]::IsPathRooted($CargoTargetDir)) {
        [System.IO.Path]::GetFullPath($CargoTargetDir)
    } else {
        [System.IO.Path]::GetFullPath((Join-Path $repoRoot $CargoTargetDir))
    }
    $env:CARGO_TARGET_DIR = $resolvedCargoTargetDir
}

$cargoCommand = Get-Command cargo.exe -ErrorAction SilentlyContinue
if (-not $cargoCommand) {
    $cargoCommand = Get-Command cargo -CommandType Application -ErrorAction SilentlyContinue
}
if (-not $cargoCommand) {
    throw "cargo not found on PATH. Install the Rust stable toolchain before building KOI."
}

$env:KOI_EXPECTED_VERSION = $appVersion
$env:KOI_RELEASE_STRICT = if ($AllowMigrationOwners) { '0' } else { '1' }

if (-not $SkipInstall) {
    Write-Host "Python dependencies are not installed: the production backend is compiled Rust."
}

if ($DryRun) {
    Write-Host "Dry run: Rust/Tauri release pipeline is configured."
    Write-Host ("Version: {0}" -f $appVersion)
    Write-Host ("Release base: {0}" -f $(if ($resolvedReleaseBase) { $resolvedReleaseBase } else { Join-Path $repoRoot 'dist-tauri\4.0.0' }))
    Write-Host ("NSIS: {0}" -f (-not $SkipNsis))
    Write-Host ("Strict Rust owner gate: {0}" -f (-not $AllowMigrationOwners))
    return
}

Push-Location $uiDir
try {
    Ensure-UiDependencies -UiDir $uiDir -Npm $npm -SkipInstall $SkipInstall

    if ($Verify) {
        Invoke-Step "Verifying backend contract" { Invoke-External $npm @('run', 'verify:backend-contract') }
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
    Compress-Archive -Path @($releaseOutput, $releaseData, (Join-Path $releaseRoot 'release-manifest.json'), (Join-Path $releaseRoot 'koi-portable.marker')) -DestinationPath $portableArchive -CompressionLevel Optimal
    $env:KOI_REQUIRE_NSIS = if ($SkipNsis) { '0' } else { '1' }
    Invoke-Step "Finalizing checksums and supply-chain manifest" { Invoke-External $npm @('run', 'finalize:release') }
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
