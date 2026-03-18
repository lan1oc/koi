param(
    [string]$Tag = "",
    [string]$Branch = "",
    [switch]$DryRun = $false,
    [switch]$Force = $false
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir) {
        $scriptDir = (Get-Location).Path
    }
    try {
        $gitRoot = (git -C $scriptDir rev-parse --show-toplevel 2>$null | Out-String).Trim()
        if ($gitRoot) {
            return (Resolve-Path $gitRoot).Path
        }
    } catch {
    }
    if (Test-Path (Join-Path $scriptDir ".github\workflows\release.yml")) {
        return (Resolve-Path $scriptDir).Path
    }
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Resolve-Tag([string]$repoRoot, [string]$inputTag) {
    if ($inputTag -and $inputTag.Trim()) {
        return $inputTag.Trim()
    }
    $configPath = Join-Path $repoRoot "./config.json"
    if (-not (Test-Path $configPath)) {
        throw "config.json not found. Please pass -Tag explicitly."
    }
    $cfg = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $ver = ""
    if ($cfg.app -and $cfg.app.version) {
        $ver = [string]$cfg.app.version
    }
    if (-not $ver) {
        throw "app.version not found in config.json. Please pass -Tag explicitly."
    }
    if ($ver.StartsWith("v")) {
        return $ver
    }
    return "v$ver"
}

function Invoke-StepCommand([string]$cmd, [switch]$dryRun) {
    Write-Host ">> $cmd"
    if (-not $dryRun) {
        Invoke-Expression $cmd
    }
}

$repoRoot = Resolve-RepoRoot
Set-Location $repoRoot

$tagValue = Resolve-Tag -repoRoot $repoRoot -inputTag $Tag
$branchValue = $Branch
if (-not $branchValue) {
    $branchValue = (git rev-parse --abbrev-ref HEAD).Trim()
}
if (-not $branchValue -or $branchValue -eq "HEAD") {
    throw "Cannot detect current branch. Please pass -Branch."
}

$workflowPath = Join-Path $repoRoot ".github\workflows\release.yml"
if (-not (Test-Path $workflowPath)) {
    throw "Release workflow file not found: $workflowPath"
}

git --version | Out-Null
git rev-parse --is-inside-work-tree | Out-Null

$hasTagLocal = $false
$matchedTag = (git tag -l $tagValue | Out-String).Trim()
if ($matchedTag -eq $tagValue) {
    $hasTagLocal = $true
}

if ($hasTagLocal -and -not $Force) {
    throw "Local tag $tagValue already exists. Use -Force to overwrite."
}

if ($hasTagLocal -and $Force) {
    Invoke-StepCommand "git tag -d $tagValue" -dryRun:$DryRun
}

if ($Force) {
    Invoke-StepCommand "git push origin :refs/tags/$tagValue" -dryRun:$DryRun
}

Invoke-StepCommand "git add .github/workflows/release.yml" -dryRun:$DryRun
if ($DryRun) {
    Write-Host ">> git commit -m ""chore: trigger release $tagValue"""
    Write-Host ">> git push origin $branchValue"
} else {
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        Invoke-StepCommand "git commit -m ""chore: trigger release $tagValue""" -dryRun:$DryRun
        Invoke-StepCommand "git push origin $branchValue" -dryRun:$DryRun
    } else {
        Write-Host ">> Skip commit: release.yml has no changes"
    }
}
Invoke-StepCommand "git tag $tagValue" -dryRun:$DryRun
if ($Force) {
    Invoke-StepCommand "git push origin $tagValue --force" -dryRun:$DryRun
} else {
    Invoke-StepCommand "git push origin $tagValue" -dryRun:$DryRun
}

Write-Host ""
Write-Host "Done. Release workflow triggered with tag: $tagValue"
