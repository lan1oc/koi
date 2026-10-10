import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const options = { skip: process.platform !== 'win32' };
const quote = value => `'${String(value).replaceAll("'", "''")}'`;
function run(source, environment = {}, executable = 'powershell.exe') {
  return spawnSync(executable, ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', Buffer.from(`$ErrorActionPreference='Stop'\n$ProgressPreference='SilentlyContinue'\n${source}\nexit 0`, 'utf16le').toString('base64')], {
    cwd: root, encoding: 'utf8', windowsHide: true, timeout: 30000, env: { ...process.env, PSModulePath: path.join(process.env.SystemRoot || "C:/Windows", "System32/WindowsPowerShell/v1.0/Modules"), ...environment },
  });
}
function definitions(relative, names) {
  return `$tokens=$null;$errors=$null;$ast=[System.Management.Automation.Language.Parser]::ParseFile(${quote(path.join(root, relative))},[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ($errors|Out-String)}
    $names=@(${names.map(quote).join(',')})
    $ast.FindAll({param($n)$n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -in $names},$true)|ForEach-Object{Invoke-Expression $_.Extent.Text}`;
}

function visualStudioFixture(t) {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-vs-environment-'));
  t.after(() => {
    assert.ok(path.resolve(fixture).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(fixture, { recursive:true, force:true });
  });
  const programFiles = path.join(fixture, 'Program Files (x86)');
  const installation = path.join(programFiles, 'Microsoft Visual Studio', '2022', 'Enterprise');
  const locator = path.join(programFiles, 'Microsoft Visual Studio', 'Installer', 'vswhere.exe');
  const batch = path.join(installation, 'VC', 'Auxiliary', 'Build', 'vcvars64.bat');
  const bin = path.join(installation, 'VC', 'Tools', 'MSVC', 'fixture', 'bin', 'Hostx64', 'x64');
  const lib = path.join(installation, 'Windows SDK (x64)', 'lib');
  const include = path.join(installation, 'SDK include 中文 & headers');
  const sdk = path.join(installation, 'Windows SDK (x64)');
  for (const directory of [path.dirname(locator), path.dirname(batch), bin, lib, include]) fs.mkdirSync(directory, { recursive:true });
  const compiled = run(`Add-Type -OutputAssembly ${quote(locator)} -OutputType ConsoleApplication -TypeDefinition 'public class KoiVsWhereFixture { public static int Main() { System.Console.WriteLine(System.Environment.GetEnvironmentVariable("KOI_FIXTURE_VS_INSTALL")); return 0; } }'`);
  assert.equal(compiled.status, 0, compiled.stderr + compiled.stdout);
  for (const name of ['cl.exe', 'link.exe', 'rc.exe']) fs.copyFileSync(locator, path.join(bin, name));
  for (const name of ['kernel32.lib', 'libcmt.lib', 'ucrt.lib']) fs.writeFileSync(path.join(lib, name), 'fixture');
  fs.writeFileSync(batch, [
    '@echo off',
    'set "PATH=%KOI_FIXTURE_VS_BIN%;%SystemRoot%\\System32;%SystemRoot%"',
    'set "LIB=%KOI_FIXTURE_VS_LIB%"',
    'set "LIBPATH=%KOI_FIXTURE_VS_LIB%"',
    'set "INCLUDE=%KOI_FIXTURE_VS_INCLUDE%"',
    'set "VSINSTALLDIR=%KOI_FIXTURE_VS_INSTALL%"',
    'set "VCINSTALLDIR=%KOI_FIXTURE_VS_INSTALL%\\VC\\"',
    'set "WindowsSdkDir=%KOI_FIXTURE_VS_SDK%"',
    'set "WindowsSDKVersion=fixture-sdk\\"',
    'set "KOI_VCVARS_FIXTURE=loaded"',
    'exit /b 0',
  ].join('\r\n') + '\r\n');
  return {
    fixture, batch, installation, bin, lib, include,
    environment: {
      'ProgramFiles(x86)':programFiles, ProgramFiles:programFiles,
      KOI_FIXTURE_VS_INSTALL:installation, KOI_FIXTURE_VS_BIN:bin,
      KOI_FIXTURE_VS_LIB:lib, KOI_FIXTURE_VS_INCLUDE:include,
      KOI_FIXTURE_VS_SDK:sdk,
    },
  };
}
const toolchainDefinitions = () => definitions('build_release.ps1', ['Test-WindowsRustToolchain', 'Import-VisualStudioToolchain', 'Initialize-WindowsRustToolchain']);
const resetToolchainEnvironment = `$env:PATH="$env:SystemRoot\\System32;$env:SystemRoot";$env:LIB='';$env:INCLUDE='';$env:LIBPATH='';$env:KOI_VCVARS_FIXTURE=''`;

test('Visual Studio environment loads real space-path batch in Windows PowerShell and all PowerShell 7 argument modes', options, t => {
  const fixture = visualStudioFixture(t);
  const cases = [['powershell.exe',null], ...['Legacy','Windows','Standard'].map(mode => ['pwsh.exe',mode])];
  for (const [host, mode] of cases) {
    const result = run(`${toolchainDefinitions()}
      ${resetToolchainEnvironment}
      ${mode ? `$PSNativeCommandArgumentPassing='${mode}'` : ''}
      function Import-PortableWindowsRustToolchain { throw 'installed Visual Studio was not reused' }
      function Invoke-WebRequest { throw 'installed Visual Studio caused a download' }
      function Start-Process { throw 'installed Visual Studio caused an install' }
      Initialize-WindowsRustToolchain -SkipInstall $false
      if(-not (Test-WindowsRustToolchain) -or $env:KOI_VCVARS_FIXTURE -ne 'loaded'){throw 'real vcvars environment was not loaded'}
      if($env:LIB -ne $env:KOI_FIXTURE_VS_LIB -or $env:LIBPATH -ne $env:KOI_FIXTURE_VS_LIB -or $env:INCLUDE -ne $env:KOI_FIXTURE_VS_INCLUDE){throw 'library/include environment did not survive'}
      if($env:VSINSTALLDIR -ne $env:KOI_FIXTURE_VS_INSTALL -or $env:WindowsSdkDir -ne $env:KOI_FIXTURE_VS_SDK -or $env:WindowsSDKVersion -ne 'fixture-sdk\\'){throw 'Visual Studio/SDK environment did not survive'}
      foreach($name in @('cl.exe','link.exe','rc.exe')){if((Get-Command $name -CommandType Application).Source -ne (Join-Path $env:KOI_FIXTURE_VS_BIN $name)){throw 'tool path did not survive'}}
    `, fixture.environment, host);
    assert.equal(result.status, 0, `${host} ${mode || ''}: ${result.error || result.stderr + result.stdout}`);
  }
});

test('Visual Studio environment rejects failed real vcvars without importing its partial environment', options, t => {
  const fixture = visualStudioFixture(t);
  fs.writeFileSync(fixture.batch, '@set KOI_VCVARS_FIXTURE=partial\r\n@exit /b 42\r\n');
  for (const host of ['powershell.exe','pwsh.exe']) {
    const result = run(`${toolchainDefinitions()}
      ${resetToolchainEnvironment}
      if(Import-VisualStudioToolchain){throw 'failed vcvars was accepted'}
      if($env:KOI_VCVARS_FIXTURE){throw 'failed vcvars changed parent environment'}
    `, fixture.environment, host);
    assert.equal(result.status, 0, `${host}: ${result.error || result.stderr + result.stdout}`);
    assert.match(result.stdout + result.stderr, /environment initialization failed/);
    assert.match(result.stdout + result.stderr, /exit 42/);
  }
});

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

test('Release executable discovery runs one npm Git and Node when duplicate installations exist', options, t => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-ci-multiple-tools-'));
  t.after(() => {
    assert.ok(path.resolve(fixture).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(fixture, { recursive:true, force:true });
  });
  const first = path.join(fixture, 'Program Files', 'first tools');
  const second = path.join(fixture, 'Program Files', 'second tools');
  for (const [index, directory] of [first,second].entries()) {
    fs.mkdirSync(directory, { recursive:true });
    const label = index === 0 ? 'first' : 'second';
    const native = path.join(directory, 'fixture.exe');
    const source = `public class KoiToolFixture${index} { public static int Main(string[] args) { string tool=System.IO.Path.GetFileName(System.Reflection.Assembly.GetExecutingAssembly().Location); System.IO.File.AppendAllText(System.Environment.GetEnvironmentVariable("KOI_DISCOVERY_TRACE"), "${label} "+tool+System.Environment.NewLine); if(tool=="git.exe") System.Console.WriteLine(new string('a',40)); return 0; } }`;
    const compiled = run(`Add-Type -OutputAssembly ${quote(native)} -OutputType ConsoleApplication -TypeDefinition ${quote(source)}`);
    assert.equal(compiled.status, 0, compiled.stderr + compiled.stdout);
    for (const tool of ['git.exe','node.exe','cargo.exe']) fs.copyFileSync(native, path.join(directory, tool));
    fs.writeFileSync(path.join(directory, 'npm.cmd'), `@echo ${label} npm.cmd>>"%KOI_DISCOVERY_TRACE%"\r\n@exit /b 0\r\n`);
  }
  const repo = path.join(fixture, 'source');
  fs.mkdirSync(path.join(repo, 'tauri-ui', 'src-tauri'), {recursive:true});
  fs.mkdirSync(path.join(repo, 'tauri-ui', 'scripts'), {recursive:true});
  fs.copyFileSync(path.join(root, 'build_release.ps1'), path.join(repo, 'build_release.ps1'));
  fs.writeFileSync(path.join(repo, 'tauri-ui', 'package.json'), '{}\n');
  fs.writeFileSync(path.join(repo, 'tauri-ui', 'src-tauri', 'Cargo.toml'), '[package]\nname = "fixture"\nversion = "4.0.0"\n');
  for (const name of ['verify-backend-contract.mjs','verify-behavior-matrix.mjs']) fs.writeFileSync(path.join(repo, 'tauri-ui', 'scripts', name), '// fixture\n');
  for (const host of ['powershell.exe','pwsh.exe']) {
    const trace = path.join(fixture, `${host}-trace.txt`);
    const result = run(`${definitions('build_release.ps1', ['Resolve-Npm','Invoke-External'])}
      ${definitions('push_workflow.ps1', ['Invoke-ReleaseSourceChecks'])}
      $env:PATH=${quote([first,second,path.join(process.env.SystemRoot || 'C:/Windows','System32')].join(';'))}
      $env:KOI_DISCOVERY_TRACE=${quote(trace)}
      $env:KOI_SOURCE_REVISION=${quote('a'.repeat(40))};$env:GITHUB_SHA=''
      function Install-PortableNode { throw 'available npm unexpectedly caused an installation' }
      foreach($name in @('npm.cmd','git.exe','node.exe')){if(@(Get-Command $name -CommandType Application).Count -ne 2){throw 'duplicate tools were not exercised'}}
      $npm=Resolve-Npm ${quote(repo)} '22.16.0'
      if($npm -isnot [string] -or $npm -ne ${quote(path.join(first, 'npm.cmd'))}){throw 'npm did not resolve one program in PATH order'}
      Invoke-External $npm @('--version')
      & ${quote(path.join(repo, 'build_release.ps1'))} -StrictRelease -DryRun
      Push-Location ${quote(repo)}
      try {Invoke-ReleaseSourceChecks} finally {Pop-Location}
    `, {}, host);
    assert.equal(result.status, 0, `${host}: ${result.error || result.stderr + result.stdout}`);
    const calls = fs.readFileSync(trace,'utf8').trim().split(/\r?\n/);
    assert.deepEqual(calls, ['first npm.cmd','first git.exe','first node.exe','first node.exe']);
  }
});

test('CI download resolves one real curl when Windows and Git copies both exist on PATH', options, t => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-ci-multiple-curl-'));
  t.after(() => {
    assert.ok(path.resolve(fixture).startsWith(path.resolve(os.tmpdir()) + path.sep));
    fs.rmSync(fixture, { recursive:true, force:true });
  });
  const systemRoot = process.env.SystemRoot || 'C:/Windows';
  const systemBin = path.join(systemRoot, 'System32');
  const gitBin = path.join(fixture, 'Program Files', 'Git', 'ucrt64', 'bin');
  fs.mkdirSync(gitBin, { recursive:true });
  fs.copyFileSync(path.join(systemBin, 'curl.exe'), path.join(gitBin, 'curl.exe'));
  const payload = path.join(fixture, 'runtime payload.bin');
  const bytes = Buffer.from([0,1,2,10,13,127,128,254,255]);
  fs.writeFileSync(payload, bytes);
  for (const host of ['powershell.exe','pwsh.exe']) {
    for (const order of ['Windows-first','Git-first']) {
      const cache = path.join(fixture, `${host}-${order} download cache`);
      fs.mkdirSync(cache);
      const nativePath = (order === 'Windows-first' ? [systemBin,gitBin] : [gitBin,systemBin]).join(';');
      const result = run(`${definitions('tauri-ui/scripts/prepare-ci-dependencies.ps1', ['Invoke-CiDownload','Get-LockedArtifact'])}
        $env:PATH=${quote(nativePath)}
        $candidates=@(Get-Command curl.exe -CommandType Application)
        if($candidates.Count -ne 2){throw 'real duplicate curl discovery was not exercised'}
        $CacheDirectory=${quote(cache)}
        $hash=(Get-FileHash -LiteralPath ${quote(payload)} -Algorithm SHA256).Hash
        $download=Get-LockedArtifact ${quote(pathToFileURL(payload).href)} $hash 'locked-runtime.bin'
        if((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $hash){throw 'real curl did not return the locked bytes'}
        if(Test-Path -LiteralPath "$download.download"){throw 'successful transfer left partial files'}
      `, {}, host);
      assert.equal(result.status, 0, `${host} ${order}: ${result.error || result.stderr + result.stdout}`);
      assert.deepEqual(fs.readFileSync(path.join(cache, 'locked-runtime.bin')), bytes);
    }
  }
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
