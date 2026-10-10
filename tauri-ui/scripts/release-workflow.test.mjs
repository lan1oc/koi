import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const options = { skip: process.platform !== 'win32' };
const quote = value => `'${String(value).replaceAll("'", "''")}'`;
function run(source, environment = {}) {
  return spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', Buffer.from(`$ErrorActionPreference='Stop'\n$ProgressPreference='SilentlyContinue'\n${source}\nexit 0`, 'utf16le').toString('base64')], {
    cwd: root, encoding: 'utf8', windowsHide: true, timeout: 30000, env: { ...process.env, PSModulePath: path.join(process.env.SystemRoot || "C:/Windows", "System32/WindowsPowerShell/v1.0/Modules"), ...environment },
  });
}
function definitions(relative, names) {
  return `$tokens=$null;$errors=$null;$ast=[System.Management.Automation.Language.Parser]::ParseFile(${quote(path.join(root, relative))},[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ($errors|Out-String)}
    $names=@(${names.map(quote).join(',')})
    $ast.FindAll({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in $names},$true)|ForEach-Object{Invoke-Expression $_.Extent.Text}`;
}

test('direct release Git clears URL and environment proxies then restores process environment', options, () => {
  const result = run(`${definitions('push_workflow.ps1', ['Invoke-Git'])}
    $UseProxy=$false
    $script:seen=$false
    function git {
      if($args -contains '--get-regexp'){ $global:LASTEXITCODE=0;return 'http.https://github.com/.proxy' }
      if($env:HTTP_PROXY -or $env:HTTPS_PROXY -or $env:ALL_PROXY){throw 'proxy environment reached direct Git'}
      if($args -notcontains 'http.https://github.com/.proxy='){throw 'URL proxy was not overridden'}
      $script:seen=$true;$global:LASTEXITCODE=0
    }
    Invoke-Git -GitArguments @('ls-remote','origin')
    if(-not $script:seen){throw 'Git did not execute'}
    if($env:HTTP_PROXY -ne 'http://fixture.invalid:1' -or $env:HTTPS_PROXY -ne 'http://fixture.invalid:2' -or $env:ALL_PROXY -ne 'http://fixture.invalid:3'){throw 'caller proxy environment changed'}
    $UseProxy=$true
    function git { if($env:HTTPS_PROXY -ne 'http://fixture.invalid:2'){throw 'UseProxy did not retain settings'};$global:LASTEXITCODE=0 }
    Invoke-Git -GitArguments @('ls-remote','origin')
  `, { HTTP_PROXY:'http://fixture.invalid:1', HTTPS_PROXY:'http://fixture.invalid:2', ALL_PROXY:'http://fixture.invalid:3' });
  assert.equal(result.status, 0, result.stderr + result.stdout);
});

test('CI downloads bound connection and complete transfer time and propagate native failures', options, () => {
  const result = run(`${definitions('tauri-ui/scripts/prepare-ci-dependencies.ps1', ['Invoke-CiDownload'])}
    function Get-Command {param($Name,$CommandType,$ErrorAction) return [pscustomobject]@{Source='Invoke-CurlFixture'} }
    $script:seen=$false
    function Invoke-CurlFixture {
      $limit=[Array]::IndexOf($args,'--max-time')
      $connect=[Array]::IndexOf($args,'--connect-timeout')
      if($limit -lt 0 -or $args[$limit+1] -ne '45' -or $connect -lt 0 -or $args[$connect+1] -ne '20'){throw 'download timeout is not bounded'}
      if($args -notcontains '--fail' -or $args -notcontains '--location' -or $args -notcontains '--output'){throw 'download response handling is incomplete'}
      $script:seen=$true;$global:LASTEXITCODE=28
    }
    try {Invoke-CiDownload 'https://official.invalid/runtime.zip' 'fixture.zip' @{} 45;throw 'native timeout accepted'}catch{if($_.Exception.Message -notlike '*curl exit 28*'){throw}}
    if(-not $script:seen){throw 'bounded native request did not execute'}
  `);
  assert.equal(result.status, 0, result.stderr + result.stdout);
});

test('locked CI download retries transient errors and rejects corrupt data before cache replacement', options, t => {
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-ci-dependency-test-'));
  t.after(() => fs.rmSync(cache, { recursive:true, force:true }));
  const result = run(`${definitions('tauri-ui/scripts/prepare-ci-dependencies.ps1', ['Get-LockedArtifact'])}
    $CacheDirectory=${quote(cache)}
    $fixture=Join-Path $CacheDirectory 'fixture.bin';[IO.File]::WriteAllText($fixture,'official fixture')
    $hash=(Get-FileHash $fixture -Algorithm SHA256).Hash
    $script:attempt=0
    function Start-Sleep {}
    function Invoke-CiDownload {param($Url,$Destination,$Headers,$TimeoutSeconds)
      $script:attempt++;if($script:attempt -eq 1){throw 'transient fixture failure'};Copy-Item -LiteralPath $fixture -Destination $Destination
    }
    $file=Get-LockedArtifact 'https://official.invalid/runtime.zip' $hash 'runtime.zip'
    if($script:attempt -ne 2 -or (Get-FileHash $file).Hash -ne $hash){throw 'retry/download did not complete'}
    Get-LockedArtifact 'https://official.invalid/runtime.zip' $hash 'runtime.zip'|Out-Null
    if($script:attempt -ne 2){throw 'valid cached data downloaded again'}
    function Invoke-CiDownload {param($Url,$Destination,$Headers,$TimeoutSeconds) [IO.File]::WriteAllText($Destination,'corrupt download')}
    try {Get-LockedArtifact 'https://official.invalid/runtime.zip' $hash 'corrupt.zip';throw 'corrupt file accepted'}catch{if($_.Exception.Message -notlike '*hash mismatch*'){throw}}
    if(Test-Path -LiteralPath (Join-Path $CacheDirectory 'corrupt.zip')){throw 'corrupt artifact installed'}
  `);
  assert.equal(result.status, 0, result.stderr + result.stdout);
});

test('failed GitHub release download uses the official asset API with the same locked digest', options, t => {
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-ci-api-download-test-'));
  t.after(() => fs.rmSync(cache, { recursive:true, force:true }));
  const result = run(`${definitions('tauri-ui/scripts/prepare-ci-dependencies.ps1', ['Get-LockedArtifact'])}
    $CacheDirectory=${quote(cache)}
    $fixture=Join-Path $CacheDirectory 'expected.bin';[IO.File]::WriteAllText($fixture,'verified API artifact')
    $hash=(Get-FileHash $fixture).Hash
    $script:calls=0
    function Start-Sleep {}
    function Invoke-CiDownload {param($Url,$Destination,$Headers,$TimeoutSeconds)
      $script:calls++
      if($Url -eq 'https://github.com/owner/project/releases/download/v1/runtime.zip'){throw 'direct fixture timeout'}
      if($Url -eq 'https://api.github.com/repos/owner/project/releases/tags/v1'){[IO.File]::WriteAllText($Destination,'{"assets":[{"name":"runtime.zip","url":"https://api.github.com/repos/owner/project/releases/assets/1"}]}');return}
      if($Url -ne 'https://api.github.com/repos/owner/project/releases/assets/1' -or $Headers.Accept -ne 'application/octet-stream'){throw 'unexpected fallback source'}
      Copy-Item -LiteralPath $fixture -Destination $Destination
    }
    $file=Get-LockedArtifact 'https://github.com/owner/project/releases/download/v1/runtime.zip' $hash 'runtime.zip'
    if($script:calls -ne 3 -or (Get-FileHash $file).Hash -ne $hash){throw 'official fallback did not return the locked bytes'}
  `);
  assert.equal(result.status, 0, result.stderr + result.stdout);
});

test('packaged GUI self-test requires process success and complete version and runtime proof', options, () => {
  const value = {ok:true,version:'4.0.0',contract_commands:97,rust_handlers_registered:97,archive_runtime_verified:true,archive_runtime_publisher_authenticated:true,pdfium_render_verified:true,probe_runtime_verified:true,probe_sandbox_fail_closed:true,probe_direct_socket_blocked:true};
  const result = run(`${definitions('tauri-ui/scripts/test-packaged-release.ps1', ['Assert-PackagedSelfTest'])}
    $good=${quote(JSON.stringify(value))}
    Assert-PackagedSelfTest 0 $good '4.0.0'|Out-Null
    foreach($case in @(@(1,$good,'exit code'),@(0,'','did not return'),@(0,$good.Replace('4.0.0','4.0.1'),'invalid version'),@(0,$good.Replace('"pdfium_render_verified":true','"pdfium_render_verified":false'),'pdfium_render_verified'))){
      try{Assert-PackagedSelfTest $case[0] $case[1] '4.0.0';throw 'invalid proof accepted'}catch{if(-not $_.Exception.Message.Contains($case[2])){throw}}
    }
  `);
  assert.equal(result.status, 0, result.stderr + result.stdout);
});
