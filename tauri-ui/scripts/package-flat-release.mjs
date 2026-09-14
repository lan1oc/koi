import crypto from 'node:crypto';
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
  assertArtifactBuiltAfterStamp,
  assertGitTrackedInputs,
  assertPinnedReleaseVersion,
  cargoTargetCandidates,
  readBuildSourceStamp,
  readReleaseVersions,
  resolveStrictSourceRevision,
  validateRustOnlyContract,
} from './release-gates.mjs';

const uiDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(uiDir, '..', '..');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', '4.0.0');
const outputDir = path.join(releaseBase, 'koi');
const dataDir = path.join(releaseBase, 'koi-data');
const seedDir = path.join(outputDir, 'seed');
const strictRelease = process.env.KOI_RELEASE_STRICT !== '0';
const configuredCargoTarget = String(process.env.CARGO_TARGET_DIR || '').trim();
if (strictRelease && configuredCargoTarget && !path.isAbsolute(configuredCargoTarget)) {
  throw new Error('Strict release requires CARGO_TARGET_DIR to be absolute when explicitly configured.');
}
const resolvedCargoTargetCandidates = cargoTargetCandidates(projectRoot, configuredCargoTarget);
const cargoTargetDir = resolvedCargoTargetCandidates[0];
const releaseDir = path.join(
  resolvedCargoTargetCandidates.find((candidate) => fs.existsSync(path.join(candidate, 'release'))) || cargoTargetDir,
  'release',
);
const cargoTomlPath = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml');
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();
const requestedSourceRevision = String(process.env.GITHUB_SHA || process.env.KOI_SOURCE_REVISION || '').trim();
const probeLockSource = path.join(projectRoot, 'probe-runtime.lock.json');
const probeRuntimeSource = path.join(projectRoot, 'probe-runtime');
const probeWheelsLockSource = path.join(projectRoot, 'probe-wheels.lock.json');
const pdfiumLockSource = path.join(projectRoot, 'pdfium-runtime.lock.json');
const pdfiumRuntimeSource = path.join(projectRoot, 'pdfium-runtime');
const archiveLockSource = path.join(projectRoot, 'archive-runtime.lock.json');
const archiveRuntimeSource = path.join(projectRoot, 'archive-runtime');
const externalToolsLockSource = path.join(
  projectRoot,
  'tauri-ui',
  'src-tauri',
  'src',
  'backend',
  'external_tools.lock.json',
);
let verifiedPdfiumLock = null;
let verifiedArchiveLock = null;
let verifiedExternalToolsLock = null;
let verifiedProbeLock = null;
let strictBuildStamp = null;

const frontendExeCandidates = [
  path.join(releaseDir, 'koi-tauri.exe'),
  path.join(releaseDir, 'koi.exe'),
];

function relativeLabel(target) {
  return path.relative(projectRoot, target) || target;
}

function readAppVersion() {
  if (strictRelease) return assertPinnedReleaseVersion(projectRoot, expectedVersion);
  const version = readReleaseVersions(projectRoot).cargo;
  if (expectedVersion && version !== expectedVersion) {
    throw new Error(`Expected KOI version ${expectedVersion}, found ${version} in ${cargoTomlPath}`);
  }
  return version;
}

function firstExisting(candidates, label) {
  const existing = candidates.find((candidate) => fs.existsSync(candidate));
  if (!existing) {
    throw new Error(`Missing required ${label}. Checked:\n${candidates.join('\n')}`);
  }
  return existing;
}

function copyEntry(source, destination, options = {}) {
  const { force = true } = options;
  const sourceStat = fs.lstatSync(source, { throwIfNoEntry: false });
  if (!sourceStat) {
    throw new Error(`Missing required release resource: ${source}`);
  }
  if (sourceStat.isSymbolicLink()) {
    throw new Error(`Release resource must not be a symbolic link: ${source}`);
  }
  if (path.resolve(source) === path.resolve(destination)) {
    return;
  }
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.cpSync(source, destination, { recursive: true, force, errorOnExist: false });
}

function rejectReparseEntry(target, label) {
  const stat = fs.lstatSync(target, { throwIfNoEntry: false });
  if (stat?.isSymbolicLink()) {
    throw new Error(`${label} must not be a symbolic link: ${target}`);
  }
  return stat;
}

function replaceImmutableEntry(source, destination, label) {
  fs.rmSync(destination, { recursive: true, force: true });
  if (!fs.existsSync(source)) return;
  copyEntry(source, destination, { force: true });
  console.log(`Refreshed immutable ${label}: ${relativeLabel(destination)}`);
}

function copyIfMissing(source, destination, label) {
  if (fs.existsSync(destination)) {
    console.log(`Preserved existing ${label}: ${relativeLabel(destination)}`);
    return;
  }
  copyEntry(source, destination, { force: false });
  console.log(`Seeded ${label}: ${relativeLabel(destination)}`);
}

function ensureDirectory(destination, label) {
  if (fs.existsSync(destination)) {
    const destinationStat = rejectReparseEntry(destination, label);
    if (!destinationStat.isDirectory()) {
      throw new Error(`${label} is not a directory: ${destination}`);
    }
    console.log(`Preserved existing ${label}: ${relativeLabel(destination)}`);
    return;
  }
  fs.mkdirSync(destination, { recursive: true });
  console.log(`Seeded empty ${label}: ${relativeLabel(destination)}`);
}

function ensureFile(destination, label) {
  if (fs.existsSync(destination)) {
    const destinationStat = rejectReparseEntry(destination, label);
    if (!destinationStat.isFile()) {
      throw new Error(`${label} is not a file: ${destination}`);
    }
    console.log(`Preserved existing ${label}: ${relativeLabel(destination)}`);
    return;
  }
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, '');
  console.log(`Seeded empty ${label}: ${relativeLabel(destination)}`);
}

function mergeDefaults(source, destination, label) {
  if (!fs.existsSync(source)) {
    return;
  }
  if (fs.existsSync(destination)) {
    const destinationStat = rejectReparseEntry(destination, label);
    if (!destinationStat.isDirectory()) {
      throw new Error(`${label} destination is not a directory: ${destination}`);
    }
    fs.cpSync(source, destination, { recursive: true, force: false, errorOnExist: false });
    console.log(`Merged missing ${label} defaults: ${relativeLabel(destination)}`);
    return;
  }
  copyEntry(source, destination, { force: false });
  console.log(`Seeded ${label}: ${relativeLabel(destination)}`);
}

function removeConfigVersion(configPath) {
  if (!fs.existsSync(configPath)) {
    return;
  }
  let config;
  try {
    config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  } catch (error) {
    throw new Error(`Failed to read config for migration: ${configPath}\n${error.message}`);
  }
  if (!config?.app || !Object.prototype.hasOwnProperty.call(config.app, 'version')) {
    return;
  }
  delete config.app.version;
  fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
  console.log(`Removed app.version from config: ${relativeLabel(configPath)}`);
}

function migrateLegacyUserData() {
  fs.mkdirSync(dataDir, { recursive: true });
  const legacyBase = path.join(projectRoot, 'dist-tauri');
  const legacyLocations = [
    path.join(legacyBase, '4.0.0', 'koi-data'),
    path.join(legacyBase, 'koi-data'),
    path.join(legacyBase, 'koi'),
  ];
  for (const legacyRoot of legacyLocations) {
    if (!fs.existsSync(legacyRoot) || path.resolve(legacyRoot) === path.resolve(dataDir)) {
      continue;
    }
    for (const relativePath of ['config.json', 'enterprise_classification.db', 'Report_Template', 'templates', '.koi_agent_sessions', '.retest-control']) {
      const source = path.join(legacyRoot, relativePath);
      const destination = path.join(dataDir, relativePath);
      if (fs.existsSync(source) && !fs.existsSync(destination)) {
        copyEntry(source, destination, { force: false });
        console.log(`Migrated existing user data: ${relativeLabel(source)} -> ${relativeLabel(destination)}`);
      }
    }
  }
}

function removeLegacyReleaseEntries() {
  for (const name of ['koi.exe', 'koi-tauri.exe', 'koi-backend.exe', 'koi-backend']) {
    fs.rmSync(path.join(outputDir, name), { recursive: true, force: true });
  }
}

function refreshImmutableSeeds() {
  fs.rmSync(seedDir, { recursive: true, force: true });
  copyEntry(path.join(projectRoot, 'Report_Template'), path.join(seedDir, 'Report_Template'));
  copyEntry(
    path.join(projectRoot, 'modules', 'data_processing', 'templates'),
    path.join(seedDir, 'templates'),
  );
  copyEntry(
    path.join(projectRoot, 'enterprise_classification.db'),
    path.join(seedDir, 'enterprise_classification.db'),
  );
}

function assertRustOnlyAppTree() {
  const forbidden = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const stat = fs.lstatSync(fullPath);
      const lower = entry.name.toLowerCase();
      if (stat.isSymbolicLink()
        || lower.startsWith('koi-backend')
        || lower.includes('pyinstaller')
        || lower.endsWith('.py')
        || lower.endsWith('.pyc')
        || lower.endsWith('.pyo')
        || lower === '__pycache__') {
        forbidden.push(relativeLabel(fullPath));
        continue;
      }
      if (stat.isDirectory()) {
        visit(fullPath);
      }
    }
  };
  visit(outputDir);
  if (forbidden.length) {
    throw new Error(`Rust-only release contains forbidden Python backend artifacts:\n${forbidden.join('\n')}`);
  }
}

function writeManifest(appVersion, sourceRevision) {
  const executablePath = path.join(outputDir, 'koi.exe');
  const digest = crypto.createHash('sha256').update(fs.readFileSync(executablePath)).digest('hex');
  const manifest = {
    format: 'koi-portable-v1',
    product: 'koi',
    version: appVersion,
    platform: 'windows-x64',
    executable: 'koi/koi.exe',
    executableSha256: digest,
    userDataDirectory: 'koi-data',
    sourceRevision,
    pythonBusinessBackend: false,
    pdfiumRuntime: verifiedPdfiumLock ? {
      version: verifiedPdfiumLock.version,
      chromiumBranch: verifiedPdfiumLock.chromium_branch,
      archiveSha256: verifiedPdfiumLock.source.archive_sha256,
    } : null,
    archiveRuntime: verifiedArchiveLock ? {
      version: verifiedArchiveLock.version,
      engineVersion: verifiedArchiveLock.engine_version,
      releaseAssetSha256: verifiedArchiveLock.source.release_asset_sha256,
      signedPackageSha256: verifiedArchiveLock.source.signed_package_sha256,
      trustModel: verifiedArchiveLock.trust.model,
      publisherAuthenticated: verifiedArchiveLock.trust.publisher_authenticated,
      publisherSignature: verifiedArchiveLock.trust.publisher_signature,
    } : null,
    externalTools: verifiedExternalToolsLock ? Object.fromEntries(
      verifiedExternalToolsLock.artifacts.map((artifact) => [artifact.tool, {
        version: artifact.version,
        artifactSha256: artifact.sha256,
      }]),
    ) : null,
  };
  fs.writeFileSync(path.join(releaseBase, 'release-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
  fs.writeFileSync(
    path.join(releaseBase, 'koi-portable.marker'),
    `${JSON.stringify({
      format: manifest.format,
      version: appVersion,
      dataDirectory: manifest.userDataDirectory,
      sourceRevision,
    }, null, 2)}\n`,
    'utf8',
  );
}

const appVersion = readAppVersion();
const sourceRevision = strictRelease
  ? resolveStrictSourceRevision(projectRoot, requestedSourceRevision)
  : (requestedSourceRevision || null);
if (strictRelease) {
  validateRustOnlyContract(projectRoot);
  assertGitTrackedInputs(projectRoot, [
    'Report_Template',
    'archive-runtime',
    'archive-runtime.lock.json',
    'enterprise_classification.db',
    'modules/data_processing/templates',
    'pdfium-runtime',
    'pdfium-runtime.lock.json',
    'probe-runtime',
    'probe-runtime.lock.json',
    'probe-wheels.lock.json',
    'tauri-ui/src-tauri/src/backend/external_tools.lock.json',
  ]);
  strictBuildStamp = readBuildSourceStamp(projectRoot, sourceRevision, configuredCargoTarget);
  if (path.resolve(strictBuildStamp.targetDirectory) !== path.resolve(path.dirname(releaseDir))) {
    throw new Error(
      `Rust release binary directory ${releaseDir} does not belong to the stamped Cargo target ${strictBuildStamp.targetDirectory}.`,
    );
  }
}
if (strictRelease && (
  !fs.existsSync(probeLockSource)
  || !fs.statSync(probeRuntimeSource, { throwIfNoEntry: false })?.isDirectory()
  || !fs.existsSync(probeWheelsLockSource)
  || !fs.existsSync(pdfiumLockSource)
  || !fs.statSync(pdfiumRuntimeSource, { throwIfNoEntry: false })?.isDirectory()
  || !fs.existsSync(archiveLockSource)
  || !fs.statSync(archiveRuntimeSource, { throwIfNoEntry: false })?.isDirectory()
  || !fs.existsSync(externalToolsLockSource)
)) {
  throw new Error(
    'Rust-only production release requires locked probe runtime, probe wheel policy, PDFium, archive runtime, and external tools. ' +
      'Use KOI_RELEASE_STRICT=0 only for migration/differential builds.',
  );
}
if (fs.existsSync(pdfiumLockSource) && fs.existsSync(pdfiumRuntimeSource)) {
  verifiedPdfiumLock = verifyLockedRuntime({
    lockPath: pdfiumLockSource,
    runtimeDir: pdfiumRuntimeSource,
    expectedFormat: 'koi-pdfium-runtime-v1',
  });
}
if (fs.existsSync(probeLockSource) && fs.existsSync(probeRuntimeSource)) {
  verifiedProbeLock = verifyProbeRuntime({
    lockPath: probeLockSource,
    runtimeDir: probeRuntimeSource,
  });
}
if (fs.existsSync(archiveLockSource) && fs.existsSync(archiveRuntimeSource)) {
  verifiedArchiveLock = verifyLockedRuntime({
    lockPath: archiveLockSource,
    runtimeDir: archiveRuntimeSource,
    expectedFormat: 'koi-archive-runtime-v3',
  });
  verifyArchiveRuntimeProvenance(verifiedArchiveLock, archiveRuntimeSource);
}
if (fs.existsSync(externalToolsLockSource)) {
  verifiedExternalToolsLock = verifyExternalToolsLock(externalToolsLockSource);
}
if (strictRelease && !verifiedProbeLock) {
  throw new Error('Strict release packaging requires the verified CPython probe runtime.');
}
if (strictRelease && fs.existsSync(releaseBase) && fs.readdirSync(releaseBase).length) {
  throw new Error(
    `Strict release packaging requires an empty release base: ${releaseBase}. `
    + 'Use a new output directory so stale binaries or private state cannot enter the artifact.',
  );
}
fs.mkdirSync(releaseBase, { recursive: true });
rejectReparseEntry(releaseBase, 'release base');
if (fs.existsSync(outputDir)) rejectReparseEntry(outputDir, 'application output directory');
if (fs.existsSync(dataDir)) rejectReparseEntry(dataDir, 'user data directory');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(dataDir, { recursive: true });
if (!strictRelease || process.env.KOI_MIGRATE_LEGACY_RELEASE_DATA === '1') {
  migrateLegacyUserData();
}
removeLegacyReleaseEntries();

const frontendExecutable = firstExisting(frontendExeCandidates, 'Rust/Tauri application executable');
if (strictBuildStamp) {
  assertArtifactBuiltAfterStamp(frontendExecutable, strictBuildStamp.stampPath, 'Rust application executable');
}
copyEntry(frontendExecutable, path.join(outputDir, 'koi.exe'));
fs.writeFileSync(path.join(outputDir, 'version.txt'), `${appVersion}\n`, 'utf8');
refreshImmutableSeeds();

mergeDefaults(path.join(seedDir, 'Report_Template'), path.join(dataDir, 'Report_Template'), 'report template');
ensureDirectory(path.join(dataDir, 'Report_Template'), 'report template directory');
mergeDefaults(path.join(seedDir, 'templates'), path.join(dataDir, 'templates'), 'data template');
ensureDirectory(path.join(dataDir, 'templates'), 'data template directory');
mergeDefaults(path.join(projectRoot, 'retest_external_tools'), path.join(outputDir, 'retest_external_tools'), 'retest external tools');
ensureDirectory(path.join(outputDir, 'retest_external_tools'), 'retest external tools directory');

copyIfMissing(
  path.join(seedDir, 'enterprise_classification.db'),
  path.join(dataDir, 'enterprise_classification.db'),
  'enterprise classification database',
);

// The probe runtime is optional during migration, but when present it is
// copied as an immutable application resource and never used as a business
// backend fallback.
replaceImmutableEntry(probeLockSource, path.join(outputDir, 'probe-runtime.lock.json'), 'probe runtime lock');
replaceImmutableEntry(probeRuntimeSource, path.join(outputDir, 'probe-runtime'), 'probe runtime');
replaceImmutableEntry(probeWheelsLockSource, path.join(outputDir, 'probe-wheels.lock.json'), 'probe wheel lock');
replaceImmutableEntry(pdfiumLockSource, path.join(outputDir, 'pdfium-runtime.lock.json'), 'PDFium runtime lock');
replaceImmutableEntry(pdfiumRuntimeSource, path.join(outputDir, 'pdfium-runtime'), 'PDFium runtime');
replaceImmutableEntry(archiveLockSource, path.join(outputDir, 'archive-runtime.lock.json'), 'archive runtime lock');
replaceImmutableEntry(archiveRuntimeSource, path.join(outputDir, 'archive-runtime'), 'archive runtime');
replaceImmutableEntry(
  externalToolsLockSource,
  path.join(outputDir, 'external_tools.lock.json'),
  'external tool lock',
);

removeConfigVersion(path.join(dataDir, 'config.json'));
removeConfigVersion(path.join(outputDir, 'config.json'));
assertRustOnlyAppTree();
if (strictRelease) {
  assertCleanReleaseTree(outputDir, { label: 'Packaged application tree' });
  assertCleanReleaseTree(dataDir, { label: 'Packaged portable data tree' });
}
writeManifest(appVersion, sourceRevision);

console.log(`Portable KOI ${appVersion} prepared at: ${releaseBase}`);
console.log(`Application: ${outputDir}`);
console.log(`User data preserved at: ${dataDir}`);
