param(
    [string]$Tag = '',
    [string]$Branch = '',
    [switch]$DryRun = $false,
    [switch]$Force = $false,
    [switch]$CommitChanges = $true,
    [switch]$NoCommit = $false,
    [switch]$PreserveTag = $false,
    [switch]$UseProxy = $false,
    [string]$CommitMessage = ''
)

$ErrorActionPreference = 'Stop'
if ($Force -and $PreserveTag) {
    throw '-Force and -PreserveTag cannot be used together.'
}

function Invoke-Git {
    param([string[]]$GitArguments, [int[]]$SuccessCodes = @(0))
    $connectionOptions = @()
    $savedProxyEnvironment = @{}
    if (-not $UseProxy) {
        $connectionOptions = @('-c', 'http.proxy=', '-c', 'https.proxy=')
        $proxyKeys = @(& git config --name-only --get-regexp '^(http|https)\..*\.proxy$')
        if ($LASTEXITCODE -notin @(0, 1)) { throw 'Unable to read Git proxy configuration.' }
        foreach ($key in $proxyKeys) { $connectionOptions += @('-c', "$key=") }
        foreach ($name in @('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')) {
            $savedProxyEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
            [Environment]::SetEnvironmentVariable($name, $null, 'Process')
        }
    }
    try {
        & git @connectionOptions @GitArguments
        $gitExitCode = $LASTEXITCODE
        if ($gitExitCode -notin $SuccessCodes) {
            throw "git $($GitArguments -join ' ') failed (exit $gitExitCode). Release push stopped."
        }
    } finally {
        foreach ($name in $savedProxyEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedProxyEnvironment[$name], 'Process') }
    }
}

function Invoke-ReleaseSourceChecks {
    $checks = @('tauri-ui/scripts/verify-backend-contract.mjs', 'tauri-ui/scripts/verify-behavior-matrix.mjs')
    $node = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    foreach ($check in $checks) {
        if (-not (Test-Path -LiteralPath $check)) { continue }
        if (-not $node) { throw 'Node.js is required to verify the release source before pushing.' }
        $arguments = @($check)
        if ($check -like '*verify-backend-contract*') { $arguments += '--strict-rust' }
        & $node.Source @arguments
        if ($LASTEXITCODE -ne 0) { throw "Release source check failed: $check. No commit or tag was changed." }
    }
    if ((Test-Path -LiteralPath 'tauri-ui/src-tauri/src') -and (Get-Command cargo -ErrorAction SilentlyContinue)) {
        & cargo fmt --manifest-path 'tauri-ui/src-tauri/Cargo.toml' --all -- --check
        if ($LASTEXITCODE -ne 0) { throw 'Rust formatting check failed. Run cargo fmt before publishing. No commit or tag was changed.' }
    }
}

function Get-RemoteRefs {
    param([string]$BranchName, [string]$TagName)
    $refs = @{}
    $lines = @(Invoke-Git -GitArguments @('ls-remote', 'origin', "refs/heads/$BranchName", "refs/tags/$TagName", "refs/tags/$TagName^{}"))
    foreach ($line in $lines) {
        $fields = "$line" -split '\s+', 2
        if ($fields.Count -eq 2) { $refs[$fields[1]] = $fields[0] }
    }
    return $refs
}

$repoRoot = (Invoke-Git -GitArguments @('-C', $PSScriptRoot, 'rev-parse', '--show-toplevel') | Out-String).Trim()
Push-Location $repoRoot
try {
    $cargo = Get-Content -LiteralPath 'tauri-ui/src-tauri/Cargo.toml' -Raw -Encoding UTF8
    if ($cargo -notmatch '(?m)^version\s*=\s*"([^\"]+)"') {
        throw 'Version not found in tauri-ui/src-tauri/Cargo.toml.'
    }
    $expectedTag = "v$($matches[1])"
    $tagValue = if ($Tag.Trim()) { $Tag.Trim() } else { $expectedTag }
    if ($tagValue -ne $expectedTag) { throw "Release tag must match the application version: $expectedTag" }
    $tagRef = "refs/tags/$tagValue"
    Invoke-Git -GitArguments @('check-ref-format', $tagRef) | Out-Null
    $currentBranch = (Invoke-Git -GitArguments @('branch', '--show-current') | Out-String).Trim()
    $branchValue = if ($Branch.Trim()) { $Branch.Trim() } else { $currentBranch }
    if (-not $currentBranch -or $currentBranch -ne $branchValue) {
        throw 'Check out the branch to publish before running this script.'
    }
    Invoke-Git -GitArguments @('check-ref-format', '--branch', $branchValue) | Out-Null
    if (-not (Test-Path -LiteralPath '.github/workflows/release.yml')) { throw 'Release workflow is missing.' }

    $changes = @(Invoke-Git -GitArguments @('status', '--porcelain=v1', '--untracked-files=all'))
    if ($changes.Count -and ($NoCommit -or -not $CommitChanges)) {
        Write-Host ($changes -join [Environment]::NewLine)
        throw 'Uncommitted release changes exist and auto-commit was disabled. No files were staged or committed.'
    }
    if ($DryRun) {
        $proxyMode = if ($UseProxy) { 'configured Git proxy' } else { 'direct connection without Git HTTP proxy' }
        Write-Host ">> git ls-remote origin refs/heads/$branchValue $tagRef ($proxyMode)"
        if ($changes.Count) {
            Write-Host '>> verify backend contract, behavior matrix, and available Rust formatting before commit'
            Write-Host '>> git add --all'
            Write-Host '>> git commit (all reviewed, non-ignored changes)'
        }
        if ($PreserveTag) {
            Write-Host ">> git push --atomic origin HEAD:refs/heads/$branchValue (existing tag unchanged)"
        } else {
            Write-Host ">> git tag (create/update local $tagValue only after remote preflight)"
            Write-Host ">> git push --atomic origin HEAD:refs/heads/$branchValue $tagRef (existing tag uses an exact lease)"
        }
        Write-Host 'Dry run complete. No commit, tag, or remote reference was changed.'
        return
    }

    Invoke-ReleaseSourceChecks

    # Connectivity and tag ownership must be known before committing or moving a local tag.
    $proxyMode = if ($UseProxy) { 'using configured Git proxy' } else { 'without Git HTTP proxy' }
    Write-Host ">> Checking remote connectivity and references $proxyMode"
    $remote = Get-RemoteRefs -BranchName $branchValue -TagName $tagValue
    $remoteTagObject = $remote[$tagRef]
    $remoteTagCommit = if ($remote.ContainsKey("$tagRef^{}")) { $remote["$tagRef^{}"] } else { $remoteTagObject }
    $publishTag = -not $PreserveTag
    if ($remoteTagObject -and $publishTag) {
        Write-Host "Updating release tag $tagValue from $remoteTagCommit with an exact lease."
    }
    if ($changes.Count) {
        $message = if ($CommitMessage.Trim()) { $CommitMessage.Trim() } else { "chore: prepare release $tagValue" }
        Invoke-Git -GitArguments @('add', '--all')
        Invoke-Git -GitArguments @('commit', '-m', $message)
    }
    if (@(Invoke-Git -GitArguments @('status', '--porcelain=v1', '--untracked-files=all')).Count) {
        throw 'Release source changed during preparation. Commit the remaining changes before publishing.'
    }
    $headCommit = (Invoke-Git -GitArguments @('rev-parse', '--verify', 'HEAD^{commit}') | Out-String).Trim()
    $localTagObject = ''
    $localTagChanged = $false
    if ($publishTag) {
        if (@(Invoke-Git -GitArguments @('tag', '--list', $tagValue)).Count) {
            $localTagObject = (Invoke-Git -GitArguments @('rev-parse', $tagRef) | Out-String).Trim()
        }
        if (-not $localTagObject) {
            Invoke-Git -GitArguments @('tag', $tagValue, $headCommit)
            $localTagChanged = $true
        } elseif ((Invoke-Git -GitArguments @('rev-list', '-n', '1', $tagValue) | Out-String).Trim() -ne $headCommit) {
            Invoke-Git -GitArguments @('tag', '-f', $tagValue, $headCommit)
            $localTagChanged = $true
        }
    }

    $pushArguments = @('push', '--atomic')
    if ($publishTag -and $remoteTagObject) {
        $localTagNow = (Invoke-Git -GitArguments @('rev-parse', $tagRef) | Out-String).Trim()
        if ($localTagNow -ne $remoteTagObject) {
            $pushArguments += "--force-with-lease=" + $tagRef + ':' + $remoteTagObject
        }
    }
    $pushArguments += @('origin', "HEAD:refs/heads/$branchValue")
    if ($publishTag) { $pushArguments += ($tagRef + ':' + $tagRef) }
    Write-Host ">> git $($pushArguments -join ' ')"
    try {
        Invoke-Git -GitArguments $pushArguments
    } catch {
        $pushError = $_
        if ($localTagChanged) {
            if ($localTagObject) { Invoke-Git -GitArguments @('update-ref', $tagRef, $localTagObject) }
            else { Invoke-Git -GitArguments @('tag', '-d', $tagValue) }
        }
        throw $pushError
    }

    $verified = Get-RemoteRefs -BranchName $branchValue -TagName $tagValue
    $verifiedTagCommit = if ($verified.ContainsKey("$tagRef^{}")) { $verified["$tagRef^{}"] } else { $verified[$tagRef] }
    if ($verified["refs/heads/$branchValue"] -ne $headCommit -or
        ($publishTag -and $verifiedTagCommit -ne $headCommit) -or
        (-not $publishTag -and $verifiedTagCommit -ne $remoteTagCommit)) {
        throw 'Remote verification did not match the submitted references. Inspect the branch and tag before retrying.'
    }
    if ($publishTag) {
        Write-Host "Source and release tag verified on origin: $headCommit ($branchValue, $tagValue)."
        if ($remoteTagCommit -eq $headCommit) { Write-Host 'Tag already referenced this commit; this run does not trigger another tag build.' }
        else { Write-Host 'Release tag pushed. Check GitHub Actions for build and publication status; a successful push is not a successful build.' }
    } else {
        Write-Host "Source branch verified on origin: $headCommit ($branchValue). Existing release tag $tagValue remains at $remoteTagCommit."
        Write-Host 'A push to main triggers the GitHub Actions build; branch-only pushes do not publish a GitHub release.'
    }
} finally {
    Pop-Location
}
