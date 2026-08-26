import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', '4.0.0');
const cargoTarget = String(process.env.CARGO_TARGET_DIR || '').trim();
const targetCandidates = cargoTarget && !path.isAbsolute(cargoTarget)
  ? [
      path.resolve(projectRoot, cargoTarget),
      path.resolve(projectRoot, 'tauri-ui', 'src-tauri', cargoTarget),
    ]
  : [cargoTarget ? path.resolve(projectRoot, cargoTarget) : path.join(projectRoot, 'tauri-ui', 'src-tauri', 'target')];
const targetDir = targetCandidates.find((candidate) => fs.existsSync(path.join(candidate, 'release', 'bundle', 'nsis')))
  || targetCandidates.find((candidate) => fs.existsSync(path.join(candidate, 'release')))
  || targetCandidates[0];
const nsisDir = path.join(targetDir, 'release', 'bundle', 'nsis');
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();

function readVersion() {
  const source = fs.readFileSync(path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml'), 'utf8');
  const match = source.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) throw new Error('Unable to read Cargo package version.');
  if (expectedVersion && match[1] !== expectedVersion) {
    throw new Error(`Expected version ${expectedVersion}, found ${match[1]}.`);
  }
  return match[1];
}

const version = readVersion();
if (!fs.existsSync(nsisDir)) {
  throw new Error(`NSIS bundle directory does not exist: ${nsisDir}. Run tauri build --bundles nsis first.`);
}

const installers = fs.readdirSync(nsisDir)
  .filter((name) => name.toLowerCase().endsWith('.exe'))
  .filter((name) => !name.toLowerCase().includes('uninstall'))
  .map((name) => path.join(nsisDir, name));
if (installers.length !== 1) {
  throw new Error(`Expected exactly one NSIS installer in ${nsisDir}; found ${installers.length}.`);
}

fs.mkdirSync(releaseBase, { recursive: true });
const destination = path.join(releaseBase, `koi-v${version}-windows-x64-setup.exe`);
fs.copyFileSync(installers[0], destination);
console.log(`NSIS installer prepared at: ${destination}`);
