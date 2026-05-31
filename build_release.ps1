param(
    [switch]$SkipInstall = $false,
    [switch]$Verify = $false
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

$repoRoot = if ($PSScriptRoot) {
    (Resolve-Path $PSScriptRoot).Path
} else {
    (Get-Location).Path
}

$uiDir = Join-Path $repoRoot 'tauri-ui'
$packageJson = Join-Path $uiDir 'package.json'
if (-not (Test-Path $packageJson)) {
    throw "Missing tauri-ui/package.json: $packageJson"
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
}
if (-not $npmCommand) {
    throw "npm not found on PATH."
}
$npm = $npmCommand.Source

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "python not found on PATH."
}
$python = $pythonCommand.Source

if (-not $SkipInstall) {
    Invoke-Step "Installing Python backend dependencies" { Invoke-External $python @('-m', 'pip', 'install', '-r', (Join-Path $repoRoot 'requirements.txt')) }
}

Push-Location $uiDir
try {
    if (-not $SkipInstall -and -not (Test-Path (Join-Path $uiDir 'node_modules'))) {
        Invoke-Step "Installing UI dependencies" { Invoke-External $npm @('ci') }
    }

    if ($Verify) {
        Invoke-Step "Verifying backend contract" { Invoke-External $npm @('run', 'verify:backend-contract') }
    }

    Invoke-Step "Building full release" { Invoke-External $npm @('run', 'release:flat') }

    Write-Host ""
    Write-Host "Done."
    Write-Host ("Release output: {0}" -f (Join-Path $repoRoot 'dist-tauri\koi'))
    Write-Host ("User data: {0}" -f (Join-Path $repoRoot 'dist-tauri\koi-data'))
}
finally {
    Pop-Location
}
