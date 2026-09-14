import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  verifyArchiveRuntimeProvenance,
  verifyLockedRuntime,
} from './locked-runtime.mjs';
import {
  assertPinnedReleaseVersion,
  createSupplyChainInputs,
  normalizeFullSourceRevision,
  readReleaseVersions,
  requireRealDirectory,
  requireRegularFile,
  resolveStrictSourceRevision,
  sha256File,
  validateRustOnlyContract,
  verifyPortableArchive,
} from './release-gates.mjs';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', '4.0.0');
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();
const strictRelease = process.env.KOI_RELEASE_STRICT !== '0';
const requestedSourceRevision = String(process.env.GITHUB_SHA || process.env.KOI_SOURCE_REVISION || '').trim();

const version = strictRelease
  ? assertPinnedReleaseVersion(projectRoot, expectedVersion)
  : readReleaseVersions(projectRoot).cargo;
if (!strictRelease && expectedVersion && version !== expectedVersion) {
  throw new Error(`Expected KOI ${expectedVersion}, found ${version}.`);
}
const sourceRevision = strictRelease
  ? resolveStrictSourceRevision(projectRoot, requestedSourceRevision)
  : (requestedSourceRevision ? normalizeFullSourceRevision(requestedSourceRevision) : null);
if (strictRelease) validateRustOnlyContract(projectRoot);

requireRealDirectory(releaseBase, 'Release base');
const appDir = path.join(releaseBase, 'koi');
const dataDir = path.join(releaseBase, 'koi-data');
const releaseManifestPath = path.join(releaseBase, 'release-manifest.json');
const portableMarkerPath = path.join(releaseBase, 'koi-portable.marker');
const portable = path.join(releaseBase, `koi-v${version}-windows-x64-portable.zip`);
const installer = path.join(releaseBase, `koi-v${version}-windows-x64-setup.exe`);
requireRegularFile(releaseManifestPath, 'Release manifest');
requireRegularFile(portableMarkerPath, 'Portable marker');
requireRegularFile(portable, 'Portable archive');
if (strictRelease || process.env.KOI_REQUIRE_NSIS === '1') {
  requireRegularFile(installer, 'NSIS installer');
}

let releaseManifest;
let portableMarker;
try {
  releaseManifest = JSON.parse(fs.readFileSync(releaseManifestPath, 'utf8'));
  portableMarker = JSON.parse(fs.readFileSync(portableMarkerPath, 'utf8'));
} catch (error) {
  throw new Error(`Release manifest or portable marker is invalid JSON: ${error.message}`);
}
if (releaseManifest.format !== 'koi-portable-v1'
  || releaseManifest.version !== version
  || releaseManifest.sourceRevision !== sourceRevision
  || releaseManifest.pythonBusinessBackend !== false
  || portableMarker.format !== 'koi-portable-v1'
  || portableMarker.version !== version
  || portableMarker.sourceRevision !== sourceRevision) {
  throw new Error('Release tree is not stamped with the exact build source revision and Rust-only version metadata.');
}

verifyPortableArchive(portable, {
  releaseManifestPath,
  portableMarkerPath,
  expectedTrees: strictRelease ? [
    { prefix: 'koi', root: appDir },
    { prefix: 'koi-data', root: dataDir },
  ] : [],
});

const artifactPaths = [portable];
if (fs.existsSync(installer)) artifactPaths.push(installer);
if (strictRelease && artifactPaths.length !== 2) {
  throw new Error('Strict KOI finalization requires both the portable ZIP and per-user NSIS installer.');
}
const artifacts = artifactPaths.map((filePath) => {
  const stat = requireRegularFile(filePath, 'Release artifact');
  if (!stat.size) throw new Error(`Release artifact is empty: ${filePath}`);
  return {
    file: path.basename(filePath),
    bytes: stat.size,
    sha256: sha256File(filePath),
  };
});

const inputs = createSupplyChainInputs(projectRoot);
const archiveLockPath = path.join(projectRoot, 'archive-runtime.lock.json');
const archiveRuntimeDir = path.join(projectRoot, 'archive-runtime');
const archiveLock = verifyLockedRuntime({
  lockPath: archiveLockPath,
  runtimeDir: archiveRuntimeDir,
  expectedFormat: 'koi-archive-runtime-v3',
});
verifyArchiveRuntimeProvenance(archiveLock, archiveRuntimeDir);

const manifest = {
  format: 'koi-supply-chain-v1',
  product: 'koi',
  version,
  platform: 'windows-x64',
  sourceRevision,
  // Kept for consumers of the previous v1 shape. It is the same full object
  // ID, not a separate or abbreviated build identifier.
  commit: sourceRevision,
  rustToolchain: String(process.env.RUSTUP_TOOLCHAIN || 'stable'),
  node: process.version,
  pythonBusinessBackend: false,
  runtimeTrust: {
    archiveRuntime: {
      model: archiveLock.trust.model,
      publisherAuthenticated: true,
      publisherSignature: archiveLock.trust.publisher_signature,
      packageIdentity: archiveLock.trust.package_identity,
      reviewedAt: archiveLock.trust.reviewed_at,
      runtimeBinding: archiveLock.trust.publisher_signature.runtime_binding,
    },
  },
  inputs,
  artifacts,
};

const sums = `${artifacts.map((artifact) => `${artifact.sha256}  ${artifact.file}`).join('\n')}\n`;
for (const [destination, contents, encoding] of [
  [path.join(releaseBase, 'SHA256SUMS'), sums, 'ascii'],
  [path.join(releaseBase, 'supply-chain.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8'],
]) {
  const temporary = `${destination}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(temporary, contents, { encoding, flag: 'wx' });
  if (fs.existsSync(destination)) requireRegularFile(destination, 'Existing finalized metadata');
  fs.rmSync(destination, { force: true });
  fs.renameSync(temporary, destination);
}

console.log(
  `Finalized ${artifacts.length} KOI ${version} artifact(s) from ${sourceRevision || '<unstamped development tree>'} `
  + `in ${releaseBase}.`,
);
