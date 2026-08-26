import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', '4.0.0');
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();
const requireNsis = process.env.KOI_REQUIRE_NSIS === '1';

function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function requireFile(filePath, label) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    throw new Error(`Missing ${label}: ${filePath}`);
  }
}

function cargoVersion() {
  const source = fs.readFileSync(path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml'), 'utf8');
  const match = source.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) throw new Error('Unable to read Cargo package version.');
  if (match[1] !== expectedVersion) {
    throw new Error(`Expected KOI ${expectedVersion}, found ${match[1]}.`);
  }
  return match[1];
}

const version = cargoVersion();
const portable = path.join(releaseBase, `koi-v${version}-windows-x64-portable.zip`);
const installer = path.join(releaseBase, `koi-v${version}-windows-x64-setup.exe`);
requireFile(portable, 'portable archive');
if (requireNsis) requireFile(installer, 'NSIS installer');

const artifactPaths = [portable];
if (fs.existsSync(installer)) artifactPaths.push(installer);
const artifacts = artifactPaths.map((filePath) => ({
  file: path.basename(filePath),
  bytes: fs.statSync(filePath).size,
  sha256: sha256(filePath),
}));

const lockFiles = [
  path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.lock'),
  path.join(projectRoot, 'tauri-ui', 'package-lock.json'),
  path.join(projectRoot, 'contracts', 'backend-commands.json'),
  path.join(projectRoot, 'probe-wheels.lock.json'),
  path.join(projectRoot, 'tauri-ui', 'src-tauri', 'src', 'backend', 'external_tools.lock.json'),
  ...fs.readdirSync(projectRoot)
    .filter((name) => name.endsWith('-runtime.lock.json'))
    .map((name) => path.join(projectRoot, name)),
].filter((filePath, index, values) => fs.existsSync(filePath) && values.indexOf(filePath) === index);

const inputs = lockFiles.map((filePath) => ({
  file: path.relative(projectRoot, filePath).replaceAll('\\', '/'),
  bytes: fs.statSync(filePath).size,
  sha256: sha256(filePath),
}));
const manifest = {
  format: 'koi-supply-chain-v1',
  product: 'koi',
  version,
  platform: 'windows-x64',
  commit: String(process.env.GITHUB_SHA || process.env.KOI_SOURCE_REVISION || '').trim() || null,
  rustToolchain: String(process.env.RUSTUP_TOOLCHAIN || 'stable'),
  node: process.version,
  pythonBusinessBackend: false,
  inputs,
  artifacts,
};

fs.mkdirSync(releaseBase, { recursive: true });
fs.writeFileSync(
  path.join(releaseBase, 'SHA256SUMS'),
  `${artifacts.map((artifact) => `${artifact.sha256}  ${artifact.file}`).join('\n')}\n`,
  'ascii',
);
fs.writeFileSync(
  path.join(releaseBase, 'supply-chain.json'),
  `${JSON.stringify(manifest, null, 2)}\n`,
  'utf8',
);

console.log(`Finalized ${artifacts.length} KOI ${version} artifact(s) in ${releaseBase}.`);
