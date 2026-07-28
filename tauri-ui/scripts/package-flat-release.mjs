import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const uiDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(uiDir, '..', '..');
const outputDir = path.join(projectRoot, 'dist-tauri', 'koi');
const dataDir = path.join(projectRoot, 'dist-tauri', 'koi-data');
const releaseDir = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'target', 'release');
const cargoTomlPath = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml');
const frontendExeCandidates = [
  path.join(releaseDir, 'koi.exe'),
  path.join(releaseDir, 'koi-tauri.exe'),
];
const backendExeCandidates = [
  path.join(outputDir, 'koi-backend.exe'),
  path.join(projectRoot, 'tauri-ui', 'dist', 'koi-backend.exe'),
  path.join(projectRoot, 'tauri-ui', 'dist', 'koi_backend.exe'),
  path.join(projectRoot, 'dist', 'koi-backend.exe'),
  path.join(projectRoot, 'dist', 'koi_backend.exe'),
];
const backendDirCandidates = [
  path.join(outputDir, 'koi-backend'),
  path.join(projectRoot, 'tauri-ui', 'dist', 'koi-backend'),
  path.join(projectRoot, 'dist', 'koi-backend'),
];

function firstExisting(candidates, label) {
  const existing = candidates.find((candidate) => fs.existsSync(candidate));
  if (!existing) {
    throw new Error(`Missing required ${label}. Checked:\n${candidates.join('\n')}`);
  }
  return existing;
}

function relativeLabel(target) {
  return path.relative(projectRoot, target) || target;
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
    console.log(`Preserved existing ${label}: ${relativeLabel(destination)}`);
    return;
  }
  fs.mkdirSync(destination, { recursive: true });
  console.log(`Seeded empty ${label}: ${relativeLabel(destination)}`);
}

function ensureFile(destination, label) {
  if (fs.existsSync(destination)) {
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

function readAppVersion() {
  const cargoToml = fs.readFileSync(cargoTomlPath, 'utf8');
  const match = cargoToml.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) {
    throw new Error(`Unable to read application version from ${cargoTomlPath}`);
  }
  return match[1];
}

function migrateLegacyUserData() {
  fs.mkdirSync(dataDir, { recursive: true });
  for (const relativePath of ['config.json', 'enterprise_classification.db', 'Report_Template', 'templates']) {
    const legacyPath = path.join(outputDir, relativePath);
    const dataPath = path.join(dataDir, relativePath);
    if (!fs.existsSync(legacyPath) || fs.existsSync(dataPath)) {
      continue;
    }
    copyEntry(legacyPath, dataPath, { force: false });
    console.log(`Migrated existing user data: ${relativeLabel(legacyPath)} -> ${relativeLabel(dataPath)}`);
  }
}

fs.mkdirSync(outputDir, { recursive: true });
migrateLegacyUserData();
fs.rmSync(path.join(outputDir, 'koi.exe'), { force: true });
fs.rmSync(path.join(outputDir, 'koi-backend.exe'), { force: true });

copyEntry(firstExisting(frontendExeCandidates, 'Tauri frontend executable'), path.join(outputDir, 'koi.exe'));
if (backendDirCandidates.some((candidate) => fs.existsSync(candidate))) {
  copyEntry(firstExisting(backendDirCandidates, 'Python backend directory'), path.join(outputDir, 'koi-backend'));
} else {
  copyEntry(firstExisting(backendExeCandidates, 'Python backend executable'), path.join(outputDir, 'koi-backend.exe'));
}
const appVersion = readAppVersion();
fs.writeFileSync(path.join(outputDir, 'version.txt'), `${appVersion}\n`, 'utf8');
if (fs.existsSync(path.join(outputDir, 'koi-backend'))) {
  fs.writeFileSync(path.join(outputDir, 'koi-backend', 'version.txt'), `${appVersion}\n`, 'utf8');
}
mergeDefaults(path.join(projectRoot, 'Report_Template'), path.join(dataDir, 'Report_Template'), 'report template');
ensureDirectory(path.join(dataDir, 'Report_Template'), 'report template directory');
ensureDirectory(path.join(outputDir, 'retest_external_tools'), 'retest external tools directory');
mergeDefaults(
  path.join(projectRoot, 'modules', 'data_processing', 'templates'),
  path.join(dataDir, 'templates'),
  'data template'
);
if (fs.existsSync(path.join(projectRoot, 'enterprise_classification.db'))) {
  copyIfMissing(
    path.join(projectRoot, 'enterprise_classification.db'),
    path.join(dataDir, 'enterprise_classification.db'),
    'enterprise classification database'
  );
} else {
  ensureFile(path.join(dataDir, 'enterprise_classification.db'), 'enterprise classification database');
}
fs.rmSync(path.join(outputDir, 'koi-backend', 'config.json'), { force: true });
fs.rmSync(path.join(outputDir, 'koi-backend', 'config.json.lock'), { force: true });
fs.rmSync(path.join(outputDir, 'koi-backend', 'config.json.tmp'), { force: true });
fs.rmSync(path.join(outputDir, 'koi-backend', 'enterprise_classification.db'), { force: true });
removeConfigVersion(path.join(dataDir, 'config.json'));
removeConfigVersion(path.join(outputDir, 'config.json'));

console.log(`Flat KOI release prepared at: ${outputDir}`);
console.log(`User data preserved at: ${dataDir}`);
