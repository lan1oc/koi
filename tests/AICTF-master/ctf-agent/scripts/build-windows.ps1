param(
  [string]$OutDir = "dist",
  [string]$ExeName = "LovelyIrisAgent.exe"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outPath = Join-Path $repoRoot $OutDir

Write-Host "== Build frontend =="
Push-Location (Join-Path $repoRoot "frontend")
if (Get-Command bun -ErrorAction SilentlyContinue) {
  bun install
  bun run build
} else {
  npm ci
  npm run build
}
Pop-Location

Write-Host "== Copy frontend/dist -> backend/web/dist =="
$srcDist = Join-Path $repoRoot "frontend\dist"
$dstDist = Join-Path $repoRoot "backend\web\dist"
if (!(Test-Path $srcDist)) { throw "frontend dist not found: $srcDist" }

Remove-Item -Recurse -Force $dstDist -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $dstDist | Out-Null
Copy-Item -Recurse -Force (Join-Path $srcDist "*") $dstDist

Write-Host "== Build desktop exe =="
New-Item -ItemType Directory -Force -Path $outPath | Out-Null
Push-Location (Join-Path $repoRoot "backend")

# Ensure deps are resolved (also updates go.sum)
go mod tidy

Write-Host "== Generate Windows icon resources =="
go run .\cmd\genicon
go run github.com/josephspurrier/goversioninfo/cmd/goversioninfo@v1.5.0 -icon cmd\desktop\icon.ico -o cmd\desktop\resource.syso cmd\desktop\versioninfo.json

# -H=windowsgui: hide console window for double-click launches
go build -trimpath -ldflags "-s -w -H=windowsgui" -o (Join-Path $outPath $ExeName) .\cmd\desktop

Pop-Location

Write-Host "OK: $(Join-Path $outPath $ExeName)"
