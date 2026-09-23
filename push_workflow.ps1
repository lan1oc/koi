param(
    [string]$Tag = '',
    [string]$Branch = '',
    [switch]$DryRun = $false,
    [switch]$Force = $false,
    [switch]$CommitChanges = $false,
    [string]$CommitMessage = ''
)

$ErrorActionPreference = 'Stop'

function Invoke-Git {
    param([string[]]$GitArguments, [int[]]$SuccessCodes = @(0))
    & git @GitArguments
    if ($LASTEXITCODE -notin $SuccessCodes) {
        throw "git $($GitArguments -join ' ') failed (exit $LASTEXITCODE). Release push stopped."
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
    if ($changes.Count -and -not $CommitChanges) {
        Write-Host ($changes -join [Environment]::NewLine)
        throw 'Uncommitted release changes exist. Review and commit them first, or pass -CommitChanges -CommitMessage "..." to include all non-ignored changes. No files were staged or committed.'
    }
    if ($DryRun) {
        Write-Host ">> git ls-remote origin refs/heads/$branchValue $tagRef"
        if ($changes.Count) {
            Write-Host '>> git add --all'
            Write-Host '>> git commit (all reviewed, non-ignored changes)'
        }
        Write-Host ">> git tag (create/update local $tagValue only after remote preflight)"
        Write-Host ">> git push --atomic origin HEAD:refs/heads/$branchValue $tagRef"
        Write-Host 'Dry run complete. No commit, tag, or remote reference was changed.'
        return
    }

    # A broken proxy must fail before committing or moving the local tag.
    Write-Host '>> Checking remote connectivity and references'
    $remote = Get-RemoteRefs -BranchName $branchValue -TagName $tagValue
    $headBeforeCommit = (Invoke-Git -GitArguments @('rev-parse', 'HEAD') | Out-String).Trim()
    $remoteTagObject = $remote[$tagRef]
    $remoteTagCommit = if ($remote.ContainsKey("$tagRef^{}")) { $remote["$tagRef^{}"] } else { $remoteTagObject }
    if ($remoteTagObject -and ($changes.Count -or $remoteTagCommit -ne $headBeforeCommit) -and -not $Force) {
        throw "Remote tag $tagValue already exists at $remoteTagCommit. Use -Force only when intentionally replacing this release; the update will use an exact lease."
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
    if (@(Invoke-Git -GitArguments @('tag', '--list', $tagValue)).Count) {
        $localTagObject = (Invoke-Git -GitArguments @('rev-parse', $tagRef) | Out-String).Trim()
    }
    $localTagChanged = $false
    if (-not $localTagObject) {
        Invoke-Git -GitArguments @('tag', $tagValue, $headCommit)
        $localTagChanged = $true
    } elseif ((Invoke-Git -GitArguments @('rev-list', '-n', '1', $tagValue) | Out-String).Trim() -ne $headCommit) {
        Invoke-Git -GitArguments @('tag', '-f', $tagValue, $headCommit)
        $localTagChanged = $true
    }

    $pushArguments = @('push', '--atomic')
    if ($remoteTagObject) {
        $localTagNow = (Invoke-Git -GitArguments @('rev-parse', $tagRef) | Out-String).Trim()
        if ($localTagNow -ne $remoteTagObject) {
            if (-not $Force) { throw "Remote tag $tagValue has a different tag object; pass -Force for an intentional update." }
            $pushArguments += "--force-with-lease=" + $tagRef + ':' + $remoteTagObject
        }
    }
    $pushArguments += @('origin', "HEAD:refs/heads/$branchValue", ($tagRef + ':' + $tagRef))
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
    if ($verified["refs/heads/$branchValue"] -ne $headCommit -or $verifiedTagCommit -ne $headCommit) {
        throw 'Remote verification did not match the submitted commit. Inspect the branch and tag before retrying.'
    }
    Write-Host "Source and release tag verified on origin: $headCommit ($branchValue, $tagValue)."
    if ($remoteTagCommit -eq $headCommit) { Write-Host 'Tag already referenced this commit; this run does not trigger another tag build.' }
    else { Write-Host 'Release tag pushed. Check GitHub Actions for build and publication status; a successful push is not a successful build.' }
} finally {
    Pop-Location
}
