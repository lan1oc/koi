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

    $cargoPath = Join-Path $repoRoot "tauri-ui/src-tauri/Cargo.toml"
    if (Test-Path $cargoPath) {
        $content = Get-Content $cargoPath -Raw -Encoding UTF8
        if ($content -match '(?m)^version\s*=\s*"([^"]+)"') {
            $ver = $matches[1]
            if ($ver.StartsWith("v")) {
                return $ver
            }
            return "v$ver"
        }
    }

    throw "Version not found in tauri-ui/src-tauri/Cargo.toml. Please pass -Tag explicitly."
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
$localTagCommit = ""
$matchedTag = (git tag -l $tagValue | Out-String).Trim()
if ($matchedTag -eq $tagValue) {
    $hasTagLocal = $true
    $localTagCommit = (git rev-list -n 1 $tagValue | Out-String).Trim()
}

if ($hasTagLocal) {
    Write-Host ">> Found local tag $tagValue at $localTagCommit"
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
$headCommit = (git rev-parse HEAD | Out-String).Trim()
$hasTagLocal = $false
$localTagCommit = ""
$matchedTag = (git tag -l $tagValue | Out-String).Trim()
if ($matchedTag -eq $tagValue) {
    $hasTagLocal = $true
    $localTagCommit = (git rev-list -n 1 $tagValue | Out-String).Trim()
}

if ($hasTagLocal) {
    if ($localTagCommit -eq $headCommit) {
        Write-Host ">> Reuse local tag $tagValue at HEAD"
    } else {
        Write-Host ">> Move local tag $tagValue from $localTagCommit to $headCommit"
        Invoke-StepCommand "git tag -f $tagValue HEAD" -dryRun:$DryRun
    }
} else {
    Invoke-StepCommand "git tag $tagValue HEAD" -dryRun:$DryRun
}

$remoteTagCommit = ""
if ($DryRun) {
    Write-Host ">> git ls-remote --tags origin refs/tags/$tagValue"
} else {
    $remoteTagLine = (git ls-remote --tags origin "refs/tags/$tagValue" | Select-Object -First 1 | Out-String).Trim()
    if ($remoteTagLine) {
        $remoteTagCommit = ($remoteTagLine -split "\s+")[0]
    }
}

if ($Force -and $remoteTagCommit) {
    Invoke-StepCommand "git push origin :refs/tags/$tagValue" -dryRun:$DryRun
    Invoke-StepCommand "git push origin refs/tags/$tagValue" -dryRun:$DryRun
} elseif ($remoteTagCommit -and $remoteTagCommit -ne $headCommit) {
    Write-Host ">> Update remote tag $tagValue from $remoteTagCommit to $headCommit"
    Invoke-StepCommand "git push --force-with-lease=refs/tags/${tagValue}:$remoteTagCommit origin refs/tags/$tagValue" -dryRun:$DryRun
} elseif ($remoteTagCommit -eq $headCommit) {
    Write-Host ">> Remote tag $tagValue already points to HEAD; skip tag push"
} else {
    Invoke-StepCommand "git push origin refs/tags/$tagValue" -dryRun:$DryRun
}

Write-Host ""
Write-Host "Done. Release workflow triggered with tag: $tagValue"
