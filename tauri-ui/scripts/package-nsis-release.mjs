import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  assertArtifactBuiltAfterStamp,
  assertPinnedReleaseVersion,
  cargoTargetCandidates,
  normalizeFullSourceRevision,
  readBuildSourceStamp,
  readReleaseVersions,
  requireRealDirectory,
  requireRegularFile,
  resolveStrictSourceRevision,
  validateRustOnlyContract,
} from './release-gates.mjs';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', '4.0.0');
const configuredCargoTarget = String(process.env.CARGO_TARGET_DIR || '').trim();
const strictRelease = process.env.KOI_RELEASE_STRICT !== '0';
if (strictRelease && configuredCargoTarget && !path.isAbsolute(configuredCargoTarget)) {
  throw new Error('Strict release requires CARGO_TARGET_DIR to be absolute when explicitly configured.');
}
const targetCandidates = cargoTargetCandidates(projectRoot, configuredCargoTarget);
const targetDir = targetCandidates.find((candidate) => fs.existsSync(path.join(candidate, 'release', 'bundle', 'nsis')))
  || targetCandidates[0];
const nsisDir = path.join(targetDir, 'release', 'bundle', 'nsis');
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();
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
let buildStamp = null;
if (strictRelease) {
  validateRustOnlyContract(projectRoot);
  buildStamp = readBuildSourceStamp(projectRoot, sourceRevision, configuredCargoTarget);
  if (path.resolve(buildStamp.targetDirectory) !== path.resolve(targetDir)) {
    throw new Error(`NSIS bundle is not below the stamped Cargo target directory: ${targetDir}`);
  }
  const releaseManifestPath = path.join(releaseBase, 'release-manifest.json');
  requireRegularFile(releaseManifestPath, 'Portable release manifest');
  let releaseManifest;
  try {
    releaseManifest = JSON.parse(fs.readFileSync(releaseManifestPath, 'utf8'));
  } catch (error) {
    throw new Error(`Portable release manifest is invalid JSON: ${error.message}`);
  }
  if (releaseManifest.version !== version || releaseManifest.sourceRevision !== sourceRevision
    || releaseManifest.pythonBusinessBackend !== false) {
    throw new Error('NSIS source revision does not match the already verified portable release.');
  }
}

requireRealDirectory(nsisDir, 'NSIS bundle directory');
const installers = fs.readdirSync(nsisDir)
  .filter((name) => name.toLowerCase().endsWith('.exe'))
  .filter((name) => !name.toLowerCase().includes('uninstall'))
  .map((name) => path.join(nsisDir, name));
if (installers.length !== 1) {
  throw new Error(`Expected exactly one NSIS installer in ${nsisDir}; found ${installers.length}.`);
}
const installerStat = requireRegularFile(installers[0], 'NSIS installer');
if (!installerStat.size) throw new Error(`NSIS installer is empty: ${installers[0]}`);
if (buildStamp) assertArtifactBuiltAfterStamp(installers[0], buildStamp.stampPath, 'NSIS installer');

fs.mkdirSync(releaseBase, { recursive: true });
requireRealDirectory(releaseBase, 'Release base');
const destination = path.join(releaseBase, `koi-v${version}-windows-x64-setup.exe`);
if (strictRelease && fs.existsSync(destination)) {
  throw new Error(`Strict release refuses to overwrite an existing NSIS artifact: ${destination}`);
}
if (fs.existsSync(destination)) requireRegularFile(destination, 'Existing staged NSIS installer');
fs.copyFileSync(installers[0], destination, strictRelease ? fs.constants.COPYFILE_EXCL : 0);
requireRegularFile(destination, 'Staged NSIS installer');
console.log(`NSIS installer prepared for ${sourceRevision || '<unstamped development tree>'}: ${destination}`);
