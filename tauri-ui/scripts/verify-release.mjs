import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  verifyArchiveRuntimeProvenance,
  verifyExternalToolsLock,
  verifyLockedRuntime,
  verifyProbeRuntime,
} from './locked-runtime.mjs';
import {
  assertCleanReleaseTree,
  assertPinnedReleaseVersion,
  normalizeFullSourceRevision,
  readReleaseVersions,
  requireRealDirectory,
  requireRegularFile,
  resolveStrictSourceRevision,
  sha256File,
  validateRustOnlyContract,
  verifyPortableArchive,
  verifySupplyChainInputs,
} from './release-gates.mjs';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', '4.0.0');
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();
const strictRelease = process.env.KOI_RELEASE_STRICT !== '0';
const requireSupplyChain = process.env.KOI_REQUIRE_SUPPLY_CHAIN === '1';
const requireNsis = process.env.KOI_REQUIRE_NSIS === '1';
const requestedSourceRevision = String(process.env.GITHUB_SHA || process.env.KOI_SOURCE_REVISION || '').trim();
const version = strictRelease
  ? assertPinnedReleaseVersion(projectRoot, expectedVersion)
  : readReleaseVersions(projectRoot).cargo;
if (!strictRelease && expectedVersion && version !== expectedVersion) {
  throw new Error(`Expected KOI ${expectedVersion}, found ${version}.`);
}
const checkoutRevision = strictRelease
  ? resolveStrictSourceRevision(projectRoot, requestedSourceRevision)
  : (requestedSourceRevision ? normalizeFullSourceRevision(requestedSourceRevision) : null);
const registry = validateRustOnlyContract(projectRoot);

function parseJson(filePath, label) {
  requireRegularFile(filePath, label);
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    throw new Error(`${label} is invalid JSON: ${error.message}`);
  }
}

function verifyProbeWheelLock(filePath) {
  const lock = parseJson(filePath, 'Embedded probe wheel lock');
  if (lock.format !== 'koi-probe-wheels-v1'
    || lock.source !== 'https://pypi.org/simple'
    || !Array.isArray(lock.roots)
    || !Array.isArray(lock.packages)
    || lock.packages.length > 512) {
    throw new Error('Embedded probe wheel lock has an unexpected format, source, or package count.');
  }
  const names = new Set();
  for (const packageEntry of lock.packages) {
    if (!packageEntry || typeof packageEntry.name !== 'string'
      || typeof packageEntry.version !== 'string'
      || !Array.isArray(packageEntry.dependencies)
      || !Array.isArray(packageEntry.imports)
      || !packageEntry.wheel || typeof packageEntry.wheel.filename !== 'string'
      || typeof packageEntry.wheel.url !== 'string'
      || !Number.isSafeInteger(packageEntry.wheel.size) || packageEntry.wheel.size <= 0
      || !/^[0-9a-f]{64}$/.test(String(packageEntry.wheel.sha256 || ''))) {
      throw new Error(`Embedded probe wheel lock has invalid package metadata: ${JSON.stringify(packageEntry)}`);
    }
    const name = packageEntry.name.trim().toLowerCase().replaceAll(/[._-]+/g, '-');
    if (!name || names.has(name)) throw new Error(`Embedded probe wheel lock has a duplicate package: ${packageEntry.name}`);
    names.add(name);
    if (!packageEntry.wheel.filename.toLowerCase().endsWith('.whl')
      || packageEntry.wheel.filename.includes('/') || packageEntry.wheel.filename.includes('\\')) {
      throw new Error(`Embedded probe wheel lock has an unsafe wheel filename: ${packageEntry.wheel.filename}`);
    }
    const wheelUrl = new URL(packageEntry.wheel.url);
    if (wheelUrl.protocol !== 'https:' || wheelUrl.hostname !== 'files.pythonhosted.org'
      || path.posix.basename(wheelUrl.pathname) !== packageEntry.wheel.filename) {
      throw new Error(`Embedded probe wheel lock has an untrusted wheel URL: ${packageEntry.wheel.url}`);
    }
    if (packageEntry.source_distribution != null) {
      const source = packageEntry.source_distribution;
      if (typeof source.filename !== 'string' || !source.filename.toLowerCase().match(/\.(tar\.gz|zip)$/)
        || typeof source.url !== 'string' || !/^[0-9a-f]{64}$/.test(String(source.sha256 || ''))
        || !Number.isSafeInteger(source.size) || source.size <= 0) {
        throw new Error(`Embedded probe wheel lock has invalid source metadata: ${packageEntry.name}`);
      }
      const sourceUrl = new URL(source.url);
      if (sourceUrl.protocol !== 'https:' || sourceUrl.hostname !== 'files.pythonhosted.org'
        || path.posix.basename(sourceUrl.pathname) !== source.filename) {
        throw new Error(`Embedded probe wheel lock has an untrusted source URL: ${source.url}`);
      }
    }
    if (packageEntry.source_build != null) {
      const build = packageEntry.source_build;
      if (packageEntry.source_distribution == null
        || typeof build.backend !== 'string'
        || !/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(build.backend)
        || typeof build.source_subdir !== 'string' || build.source_subdir.includes('\\')
        || path.posix.isAbsolute(build.source_subdir)
        || path.posix.normalize(build.source_subdir) !== build.source_subdir
        || build.source_subdir.split('/').some((part) => !part || part === '.' || part === '..' || part.includes(':'))
        || !Array.isArray(build.build_dependencies)) {
        throw new Error(`Embedded probe wheel lock has invalid source-build policy: ${packageEntry.name}`);
      }
    }
  }
  for (const root of lock.roots) {
    if (!names.has(String(root).trim().toLowerCase().replaceAll(/[._-]+/g, '-'))) {
      throw new Error(`Embedded probe wheel root is not locked: ${root}`);
    }
  }
  for (const packageEntry of lock.packages) {
    for (const dependency of [...packageEntry.dependencies, ...(packageEntry.source_build?.build_dependencies || [])]) {
      if (!names.has(String(dependency).trim().toLowerCase().replaceAll(/[._-]+/g, '-'))) {
        throw new Error(`Embedded probe wheel dependency is not locked: ${dependency}`);
      }
    }
  }
  return lock;
}

const appDir = path.join(releaseBase, 'koi');
const dataDir = path.join(releaseBase, 'koi-data');
const releaseManifestPath = path.join(releaseBase, 'release-manifest.json');
const portableMarkerPath = path.join(releaseBase, 'koi-portable.marker');
const portablePath = path.join(releaseBase, `koi-v${version}-windows-x64-portable.zip`);
const installerPath = path.join(releaseBase, `koi-v${version}-windows-x64-setup.exe`);
requireRealDirectory(releaseBase, 'Release base');
requireRealDirectory(appDir, 'Rust application directory');
requireRealDirectory(dataDir, 'Portable data directory');
assertCleanReleaseTree(appDir, { label: 'Rust application directory' });
assertCleanReleaseTree(dataDir, { label: 'Portable data directory' });

for (const [filePath, label] of [
  [path.join(appDir, 'koi.exe'), 'Rust application executable'],
  [path.join(appDir, 'version.txt'), 'Application version marker'],
  [path.join(appDir, 'seed', 'enterprise_classification.db'), 'Immutable database seed'],
]) requireRegularFile(filePath, label);
for (const [directory, label] of [
  [path.join(appDir, 'seed', 'Report_Template'), 'Immutable report-template seed'],
  [path.join(appDir, 'seed', 'templates'), 'Immutable data-template seed'],
]) requireRealDirectory(directory, label);

const versionMarker = fs.readFileSync(path.join(appDir, 'version.txt'), 'utf8').trim();
if (versionMarker !== version) throw new Error(`Application version marker must equal ${version}.`);
const releaseManifest = parseJson(releaseManifestPath, 'Release manifest');
const portableMarker = parseJson(portableMarkerPath, 'Portable marker');
if (releaseManifest.format !== 'koi-portable-v1'
  || releaseManifest.product !== 'koi'
  || releaseManifest.version !== version
  || releaseManifest.platform !== 'windows-x64'
  || releaseManifest.executable !== 'koi/koi.exe'
  || releaseManifest.userDataDirectory !== 'koi-data'
  || releaseManifest.pythonBusinessBackend !== false
  || releaseManifest.sourceRevision !== checkoutRevision
  || releaseManifest.pdfiumRuntime?.version !== '153.0.8009.0'
  || releaseManifest.archiveRuntime?.version !== '7.0.1832.0'
  || releaseManifest.archiveRuntime?.engineVersion !== '2609.1'
  || releaseManifest.archiveRuntime?.releaseAssetSha256 !== '10ce4246ea9efc0dcc7780e676cdcc6c7c74eca0abeb19a5ea76f384d9be2a75'
  || releaseManifest.archiveRuntime?.signedPackageSha256 !== 'df0469573ec269a5bc1dc589a68a19dda3dc8dfe4b4a8d849de81ee42c422e40'
  || releaseManifest.archiveRuntime?.trustModel !== 'publisher-signed-msix-runtime-binding-v1'
  || releaseManifest.archiveRuntime?.publisherAuthenticated !== true
  || releaseManifest.archiveRuntime?.publisherSignature?.package !== 'authenticode-valid'
  || releaseManifest.archiveRuntime?.publisherSignature?.signer_subject !== 'CN=E310A153-74A9-4D81-800B-857A8D58408A'
  || releaseManifest.archiveRuntime?.publisherSignature?.signer_thumbprint !== '6f9e58cdb36763170616b86c419b8bb19e85e86c'
  || releaseManifest.archiveRuntime?.publisherSignature?.runtime_binding !== 'byte-identical-msix-entries'
  || releaseManifest.externalTools?.ffuf?.version !== '2.2.1'
  || releaseManifest.externalTools?.ffuf?.artifactSha256 !== '717e3d103ee36ce743a18605be66a4424fca27758eebed1e8ebb2eb0a3645589'
  || releaseManifest.externalTools?.nmap?.version !== '7.991'
  || releaseManifest.externalTools?.nmap?.artifactSha256 !== '93bfd37bdb31a7adfd932beb5dbce06025da691d01a0939e806ea704f7367657') {
  throw new Error('Release manifest does not describe the exact Rust-only KOI 4.0.0 application.');
}
if (portableMarker.format !== 'koi-portable-v1' || portableMarker.version !== version
  || portableMarker.dataDirectory !== 'koi-data' || portableMarker.sourceRevision !== checkoutRevision) {
  throw new Error('Portable marker does not match the exact build source revision and data layout.');
}
const executableHash = sha256File(path.join(appDir, 'koi.exe'));
if (releaseManifest.executableSha256 !== executableHash) {
  throw new Error('Rust executable hash does not match the release manifest.');
}

verifyProbeRuntime({
  lockPath: path.join(appDir, 'probe-runtime.lock.json'),
  runtimeDir: path.join(appDir, 'probe-runtime'),
});
verifyLockedRuntime({
  lockPath: path.join(appDir, 'pdfium-runtime.lock.json'),
  runtimeDir: path.join(appDir, 'pdfium-runtime'),
  expectedFormat: 'koi-pdfium-runtime-v1',
});
const archiveLock = verifyLockedRuntime({
  lockPath: path.join(appDir, 'archive-runtime.lock.json'),
  runtimeDir: path.join(appDir, 'archive-runtime'),
  expectedFormat: 'koi-archive-runtime-v3',
});
verifyArchiveRuntimeProvenance(archiveLock, path.join(appDir, 'archive-runtime'));
verifyProbeWheelLock(path.join(appDir, 'probe-wheels.lock.json'));
verifyExternalToolsLock(path.join(appDir, 'external_tools.lock.json'));

if (fs.existsSync(portablePath) || requireSupplyChain) {
  requireRegularFile(portablePath, 'Portable archive');
  verifyPortableArchive(portablePath, {
    releaseManifestPath,
    portableMarkerPath,
    expectedTrees: strictRelease ? [
      { prefix: 'koi', root: appDir },
      { prefix: 'koi-data', root: dataDir },
    ] : [],
  });
}
if (requireNsis) requireRegularFile(installerPath, 'NSIS installer');

const supplyChainPath = path.join(releaseBase, 'supply-chain.json');
if (fs.existsSync(supplyChainPath)) {
  const supplyChain = parseJson(supplyChainPath, 'Supply-chain manifest');
  const sourceRevision = checkoutRevision
    ? normalizeFullSourceRevision(supplyChain.sourceRevision, checkoutRevision)
    : null;
  if (supplyChain.format !== 'koi-supply-chain-v1'
    || supplyChain.product !== 'koi'
    || supplyChain.version !== version
    || supplyChain.platform !== 'windows-x64'
    || supplyChain.sourceRevision !== sourceRevision
    || supplyChain.commit !== sourceRevision
    || supplyChain.pythonBusinessBackend !== false
    || supplyChain.runtimeTrust?.archiveRuntime?.model !== 'publisher-signed-msix-runtime-binding-v1'
    || supplyChain.runtimeTrust?.archiveRuntime?.publisherAuthenticated !== true
    || supplyChain.runtimeTrust?.archiveRuntime?.publisherSignature?.package !== 'authenticode-valid'
    || supplyChain.runtimeTrust?.archiveRuntime?.publisherSignature?.signer_subject !== 'CN=E310A153-74A9-4D81-800B-857A8D58408A'
    || supplyChain.runtimeTrust?.archiveRuntime?.publisherSignature?.signer_thumbprint !== '6f9e58cdb36763170616b86c419b8bb19e85e86c'
    || supplyChain.runtimeTrust?.archiveRuntime?.runtimeBinding !== 'byte-identical-msix-entries'
    || supplyChain.runtimeTrust?.archiveRuntime?.packageIdentity?.name !== '40174MouriNaruto.NanaZip') {
    throw new Error('Supply-chain manifest is missing exact source revision or publisher-signed runtime metadata.');
  }
  verifySupplyChainInputs(projectRoot, supplyChain.inputs);

  const finalRequiresNsis = requireNsis || strictRelease;
  const requiredArtifactNames = [
    `koi-v${version}-windows-x64-portable.zip`,
    ...(finalRequiresNsis ? [`koi-v${version}-windows-x64-setup.exe`] : []),
  ];
  if (!Array.isArray(supplyChain.artifacts)
    || supplyChain.artifacts.length !== requiredArtifactNames.length) {
    throw new Error('Supply-chain artifact inventory has an unexpected length.');
  }
  const artifacts = new Map();
  for (const artifact of supplyChain.artifacts) {
    if (!artifact || typeof artifact.file !== 'string' || path.basename(artifact.file) !== artifact.file
      || artifacts.has(artifact.file) || !Number.isSafeInteger(artifact.bytes) || artifact.bytes <= 0
      || !/^[0-9a-f]{64}$/.test(String(artifact.sha256 || ''))) {
      throw new Error('Supply-chain artifact inventory contains invalid metadata.');
    }
    artifacts.set(artifact.file, artifact);
  }
  if (requiredArtifactNames.some((name) => !artifacts.has(name))) {
    throw new Error('Supply-chain manifest does not contain every required release artifact.');
  }

  const sumsPath = path.join(releaseBase, 'SHA256SUMS');
  requireRegularFile(sumsPath, 'SHA256SUMS');
  const sums = new Map();
  for (const line of fs.readFileSync(sumsPath, 'ascii').split(/\r?\n/).filter(Boolean)) {
    const match = line.match(/^([0-9a-f]{64})  ([^/\\]+)$/);
    if (!match || sums.has(match[2])) throw new Error('SHA256SUMS contains an invalid or duplicate entry.');
    sums.set(match[2], match[1]);
  }
  if (sums.size !== artifacts.size) throw new Error('SHA256SUMS does not match the supply-chain artifact inventory.');
  for (const [name, artifact] of artifacts) {
    const artifactPath = path.join(releaseBase, name);
    const stat = requireRegularFile(artifactPath, `Release artifact ${name}`);
    const actualHash = sha256File(artifactPath);
    if (stat.size !== artifact.bytes || actualHash !== artifact.sha256 || sums.get(name) !== actualHash) {
      throw new Error(`Release artifact hash or size does not match supply-chain metadata: ${name}`);
    }
  }
} else if (requireSupplyChain) {
  throw new Error(`Missing finalized supply-chain manifest: ${supplyChainPath}`);
}

console.log(
  `Release verification passed: KOI ${version}, ${registry.handlerCount}/${registry.commandCount} Rust handlers, `
  + `source ${checkoutRevision || '<development>'}.`,
);
