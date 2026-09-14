import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {
  requireRealDirectory,
  requireRegularFile,
} from './release-gates.mjs';

const ARCHIVE_FORMAT = 'koi-archive-runtime-v3';
const ARCHIVE_RELEASE_ASSET = 'NanaZip_7.0.1832.0.msixbundle';
const ARCHIVE_RELEASE_ASSET_URL = 'https://github.com/M2Team/NanaZip/releases/download/7.0.1832.0/NanaZip_7.0.1832.0.msixbundle';
const ARCHIVE_RELEASE_ASSET_SHA256 = '10ce4246ea9efc0dcc7780e676cdcc6c7c74eca0abeb19a5ea76f384d9be2a75';
const ARCHIVE_LICENSE_ASSET = 'NanaZip_7.0.1832.0_Binaries.zip';
const ARCHIVE_LICENSE_ASSET_URL = 'https://github.com/M2Team/NanaZip/releases/download/7.0.1832.0/NanaZip_7.0.1832.0_Binaries.zip';
const ARCHIVE_LICENSE_ASSET_SHA256 = '3cfd7745e87e1b8409a467f08dafdbd51d5c666d9df82c2770d38639ad31f910';
const ARCHIVE_SIGNED_PACKAGE = 'NanaZipPackage_7.0.1832.0_x64.msix';
const ARCHIVE_SIGNED_PACKAGE_SHA256 = 'df0469573ec269a5bc1dc589a68a19dda3dc8dfe4b4a8d849de81ee42c422e40';
const ARCHIVE_TRUST_MODEL = 'publisher-signed-msix-runtime-binding-v1';
const ARCHIVE_SIGNER_SUBJECT = 'CN=E310A153-74A9-4D81-800B-857A8D58408A';
const ARCHIVE_SIGNER_THUMBPRINT = '6f9e58cdb36763170616b86c419b8bb19e85e86c';
const PROBE_RUNTIME_VERSION = '3.13.15';
const PROBE_RUNTIME_URL = 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip';
const PROBE_RUNTIME_ARCHIVE_SHA256 = 'd1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf';

function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function lstatRegular(filePath, label) {
  const stat = fs.lstatSync(filePath, { throwIfNoEntry: false });
  if (!stat) throw new Error(`Missing ${label}: ${filePath}`);
  if (stat.isSymbolicLink()) throw new Error(`${label} must not be a symbolic link: ${filePath}`);
  return stat;
}

function inventory(root) {
  const files = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const stat = fs.lstatSync(fullPath);
      if (stat.isSymbolicLink()) throw new Error(`Locked runtime contains a symbolic link: ${fullPath}`);
      if (stat.isDirectory()) pending.push(fullPath);
      else if (stat.isFile()) files.push(path.relative(root, fullPath).replaceAll('\\', '/'));
      else throw new Error(`Locked runtime contains an unsupported entry: ${fullPath}`);
    }
  }
  return files.sort();
}

export function verifyLockedRuntime({
  lockPath,
  runtimeDir,
  expectedFormat,
  expectedPlatform = 'windows-x64',
}) {
  if (!lstatRegular(lockPath, 'Locked runtime manifest').isFile()) {
    throw new Error(`Missing locked runtime manifest: ${lockPath}`);
  }
  if (!lstatRegular(runtimeDir, 'Locked runtime directory').isDirectory()) {
    throw new Error(`Missing locked runtime directory: ${runtimeDir}`);
  }
  const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  if (lock.format !== expectedFormat || lock.platform !== expectedPlatform || !Array.isArray(lock.files)) {
    throw new Error(`Locked runtime manifest has an unexpected format or platform: ${lockPath}`);
  }
  const expected = new Set();
  for (const entry of lock.files) {
    const relative = String(entry?.path || '');
    if (!relative
      || relative.includes('\\')
      || relative.includes(':')
      || path.posix.isAbsolute(relative)
      || path.posix.normalize(relative) !== relative
      || relative.split('/').some((part) => !part || part === '.' || part === '..')
      || expected.has(relative)) {
      throw new Error(`Locked runtime manifest contains an unsafe or duplicate path: ${relative}`);
    }
    if (!Number.isSafeInteger(entry.size) || entry.size <= 0 || !/^[0-9a-f]{64}$/.test(String(entry.sha256 || ''))) {
      throw new Error(`Locked runtime manifest contains invalid metadata: ${relative}`);
    }
    expected.add(relative);
    const fullPath = path.join(runtimeDir, ...relative.split('/'));
    const stat = lstatRegular(fullPath, 'Locked runtime file');
    if (!stat?.isFile() || stat.size !== entry.size || sha256(fullPath) !== entry.sha256) {
      throw new Error(`Locked runtime file failed size/hash verification: ${fullPath}`);
    }
  }
  const actual = inventory(runtimeDir);
  const missing = [...expected].filter((relative) => !actual.includes(relative));
  const extra = actual.filter((relative) => !expected.has(relative));
  if (missing.length || extra.length) {
    throw new Error(`Locked runtime inventory mismatch (missing: ${missing.join(', ')}; extra: ${extra.join(', ')})`);
  }
  return lock;
}

export function verifyProbeRuntime({ lockPath, runtimeDir }) {
  requireRegularFile(lockPath, 'Probe runtime manifest');
  requireRealDirectory(runtimeDir, 'Probe runtime directory');
  let lock;
  try {
    lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  } catch (error) {
    throw new Error(`Probe runtime manifest is invalid JSON: ${error.message}`);
  }
  if (lock?.format !== 'koi-probe-runtime-v1'
    || lock.implementation !== 'CPython'
    || lock.version !== PROBE_RUNTIME_VERSION
    || lock.platform !== 'windows-x64'
    || lock.url !== PROBE_RUNTIME_URL
    || lock.license !== 'Python-2.0'
    || lock.executable !== 'probe-runtime/python.exe'
    || lock.sha256 !== PROBE_RUNTIME_ARCHIVE_SHA256
    || !Array.isArray(lock.files)
    || !lock.files.length) {
    throw new Error('Probe runtime manifest does not match the reviewed official CPython Windows x64 runtime.');
  }
  const expected = new Set();
  for (const entry of lock.files) {
    const lockedPath = String(entry?.path || '');
    const prefix = 'probe-runtime/';
    if (!lockedPath.startsWith(prefix)) {
      throw new Error(`Probe runtime manifest contains an unsafe path: ${lockedPath}`);
    }
    const relative = lockedPath.slice(prefix.length);
    if (!relative
      || relative.includes('\\')
      || relative.includes(':')
      || path.posix.isAbsolute(relative)
      || path.posix.normalize(relative) !== relative
      || relative.split('/').some((part) => !part || part === '.' || part === '..')
      || expected.has(relative)
      || !/^[0-9a-f]{64}$/.test(String(entry?.sha256 || ''))) {
      throw new Error(`Probe runtime manifest contains invalid file metadata: ${lockedPath}`);
    }
    expected.add(relative);
    const fullPath = path.join(runtimeDir, ...relative.split('/'));
    const stat = lstatRegular(fullPath, 'probe runtime file');
    if (!stat.isFile() || sha256(fullPath) !== entry.sha256) {
      throw new Error(`Probe runtime file failed hash verification: ${fullPath}`);
    }
  }
  const actual = inventory(runtimeDir);
  const missing = [...expected].filter((relative) => !actual.includes(relative));
  const extra = actual.filter((relative) => !expected.has(relative));
  if (missing.length || extra.length) {
    throw new Error(`Probe runtime inventory mismatch (missing: ${missing.join(', ')}; extra: ${extra.join(', ')})`);
  }
  return lock;
}

function verifyPeX64(filePath) {
  const bytes = fs.readFileSync(filePath);
  if (bytes.length < 0x40 || bytes.subarray(0, 2).toString('ascii') !== 'MZ') {
    throw new Error(`Archive runtime PE image has an invalid DOS header: ${filePath}`);
  }
  const peOffset = bytes.readUInt32LE(0x3c);
  if (peOffset > bytes.length - 24 || bytes.subarray(peOffset, peOffset + 4).toString('binary') !== 'PE\0\0') {
    throw new Error(`Archive runtime PE image has an invalid NT header: ${filePath}`);
  }
  if (bytes.readUInt16LE(peOffset + 4) !== 0x8664) {
    throw new Error(`Archive runtime PE image is not Windows x64: ${filePath}`);
  }
  const optionalHeaderSize = bytes.readUInt16LE(peOffset + 20);
  const optionalHeader = peOffset + 24;
  if (optionalHeaderSize < 152
    || optionalHeader > bytes.length - optionalHeaderSize
    || bytes.readUInt16LE(optionalHeader) !== 0x20b) {
    throw new Error(`Archive runtime PE image has an invalid PE32+ optional header: ${filePath}`);
  }
  return true;
}

function verifyPublisherSignature(packagePath) {
  if (process.platform !== 'win32') {
    throw new Error('NanaZip publisher signature verification requires Windows.');
  }
  const script = [
    "$ErrorActionPreference='Stop'",
    "$module=Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1'",
    'Import-Module $module -Force',
    '$signature=Get-AuthenticodeSignature -LiteralPath $env:KOI_ARCHIVE_SIGNATURE_TARGET',
    "[PSCustomObject]@{status=[string]$signature.Status;signatureType=[string]$signature.SignatureType;signerSubject=[string]$signature.SignerCertificate.Subject;signerThumbprint=[string]$signature.SignerCertificate.Thumbprint;timestampSubject=[string]$signature.TimeStamperCertificate.Subject}|ConvertTo-Json -Compress",
  ].join(';');
  const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    encoding: 'utf8',
    env: { ...process.env, KOI_ARCHIVE_SIGNATURE_TARGET: packagePath },
    timeout: 30_000,
    windowsHide: true,
    maxBuffer: 1024 * 1024,
  });
  if (result.status !== 0 || result.error) {
    throw new Error(
      `NanaZip publisher signature check could not run: ${result.error?.message || result.stderr || result.stdout}`,
    );
  }
  let signature;
  try {
    signature = JSON.parse(String(result.stdout || '').trim());
  } catch (error) {
    throw new Error(`NanaZip publisher signature result is invalid: ${error.message}`);
  }
  if (signature.status !== 'Valid'
    || signature.signatureType !== 'Authenticode'
    || signature.signerSubject !== ARCHIVE_SIGNER_SUBJECT
    || String(signature.signerThumbprint || '').toLowerCase() !== ARCHIVE_SIGNER_THUMBPRINT
    || !String(signature.timestampSubject || '').includes('Microsoft Time-Stamp Service')) {
    throw new Error('NanaZip MSIX publisher signature, signer identity, or timestamp is invalid.');
  }
  return signature;
}

function inspectSignedPackage(packagePath, runtimeDir) {
  if (process.platform !== 'win32') {
    throw new Error('NanaZip signed-package inspection requires Windows.');
  }
  const script = [
    "$ErrorActionPreference='Stop'",
    'Add-Type -AssemblyName System.IO.Compression.FileSystem',
    '$archive=[IO.Compression.ZipFile]::OpenRead($env:KOI_ARCHIVE_SIGNATURE_TARGET)',
    'try {',
    "$names=@('NanaZip.Universal.Console.exe','NanaZip.Core.dll','NanaZip.Codecs.dll','K7Base.dll','K7User.dll')",
    '$entries=@()',
    'foreach($name in $names){',
    '$entry=$archive.GetEntry($name); if(-not $entry){throw "missing signed MSIX entry: $name"}',
    '$stream=$entry.Open(); try{$memory=[IO.MemoryStream]::new(); try{$stream.CopyTo($memory); $signedBytes=$memory.ToArray()}finally{$memory.Dispose()}}finally{$stream.Dispose()}',
    '$runtimeBytes=[IO.File]::ReadAllBytes((Join-Path $env:KOI_ARCHIVE_RUNTIME_DIR $name))',
    '$sha=[Security.Cryptography.SHA256]::Create(); try{$hash=$sha.ComputeHash($signedBytes)}finally{$sha.Dispose()}',
    "$entries += [PSCustomObject]@{name=$name;bytes=$signedBytes.Length;sha256=([BitConverter]::ToString($hash)).Replace('-','').ToLowerInvariant();byteIdentical=[Linq.Enumerable]::SequenceEqual($signedBytes,$runtimeBytes)}",
    '}',
    '$manifestEntry=$archive.GetEntry("AppxManifest.xml"); if(-not $manifestEntry){throw "missing AppxManifest.xml"}',
    '$reader=[IO.StreamReader]::new($manifestEntry.Open()); try{$manifest=$reader.ReadToEnd()}finally{$reader.Dispose()}',
    '$signatureEntry=$archive.GetEntry("AppxSignature.p7x"); if(-not $signatureEntry){throw "missing AppxSignature.p7x"}',
    '[PSCustomObject]@{entries=$entries;manifest=$manifest;signaturePartLength=$signatureEntry.Length}|ConvertTo-Json -Compress -Depth 4',
    '} finally {$archive.Dispose()}',
  ].join(';');
  const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    encoding: 'utf8',
    env: {
      ...process.env,
      KOI_ARCHIVE_SIGNATURE_TARGET: packagePath,
      KOI_ARCHIVE_RUNTIME_DIR: runtimeDir,
    },
    timeout: 30_000,
    windowsHide: true,
    maxBuffer: 1024 * 1024,
  });
  if (result.status !== 0 || result.error) {
    throw new Error(
      `NanaZip signed-package inspection failed: ${result.error?.message || result.stderr || result.stdout}`,
    );
  }
  try {
    return JSON.parse(String(result.stdout || '').trim());
  } catch (error) {
    throw new Error(`NanaZip signed-package inspection result is invalid: ${error.message}`);
  }
}

function validArchiveTrust(trust) {
  if (trust?.model !== ARCHIVE_TRUST_MODEL
    || trust.publisher_authenticated !== true
    || trust.publisher_signature?.package !== 'authenticode-valid'
    || trust.publisher_signature?.signer_subject !== ARCHIVE_SIGNER_SUBJECT
    || trust.publisher_signature?.signer_thumbprint !== ARCHIVE_SIGNER_THUMBPRINT
    || trust.publisher_signature?.timestamped !== true
    || trust.publisher_signature?.runtime_binding !== 'byte-identical-msix-entries'
    || trust.package_identity?.name !== '40174MouriNaruto.NanaZip'
    || trust.package_identity?.publisher !== ARCHIVE_SIGNER_SUBJECT
    || trust.package_identity?.version !== '7.0.1832.0'
    || trust.package_identity?.architecture !== 'x64'
    || trust.reviewed_at !== '2026-09-14'
    || !Array.isArray(trust.evidence)
    || trust.evidence.length !== 3) {
    return false;
  }
  const evidence = new Map(trust.evidence.map((entry) => [entry?.kind, entry]));
  if (evidence.size !== 3) return false;
  const official = evidence.get('official-release-asset');
  const signature = evidence.get('microsoft-marketplace-authenticode');
  const binding = evidence.get('signed-package-runtime-binding');
  return official?.authority === 'M2-Team NanaZip GitHub release'
    && official.url === 'https://github.com/M2Team/NanaZip/releases/tag/7.0.1832.0'
    && official.artifact === ARCHIVE_RELEASE_ASSET
    && official.artifact_url === ARCHIVE_RELEASE_ASSET_URL
    && official.sha256 === ARCHIVE_RELEASE_ASSET_SHA256
    && signature?.authority === 'Microsoft Marketplace CA G 024'
    && signature.url === 'https://github.com/M2Team/NanaZip/releases/tag/7.0.1832.0'
    && signature.artifact === ARCHIVE_SIGNED_PACKAGE
    && signature.sha256 === ARCHIVE_SIGNED_PACKAGE_SHA256
    && binding?.authority === 'KOI release review'
    && binding.url === 'https://github.com/M2Team/NanaZip/tree/4f6f082858cb959a82c0d64a46352d7fb40ff146'
    && binding.artifact === 'NanaZip.Universal.Console.exe,NanaZip.Core.dll,NanaZip.Codecs.dll,K7Base.dll,K7User.dll'
    && binding.commit === '4f6f082858cb959a82c0d64a46352d7fb40ff146';
}

export function verifyArchiveRuntimeProvenance(lock, runtimeDir) {
  const expectedFiles = new Map([
    [ARCHIVE_SIGNED_PACKAGE, ['publisher-signed-package', 5858305, ARCHIVE_SIGNED_PACKAGE_SHA256]],
    ['NanaZip.Universal.Console.exe', ['console-runtime', 654336, 'd12afcaa7b4478490649b8f6b0ea26c2bf94b704687c5e2f4efefcfe77503465']],
    ['NanaZip.Core.dll', ['core-runtime', 2087424, 'b256ab04e827c93c99553c69165bcb196d422e66177f491707c7044c5e587be9']],
    ['NanaZip.Codecs.dll', ['codec-runtime', 2226688, '11a3385eee17426421ef84e7c3b239d877a4510d0dc883a2e27ab6c2aa5739ce']],
    ['K7Base.dll', ['base-support-runtime', 63488, 'd52aa4421303978217c3ba827172fdefd911852349d8a58a993fb13e8babe6c0']],
    ['K7User.dll', ['user-support-runtime', 40448, 'ebf0af5c3dbe1f78e0d9fc1bd82a589c938188cc8323bc36df3602b0b247fbbf']],
    ['License.txt', ['license', 27857, 'bff47db77f42fd08dccb1f20037eb661f3bf2542fe5fd45dc54dc036f98c01d4']],
  ]);
  const validSource = lock?.format === ARCHIVE_FORMAT
    && lock.version === '7.0.1832.0'
    && lock.engine_version === '2609.1'
    && lock.platform === 'windows-x64'
    && lock.architecture === 'x86_64'
    && lock.executable === 'NanaZip.Universal.Console.exe'
    && lock.source?.project === 'NanaZip'
    && lock.source?.upstream_url === 'https://github.com/M2Team/NanaZip'
    && lock.source?.release_url === 'https://github.com/M2Team/NanaZip/releases/tag/7.0.1832.0'
    && lock.source?.release_commit === '4f6f082858cb959a82c0d64a46352d7fb40ff146'
    && lock.source?.release_asset === ARCHIVE_RELEASE_ASSET
    && lock.source?.release_asset_url === ARCHIVE_RELEASE_ASSET_URL
    && lock.source?.release_asset_size === 11930165
    && lock.source?.release_asset_sha256 === ARCHIVE_RELEASE_ASSET_SHA256
    && lock.source?.license_asset === ARCHIVE_LICENSE_ASSET
    && lock.source?.license_asset_url === ARCHIVE_LICENSE_ASSET_URL
    && lock.source?.license_asset_size === 8090745
    && lock.source?.license_asset_sha256 === ARCHIVE_LICENSE_ASSET_SHA256
    && lock.source?.signed_package === ARCHIVE_SIGNED_PACKAGE
    && lock.source?.signed_package_size === 5858305
    && lock.source?.signed_package_sha256 === ARCHIVE_SIGNED_PACKAGE_SHA256
    && lock.source?.release_date === '2026-09-06'
    && validArchiveTrust(lock.trust)
    && lock.licenses?.console_spdx === 'MIT AND LGPL-2.1-or-later'
    && lock.licenses?.notice_file === 'License.txt'
    && String(lock.licenses?.library_summary || '').includes('LicenseRef-unRAR-restriction');
  const files = Array.isArray(lock?.files) ? lock.files : [];
  const validFiles = files.length === expectedFiles.size && files.every((entry) => {
    const expected = expectedFiles.get(entry.path);
    return expected
      && entry.role === expected[0]
      && entry.size === expected[1]
      && entry.sha256 === expected[2];
  });
  if (!validSource || !validFiles) {
    throw new Error('Archive runtime provenance or publisher trust declaration does not match the reviewed NanaZip Windows x64 artifact.');
  }
  if (!lstatRegular(runtimeDir, 'Archive runtime directory').isDirectory()) {
    throw new Error(`Archive runtime directory is required for publisher trust verification: ${runtimeDir}`);
  }
  const packagePath = path.join(runtimeDir, ARCHIVE_SIGNED_PACKAGE);
  verifyPublisherSignature(packagePath);
  const packageInspection = inspectSignedPackage(packagePath, runtimeDir);
  const signedEntries = new Map(
    Array.isArray(packageInspection.entries)
      ? packageInspection.entries.map((entry) => [entry?.name, entry])
      : [],
  );
  for (const name of ['NanaZip.Universal.Console.exe', 'NanaZip.Core.dll', 'NanaZip.Codecs.dll', 'K7Base.dll', 'K7User.dll']) {
    verifyPeX64(path.join(runtimeDir, name));
    const expected = expectedFiles.get(name);
    const signedEntry = signedEntries.get(name);
    if (!signedEntry
      || signedEntry.bytes !== expected[1]
      || signedEntry.sha256 !== expected[2]
      || signedEntry.byteIdentical !== true) {
      throw new Error(`Archive runtime is not byte-identical to its signed MSIX entry: ${name}`);
    }
  }
  const manifest = String(packageInspection.manifest || '');
  for (const identity of [
    'Name="40174MouriNaruto.NanaZip"',
    `Publisher="${ARCHIVE_SIGNER_SUBJECT}"`,
    'Version="7.0.1832.0"',
    'ProcessorArchitecture="x64"',
    'Executable="NanaZip.Universal.Console.exe"',
  ]) {
    if (!manifest.includes(identity)) {
      throw new Error(`Signed NanaZip package identity is missing ${identity}.`);
    }
  }
  if (!Number.isSafeInteger(packageInspection.signaturePartLength)
    || packageInspection.signaturePartLength <= 0
    || packageInspection.signaturePartLength > 256 * 1024) {
    throw new Error('Signed NanaZip package has an invalid AppxSignature.p7x part.');
  }
  return lock;
}

export function verifyExternalToolsLock(lockPath) {
  requireRegularFile(lockPath, 'External tool lock');
  let lock;
  try {
    lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  } catch (error) {
    throw new Error(`External tool lock is invalid JSON: ${error.message}`);
  }
  if (lock?.format !== 'koi-retest-tools-lock-v1'
    || lock.platform !== 'windows-x64'
    || !Array.isArray(lock.artifacts)
    || lock.artifacts.length !== 2) {
    throw new Error('External tool lock has an unexpected format, platform, or artifact count.');
  }
  const reviewed = new Map([
    ['ffuf', {
      version: '2.2.1',
      url: 'https://github.com/ffuf/ffuf/releases/download/v2.2.1/ffuf_2.2.1_windows_amd64.zip',
      size: 4205507,
      sha256: '717e3d103ee36ce743a18605be66a4424fca27758eebed1e8ebb2eb0a3645589',
      archiveFormat: 'zip',
      executable: 'ffuf.exe',
      machine: 'x86_64',
    }],
    ['nmap', {
      version: '7.991',
      url: 'https://nmap.org/dist/nmap-7.991-setup.exe',
      size: 37378768,
      sha256: '93bfd37bdb31a7adfd932beb5dbce06025da691d01a0939e806ea704f7367657',
      archiveFormat: 'nsis',
      executable: 'nmap.exe',
      machine: 'x86',
    }],
  ]);
  const seenTools = new Set();
  for (const artifact of lock.artifacts) {
    const expected = reviewed.get(artifact?.tool);
    if (!expected || seenTools.has(artifact.tool)
      || artifact.version !== expected.version
      || artifact.url !== expected.url
      || artifact.size !== expected.size
      || artifact.sha256 !== expected.sha256
      || artifact.archive_format !== expected.archiveFormat
      || artifact.executable !== expected.executable
      || artifact.executable_machine !== expected.machine
      || typeof artifact.license !== 'string'
      || !artifact.license.trim()
      || !Array.isArray(artifact.files)
      || !artifact.files.length
      || artifact.files.length > 64
      || !Array.isArray(artifact.trees)
      || artifact.trees.length > 8) {
      throw new Error(`External tool provenance is not reviewed: ${artifact?.tool || '<missing>'}`);
    }
    seenTools.add(artifact.tool);
    const archivePaths = new Set();
    const installPaths = new Set();
    let executableCount = 0;
    for (const entry of artifact.files) {
      for (const [label, relative] of [['archive', entry?.archive_path], ['install', entry?.install_path]]) {
      if (typeof relative !== 'string'
          || !relative
          || relative.includes('\\')
          || relative.includes(':')
          || relative.includes('*')
          || relative.includes('?')
          || path.posix.isAbsolute(relative)
          || path.posix.normalize(relative) !== relative
          || relative.split('/').some((part) => !part || part === '.' || part === '..')) {
          throw new Error(`External tool lock contains an unsafe ${label} path: ${relative}`);
        }
      }
      if (entry.archive_path.includes('/') || entry.install_path.includes('/')) {
        throw new Error(`External tool direct product paths must be top-level files: ${artifact.tool}/${entry.install_path}`);
      }
      if (!Number.isSafeInteger(entry.size)
        || entry.size <= 0
        || entry.size > 128 * 1024 * 1024
        || !/^[0-9a-f]{64}$/.test(String(entry.sha256 || ''))
        || typeof entry.role !== 'string'
        || !entry.role
        || archivePaths.has(entry.archive_path)
        || installPaths.has(entry.install_path)) {
        throw new Error(`External tool product inventory is invalid: ${artifact.tool}/${entry?.install_path}`);
      }
      archivePaths.add(entry.archive_path);
      installPaths.add(entry.install_path);
      if (entry.install_path === artifact.executable && entry.role === 'executable') executableCount += 1;
    }
    if (executableCount !== 1) {
      throw new Error(`External tool lock must identify exactly one executable: ${artifact.tool}`);
    }
    const expectedDirectFiles = artifact.tool === 'ffuf'
      ? ['CHANGELOG.md', 'LICENSE', 'README.md', 'ffuf.exe']
      : [
          '3rd-party-licenses.txt', 'CHANGELOG', 'LICENSE', 'README-WIN32',
          'libcrypto-3.dll', 'libssh2.dll', 'libssl-3.dll', 'nmap-mac-prefixes',
          'nmap-os-db', 'nmap-protocols', 'nmap-rpc', 'nmap-service-probes',
          'nmap-services', 'nmap.exe', 'nmap.xsl', 'nse_main.lua', 'zlibwapi.dll',
        ];
    if (installPaths.size !== expectedDirectFiles.length
      || expectedDirectFiles.some((relative) => !installPaths.has(relative))) {
      throw new Error(`External tool direct product inventory is not reviewed: ${artifact.tool}`);
    }
    const treeRoots = new Set();
    for (const tree of artifact.trees) {
      const root = tree?.install_root;
      if (typeof root !== 'string'
        || !root
        || root.includes('/')
        || root.includes('\\')
        || root.includes(':')
        || tree.archive_glob !== `${root}/*`
        || treeRoots.has(root)
        || installPaths.has(root)
        || !Number.isSafeInteger(tree.file_count)
        || tree.file_count <= 0
        || tree.file_count > 2000
        || !Number.isSafeInteger(tree.directory_count)
        || tree.directory_count < 0
        || tree.directory_count > 512
        || !Number.isSafeInteger(tree.total_size)
        || tree.total_size <= 0
        || tree.total_size > 128 * 1024 * 1024
        || !/^[0-9a-f]{64}$/.test(String(tree.manifest_sha256 || ''))
        || typeof tree.role !== 'string'
        || !tree.role) {
        throw new Error(`External tool product tree is invalid: ${artifact.tool}/${root}`);
      }
      treeRoots.add(root);
    }
    if (artifact.tool === 'ffuf' && treeRoots.size !== 0) {
      throw new Error('ffuf product lock must not contain directory trees.');
    }
    if (artifact.tool === 'nmap'
      && (treeRoots.size !== 2 || !treeRoots.has('nselib') || !treeRoots.has('scripts'))) {
      throw new Error('nmap product lock must contain exactly nselib and scripts trees.');
    }
    if (artifact.tool === 'nmap') {
      const nselib = artifact.trees.find((tree) => tree.install_root === 'nselib');
      const scripts = artifact.trees.find((tree) => tree.install_root === 'scripts');
      if (nselib.file_count !== 186
        || nselib.directory_count !== 3
        || nselib.total_size !== 8223140
        || nselib.manifest_sha256 !== '3b405a9f40dbc985c40c7fc5a5a20a8d76f5a19ac3f1d3562660398ef3842b6b'
        || scripts.file_count !== 612
        || scripts.directory_count !== 0
        || scripts.total_size !== 3895325
        || scripts.manifest_sha256 !== '740f923b6d74000195400302790adb9a57dab92a4db6ffd3d943c6a21a696085') {
        throw new Error('nmap product tree fingerprints are not reviewed.');
      }
    }
  }
  if (seenTools.size !== reviewed.size) {
    throw new Error('External tool lock must contain exactly nmap and ffuf.');
  }
  return lock;
}
