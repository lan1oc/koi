param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$DataDirectory,
    [string]$ExpectedVersion = '4.0.0',
    [string]$ReportPath = ''
)
$ErrorActionPreference = 'Stop'
function Assert-PackagedSelfTest {
    param([int]$ExitCode, [string]$Output, [string]$Version)
    if ($ExitCode -ne 0) { throw "Packaged self-test failed with exit code $ExitCode" }
    if (-not $Output.Trim()) { throw 'Packaged self-test did not return a result.' }
    $result = $Output.Trim() | ConvertFrom-Json
    if ($result.ok -ne $true -or $result.version -ne $Version -or $result.contract_commands -ne 97 -or $result.rust_handlers_registered -ne 97) { throw 'Packaged self-test returned invalid version or handler results.' }
    foreach ($field in @('archive_runtime_verified', 'archive_runtime_publisher_authenticated', 'pdfium_render_verified', 'probe_runtime_verified', 'probe_sandbox_fail_closed', 'probe_direct_socket_blocked')) {
        if ($result.$field -ne $true) { throw "Packaged self-test did not verify $field" }
    }
    return $result
}
$Executable = (Resolve-Path -LiteralPath $Executable).Path
$DataDirectory = [IO.Path]::GetFullPath($DataDirectory)
if (Test-Path -LiteralPath $DataDirectory) { throw 'Packaged self-test requires a new isolated data directory.' }
if (-not $ReportPath) { $ReportPath = "$DataDirectory.self-test.json" }
$ReportPath = [IO.Path]::GetFullPath($ReportPath)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ReportPath) | Out-Null
$stderr = "$ReportPath.stderr.txt"
$originalPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $arguments = @('--self-test', '--data-dir', ('"' + $DataDirectory + '"'))
    $process = Start-Process -FilePath $Executable -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden -RedirectStandardOutput $ReportPath -RedirectStandardError $stderr
    $output = Get-Content -LiteralPath $ReportPath -Raw
    $result = Assert-PackagedSelfTest $process.ExitCode $output $ExpectedVersion
    Write-Host "Packaged KOI $($result.version) self-test passed: 97/97 Rust handlers and runtime checks."
} catch {
    if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr | Write-Host }
    throw
} finally { $env:PATH = $originalPath }
