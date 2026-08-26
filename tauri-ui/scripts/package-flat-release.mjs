import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  verifyArchiveRuntimeProvenance,
  verifyExternalToolsLock,
  verifyLockedRuntime,
} from './locked-runtime.mjs';

const uiDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(uiDir, '..', '..');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', '4.0.0');
const outputDir = path.join(releaseBase, 'koi');
const dataDir = path.join(releaseBase, 'koi-data');
const seedDir = path.join(outputDir, 'seed');
const configuredCargoTarget = String(process.env.CARGO_TARGET_DIR || '').trim();
const cargoTargetDir = configuredCargoTarget
  ? path.resolve(projectRoot, configuredCargoTarget)
  : path.join(projectRoot, 'tauri-ui', 'src-tauri', 'target');
// Cargo resolves a relative target directory from `src-tauri`, while this
// script runs from the UI package. Accept the common relative form without
// silently looking in a different directory than the compiler used.
const cargoTargetCandidates = configuredCargoTarget && !path.isAbsolute(configuredCargoTarget)
  ? [
      path.resolve(projectRoot, configuredCargoTarget),
      path.resolve(projectRoot, 'tauri-ui', 'src-tauri', configuredCargoTarget),
    ]
  : [cargoTargetDir];
const releaseDir = path.join(
  cargoTargetCandidates.find((candidate) => fs.existsSync(path.join(candidate, 'release'))) || cargoTargetDir,
  'release',
);
const cargoTomlPath = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml');
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();
const strictRelease = process.env.KOI_RELEASE_STRICT !== '0';
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

const frontendExeCandidates = [
  path.join(releaseDir, 'koi-tauri.exe'),
  path.join(releaseDir, 'koi.exe'),
];

function relativeLabel(target) {
  return path.relative(projectRoot, target) || target;
}

function readAppVersion() {
  const cargoToml = fs.readFileSync(cargoTomlPath, 'utf8');
  const match = cargoToml.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) {
    throw new Error(`Unable to read application version from ${cargoTomlPath}`);
  }
  if (expectedVersion && match[1] !== expectedVersion) {
    throw new Error(`Expected KOI version ${expectedVersion}, found ${match[1]} in ${cargoTomlPath}`);
  }
  return match[1];
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
  if (!fs.existsSync(source)) {
    throw new Error(`Missing required release resource: ${source}`);
  }
  if (path.resolve(source) === path.resolve(destination)) {
    return;
  }
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.cpSync(source, destination, { recursive: true, force, errorOnExist: false });
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
    if (!fs.statSync(destination).isDirectory()) {
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
    if (!fs.statSync(destination).isFile()) {
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
    if (!fs.statSync(destination).isDirectory()) {
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
      const lower = entry.name.toLowerCase();
      if (lower.startsWith('koi-backend') || lower.includes('pyinstaller') || lower.endsWith('.py')) {
        forbidden.push(relativeLabel(fullPath));
      }
      if (entry.isDirectory()) {
        visit(fullPath);
      }
    }
  };
  visit(outputDir);
  if (forbidden.length) {
    throw new Error(`Rust-only release contains forbidden Python backend artifacts:\n${forbidden.join('\n')}`);
  }
}

function writeManifest(appVersion) {
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
    pythonBusinessBackend: false,
    pdfiumRuntime: verifiedPdfiumLock ? {
      version: verifiedPdfiumLock.version,
      chromiumBranch: verifiedPdfiumLock.chromium_branch,
      archiveSha256: verifiedPdfiumLock.source.archive_sha256,
    } : null,
    archiveRuntime: verifiedArchiveLock ? {
      version: verifiedArchiveLock.version,
      installerSha256: verifiedArchiveLock.source.installer_sha256,
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
    `${JSON.stringify({ format: manifest.format, version: appVersion, dataDirectory: manifest.userDataDirectory }, null, 2)}\n`,
    'utf8',
  );
}

const appVersion = readAppVersion();
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
if (fs.existsSync(archiveLockSource) && fs.existsSync(archiveRuntimeSource)) {
  verifiedArchiveLock = verifyLockedRuntime({
    lockPath: archiveLockSource,
    runtimeDir: archiveRuntimeSource,
    expectedFormat: 'koi-archive-runtime-v1',
  });
  verifyArchiveRuntimeProvenance(verifiedArchiveLock);
}
if (fs.existsSync(externalToolsLockSource)) {
  verifiedExternalToolsLock = verifyExternalToolsLock(externalToolsLockSource);
}
fs.mkdirSync(releaseBase, { recursive: true });
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(dataDir, { recursive: true });
if (!strictRelease || process.env.KOI_MIGRATE_LEGACY_RELEASE_DATA === '1') {
  migrateLegacyUserData();
}
removeLegacyReleaseEntries();

copyEntry(firstExisting(frontendExeCandidates, 'Rust/Tauri application executable'), path.join(outputDir, 'koi.exe'));
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
writeManifest(appVersion);

console.log(`Portable KOI ${appVersion} prepared at: ${releaseBase}`);
console.log(`Application: ${outputDir}`);
console.log(`User data preserved at: ${dataDir}`);
