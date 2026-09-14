import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  assertCleanReleaseTree,
  assertPinnedReleaseVersion,
  cargoTargetCandidates,
  readReleaseVersions,
  resolveStrictSourceRevision,
  validateRustOnlyContract,
  writeBuildSourceStamp,
} from './release-gates.mjs';

// Compatibility entry point for old local wrappers. The backend is compiled
// into the Rust/Tauri executable; this script must never invoke Python or a
// PyInstaller sidecar.
const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const strictRelease = process.env.KOI_RELEASE_STRICT !== '0';
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();
const configuredCargoTarget = String(process.env.CARGO_TARGET_DIR || '').trim();
if (strictRelease && configuredCargoTarget && !path.isAbsolute(configuredCargoTarget)) {
  throw new Error('Strict release requires CARGO_TARGET_DIR to be absolute when explicitly configured.');
}

let version;
let sourceRevision = null;
if (strictRelease) {
  version = assertPinnedReleaseVersion(projectRoot, expectedVersion);
  sourceRevision = resolveStrictSourceRevision(
    projectRoot,
    String(process.env.GITHUB_SHA || process.env.KOI_SOURCE_REVISION || '').trim(),
  );
} else {
  version = readReleaseVersions(projectRoot).cargo;
  if (expectedVersion && version !== expectedVersion) {
    throw new Error(`Expected KOI ${expectedVersion}, found ${version}.`);
  }
}

const inventory = validateRustOnlyContract(projectRoot);
const modulesRoot = path.join(projectRoot, 'modules');
if (fs.existsSync(modulesRoot)) {
  assertCleanReleaseTree(modulesRoot, {
    label: 'Production module source',
    includePrivateState: false,
  });
}
const sourceStamp = sourceRevision ? writeBuildSourceStamp(projectRoot, sourceRevision) : null;
if (sourceStamp) {
  for (const targetDirectory of cargoTargetCandidates(projectRoot)) {
    for (const name of ['koi-tauri.exe', 'koi.exe', 'koi-tauri.pdb', 'koi.pdb']) {
      fs.rmSync(path.join(targetDirectory, 'release', name), { force: true });
    }
  }
}

console.log(
  `Rust backend preflight passed for KOI ${version}: `
  + `${inventory.commandCount} contract entries and ${inventory.handlerCount} registered Rust handlers.`,
);
if (sourceRevision) console.log(`Build source revision: ${sourceRevision} (${sourceStamp})`);
console.log('The backend is built by the Tauri Rust target; no Python business backend or sidecar is packaged.');
