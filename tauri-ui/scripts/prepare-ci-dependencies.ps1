param(
    [string]$RepositoryRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [Parameter(Mandatory = $true)][string]$CacheDirectory,
    [switch]$RuntimeOnly = $false
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$CacheDirectory = [IO.Path]::GetFullPath($CacheDirectory)
New-Item -ItemType Directory -Force -Path $CacheDirectory | Out-Null

function Invoke-CiDownload {
    param([string]$Url, [string]$Destination, [hashtable]$Headers = @{}, [int]$TimeoutSeconds = 120)
    $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $curl) { throw 'Windows curl.exe is required for bounded CI dependency downloads.' }
    $downloadArguments = @('--fail', '--location', '--silent', '--show-error', '--connect-timeout', '20', '--max-time', [string]$TimeoutSeconds, '--user-agent', 'KOI-CI-dependencies', '--output', $Destination)
    foreach ($name in $Headers.Keys) { $downloadArguments += @('--header', "$name`: $($Headers[$name])") }
    $downloadArguments += @('--url', $Url)
    & $curl.Source @downloadArguments
    if ($LASTEXITCODE -ne 0) { throw "Dependency request failed with curl exit $LASTEXITCODE (total timeout $TimeoutSeconds seconds)." }
}

function Get-LockedArtifact {
    param([string]$Url, [string]$Sha256, [string]$Name)
    $destination = Join-Path $CacheDirectory $Name
    if ((Test-Path -LiteralPath $destination -PathType Leaf) -and (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -eq $Sha256) { return $destination }
    $download = "$destination.download"
    $apiAssetUrl = $null
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            Write-Host "Downloading locked $Name (attempt $attempt/4)"
            if ($attempt -ge 2 -and $Url -match '^https://github\.com/([^/]+)/([^/]+)/releases/download/(.+)/([^/]+)$') {
                if (-not $apiAssetUrl) {
                    $owner = $matches[1]; $repository = $matches[2]; $tag = [Uri]::EscapeDataString($matches[3]); $assetName = [Uri]::UnescapeDataString($matches[4])
                    $releaseUrl = "https://api.github.com/repos/$owner/$repository/releases/tags/$tag"
                    $metadataFile = "$destination.metadata.json"
                    try {
                        Invoke-CiDownload $releaseUrl $metadataFile @{ Accept = 'application/vnd.github+json' } 60
                        $metadata = Get-Content -LiteralPath $metadataFile -Raw | ConvertFrom-Json
                    } finally {
                        if (Test-Path -LiteralPath $metadataFile) { Remove-Item -LiteralPath $metadataFile -Force }
                    }
                    $asset = @($metadata.assets | Where-Object { $_.name -eq $assetName })
                    if ($asset.Count -ne 1) { throw "Official GitHub release asset is missing: $assetName" }
                    $apiAssetUrl = $asset[0].url
                }
                Write-Host "Using official GitHub asset API for $Name"
                Invoke-CiDownload $apiAssetUrl $download @{ Accept = 'application/octet-stream'; 'X-GitHub-Api-Version' = '2022-11-28' }
            } else {
                Invoke-CiDownload $Url $download
            }
            $actual = (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash
            if ($actual -ne $Sha256) { throw "Downloaded artifact hash mismatch: $Name" }
            Move-Item -LiteralPath $download -Destination $destination -Force
            return $destination
        } catch {
            Write-Host "Download attempt $attempt failed for $Name`: $($_.Exception.Message)"
            if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download -Force }
            if ($attempt -eq 4 -or $_.Exception.Message -like '*hash mismatch*') { throw }
            Start-Sleep -Seconds ([Math]::Min(8, 2 * $attempt))
        }
    }
}

function Test-LockedFiles {
    param([string]$Directory, $Records, [string]$Prefix = '')
    foreach ($record in $Records) {
        $relative = ([string]$record.path).Replace('\', '/')
        if ($Prefix) { $relative = $relative.Substring($Prefix.Length) }
        $file = Join-Path $Directory $relative
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $record.sha256) { return $false }
    }
    return $true
}

function Copy-LockedEntry {
    param([IO.Compression.ZipArchive]$Zip, [string]$Name, [string]$Destination, [string]$Sha256)
    $entry = @($Zip.Entries | Where-Object { $_.FullName.Replace('\', '/').TrimStart('/') -eq $Name })
    if ($entry.Count -ne 1) { throw "Locked archive entry missing or ambiguous: $Name" }
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = "$Destination.download"
    $input = $entry[0].Open()
    $output = [IO.File]::Create($temporary)
    try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
    if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -ne $Sha256) { Remove-Item -LiteralPath $temporary -Force; throw "Locked entry hash mismatch: $Name" }
    Move-Item -LiteralPath $temporary -Destination $Destination -Force
}

$probe = Get-Content -LiteralPath (Join-Path $RepositoryRoot 'probe-runtime.lock.json') -Raw | ConvertFrom-Json
$probeRoot = Join-Path $RepositoryRoot 'probe-runtime'
if (-not (Test-LockedFiles $probeRoot $probe.files 'probe-runtime/')) {
    Write-Host 'Restoring missing CPython probe runtime from its locked official archive.'
    $archive = Get-LockedArtifact $probe.url $probe.sha256 "python-$($probe.version)-embed-amd64.zip"
    $zip = [IO.Compression.ZipFile]::OpenRead($archive)
    try { foreach ($record in $probe.files) { Copy-LockedEntry $zip ([string]$record.path).Substring('probe-runtime/'.Length) (Join-Path $RepositoryRoot $record.path) $record.sha256 } } finally { $zip.Dispose() }
}

$pdfium = Get-Content -LiteralPath (Join-Path $RepositoryRoot 'pdfium-runtime.lock.json') -Raw | ConvertFrom-Json
$pdfiumRoot = Join-Path $RepositoryRoot 'pdfium-runtime'
if (-not (Test-LockedFiles $pdfiumRoot $pdfium.files)) {
    Write-Host 'Restoring missing PDFium runtime from its locked upstream binary archive.'
    $archive = Get-LockedArtifact $pdfium.source.archive_url $pdfium.source.archive_sha256 'pdfium-win-x64.tgz'
    $stage = Join-Path $CacheDirectory ('pdfium-extract-' + [Guid]::NewGuid().ToString('N'))
    $stage = [IO.Path]::GetFullPath($stage)
    if (-not $stage.StartsWith($CacheDirectory.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'PDFium staging path is outside its download cache.' }
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        & tar.exe -xzf $archive -C $stage
        if ($LASTEXITCODE -ne 0) { throw 'PDFium archive extraction failed.' }
        foreach ($record in $pdfium.files) {
            $candidates = @(Get-ChildItem -LiteralPath $stage -File -Recurse | Where-Object { $_.Name -eq (Split-Path -Leaf $record.path) -and (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash -eq $record.sha256 })
            if ($candidates.Count -ne 1) { throw "PDFium locked entry missing or ambiguous: $($record.path)" }
            $destination = Join-Path $pdfiumRoot $record.path
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
            Copy-Item -LiteralPath $candidates[0].FullName -Destination $destination -Force
        }
    } finally { Remove-Item -LiteralPath $stage -Recurse -Force }
}

$archiveLock = Get-Content -LiteralPath (Join-Path $RepositoryRoot 'archive-runtime.lock.json') -Raw | ConvertFrom-Json
$archiveRoot = Join-Path $RepositoryRoot 'archive-runtime'
if (-not (Test-LockedFiles $archiveRoot $archiveLock.files)) {
    Write-Host 'Restoring missing NanaZip runtime from its locked signed package.'
    $bundle = Get-LockedArtifact $archiveLock.source.release_asset_url $archiveLock.source.release_asset_sha256 $archiveLock.source.release_asset
    $package = Join-Path $archiveRoot $archiveLock.source.signed_package
    $zip = [IO.Compression.ZipFile]::OpenRead($bundle)
    try { Copy-LockedEntry $zip $archiveLock.source.signed_package $package $archiveLock.source.signed_package_sha256 } finally { $zip.Dispose() }
    $zip = [IO.Compression.ZipFile]::OpenRead($package)
    try {
        foreach ($record in $archiveLock.files | Where-Object { $_.role -ne 'publisher-signed-package' -and $_.role -ne 'license' }) { Copy-LockedEntry $zip $record.path (Join-Path $archiveRoot $record.path) $record.sha256 }
    } finally { $zip.Dispose() }
    $licenses = Get-LockedArtifact $archiveLock.source.license_asset_url $archiveLock.source.license_asset_sha256 $archiveLock.source.license_asset
    $zip = [IO.Compression.ZipFile]::OpenRead($licenses)
    try {
        foreach ($record in $archiveLock.files | Where-Object { $_.role -eq 'license' }) {
            $entries = @($zip.Entries | Where-Object { [IO.Path]::GetFileName($_.FullName) -eq $record.path })
            if ($entries.Count -ne 1) { throw "Archive license entry missing or ambiguous: $($record.path)" }
            Copy-LockedEntry $zip $entries[0].FullName (Join-Path $archiveRoot $record.path) $record.sha256
        }
    } finally { $zip.Dispose() }
}
foreach ($entry in @(@($probeRoot, $probe.files, 'probe-runtime/'), @($pdfiumRoot, $pdfium.files, ''), @($archiveRoot, $archiveLock.files, ''))) {
    if (-not (Test-LockedFiles $entry[0] $entry[1] $entry[2])) { throw "Runtime verification failed: $($entry[0])" }
}

if (-not $RuntimeOnly) {
    $tools = Get-Content -LiteralPath (Join-Path $RepositoryRoot 'tauri-ui/src-tauri/src/backend/external_tools.lock.json') -Raw | ConvertFrom-Json
    foreach ($tool in $tools.artifacts) {
        $assetName = [IO.Path]::GetFileName(([Uri]$tool.url).AbsolutePath)
        $asset = Get-LockedArtifact $tool.url $tool.sha256 $assetName
        $name = 'KOI_AUDIT_' + $tool.tool.ToUpperInvariant() + '_ARCHIVE'
        [Environment]::SetEnvironmentVariable($name, $asset, 'Process')
        if ($env:GITHUB_ENV) { "$name=$asset" | Out-File -LiteralPath $env:GITHUB_ENV -Append -Encoding utf8 }
    }
}
Write-Host 'CI runtime dependencies are present and match their locked hashes.'
