import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  verifyArchiveRuntimeProvenance,
  verifyExternalToolsLock,
  verifyLockedRuntime,
} from './locked-runtime.mjs';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', '4.0.0');
const appDir = path.join(releaseBase, 'koi');
const dataDir = path.join(releaseBase, 'koi-data');
const contractPath = path.join(projectRoot, 'contracts', 'backend-commands.json');
const expectedVersion = String(process.env.KOI_EXPECTED_VERSION || '4.0.0').trim();
const strictRelease = process.env.KOI_RELEASE_STRICT !== '0';

function requireFile(filePath, label) {
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    throw new Error(`Missing ${label}: ${filePath}`);
  }
}

function verifyProbeWheelLock(filePath) {
  requireFile(filePath, 'embedded probe wheel lock');
  let lock;
  try {
    lock = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  } catch (error) {
    throw new Error(`Embedded probe wheel lock is invalid JSON: ${error.message}`);
  }
  if (lock.format !== 'koi-probe-wheels-v1'
    || lock.source !== 'https://pypi.org/simple'
    || !Array.isArray(lock.roots)
    || !Array.isArray(lock.packages)) {
    throw new Error('Embedded probe wheel lock has an unexpected format or source.');
  }
  if (lock.packages.length > 512) throw new Error('Embedded probe wheel lock contains too many packages.');
  const names = new Set();
  for (const packageEntry of lock.packages) {
    if (!packageEntry || typeof packageEntry.name !== 'string'
      || typeof packageEntry.version !== 'string'
      || !Array.isArray(packageEntry.dependencies)
      || !Array.isArray(packageEntry.imports)
      || !packageEntry.wheel || typeof packageEntry.wheel.filename !== 'string'
      || typeof packageEntry.wheel.url !== 'string'
      || !/^[0-9a-f]{64}$/i.test(packageEntry.wheel.sha256)) {
      throw new Error(`Embedded probe wheel lock has invalid package metadata: ${JSON.stringify(packageEntry)}`);
    }
    const name = packageEntry.name.trim().toLowerCase().replaceAll(/[._-]+/g, '-');
    if (!name || names.has(name)) throw new Error(`Embedded probe wheel lock has a duplicate or empty package name: ${packageEntry.name}`);
    names.add(name);
    if (!packageEntry.wheel.filename.toLowerCase().endsWith('.whl')
      || packageEntry.wheel.filename.includes('/')
      || packageEntry.wheel.filename.includes('\\')) {
      throw new Error(`Embedded probe wheel lock has an unsafe wheel filename: ${packageEntry.wheel.filename}`);
    }
    let artifactUrl;
    try {
      artifactUrl = new URL(packageEntry.wheel.url);
    } catch {
      throw new Error(`Embedded probe wheel lock has an invalid artifact URL: ${packageEntry.wheel.url}`);
    }
    if (artifactUrl.protocol !== 'https:'
      || artifactUrl.hostname !== 'files.pythonhosted.org'
      || path.posix.basename(artifactUrl.pathname) !== packageEntry.wheel.filename) {
      throw new Error(`Embedded probe wheel lock has an untrusted artifact URL: ${packageEntry.wheel.url}`);
    }
    if (packageEntry.source_distribution != null) {
      const source = packageEntry.source_distribution;
      if (typeof source.filename !== 'string'
        || !source.filename.toLowerCase().match(/\.(tar\.gz|zip)$/)
        || typeof source.url !== 'string'
        || !/^[0-9a-f]{64}$/i.test(String(source.sha256 || ''))
        || !Number.isSafeInteger(source.size)
        || source.size <= 0) {
        throw new Error(`Embedded probe wheel lock has invalid source metadata: ${packageEntry.name}`);
      }
      const sourceUrl = new URL(source.url);
      if (sourceUrl.protocol !== 'https:'
        || sourceUrl.hostname !== 'files.pythonhosted.org'
        || path.posix.basename(sourceUrl.pathname) !== source.filename) {
        throw new Error(`Embedded probe wheel lock has an untrusted source URL: ${source.url}`);
      }
    }
    if (packageEntry.source_build != null) {
      const build = packageEntry.source_build;
      if (packageEntry.source_distribution == null
        || typeof build.backend !== 'string'
        || !/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(build.backend)
        || typeof build.source_subdir !== 'string'
        || build.source_subdir.includes('\\')
        || path.posix.isAbsolute(build.source_subdir)
        || path.posix.normalize(build.source_subdir) !== build.source_subdir
        || build.source_subdir.split('/').some((part) => !part || part === '.' || part === '..' || part.includes(':'))
        || !Array.isArray(build.build_dependencies)) {
        throw new Error(`Embedded probe wheel lock has invalid source-build policy: ${packageEntry.name}`);
      }
    }
  }
  for (const root of lock.roots) {
    const normalized = String(root).trim().toLowerCase().replaceAll(/[._-]+/g, '-');
    if (!names.has(normalized)) throw new Error(`Embedded probe wheel root is not locked: ${root}`);
  }
  for (const packageEntry of lock.packages) {
    for (const dependency of packageEntry.dependencies) {
      const normalized = String(dependency).trim().toLowerCase().replaceAll(/[._-]+/g, '-');
      if (!names.has(normalized)) throw new Error(`Embedded probe wheel dependency is not locked: ${dependency}`);
    }
    for (const dependency of packageEntry.source_build?.build_dependencies || []) {
      const normalized = String(dependency).trim().toLowerCase().replaceAll(/[._-]+/g, '-');
      if (!names.has(normalized)) throw new Error(`Embedded source-build dependency is not locked: ${dependency}`);
    }
  }
  return lock;
}

function readCargoVersion() {
  const source = fs.readFileSync(path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml'), 'utf8');
  const match = source.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) throw new Error('Cargo package version is missing.');
  return match[1];
}

const version = readCargoVersion();
if (version !== expectedVersion) throw new Error(`Release version mismatch: expected ${expectedVersion}, found ${version}.`);
requireFile(path.join(appDir, 'koi.exe'), 'Rust application executable');
requireFile(path.join(appDir, 'version.txt'), 'application version marker');
requireFile(path.join(appDir, 'seed', 'enterprise_classification.db'), 'immutable database seed');
if (!fs.existsSync(path.join(appDir, 'seed', 'Report_Template'))
  || !fs.statSync(path.join(appDir, 'seed', 'Report_Template')).isDirectory()) {
  throw new Error(`Missing immutable report-template seed: ${path.join(appDir, 'seed', 'Report_Template')}`);
}
if (!fs.existsSync(path.join(appDir, 'seed', 'templates'))
  || !fs.statSync(path.join(appDir, 'seed', 'templates')).isDirectory()) {
  throw new Error(`Missing immutable data-template seed: ${path.join(appDir, 'seed', 'templates')}`);
}
requireFile(path.join(releaseBase, 'release-manifest.json'), 'release manifest');
requireFile(path.join(releaseBase, 'koi-portable.marker'), 'portable marker');
if (!fs.existsSync(dataDir) || !fs.statSync(dataDir).isDirectory()) throw new Error(`Missing user data directory: ${dataDir}`);
if (strictRelease) {
  requireFile(path.join(appDir, 'probe-runtime.lock.json'), 'embedded probe runtime lock');
  if (!fs.existsSync(path.join(appDir, 'probe-runtime')) || !fs.statSync(path.join(appDir, 'probe-runtime')).isDirectory()) {
    throw new Error(`Missing embedded probe runtime directory: ${path.join(appDir, 'probe-runtime')}`);
  }
  requireFile(path.join(appDir, 'pdfium-runtime.lock.json'), 'embedded PDFium runtime lock');
  verifyLockedRuntime({
    lockPath: path.join(appDir, 'pdfium-runtime.lock.json'),
    runtimeDir: path.join(appDir, 'pdfium-runtime'),
    expectedFormat: 'koi-pdfium-runtime-v1',
  });
  requireFile(path.join(appDir, 'archive-runtime.lock.json'), 'embedded archive runtime lock');
  const archiveLock = verifyLockedRuntime({
    lockPath: path.join(appDir, 'archive-runtime.lock.json'),
    runtimeDir: path.join(appDir, 'archive-runtime'),
    expectedFormat: 'koi-archive-runtime-v1',
  });
  verifyArchiveRuntimeProvenance(archiveLock);
  verifyProbeWheelLock(path.join(appDir, 'probe-wheels.lock.json'));
  verifyExternalToolsLock(path.join(appDir, 'external_tools.lock.json'));
}

const manifest = JSON.parse(fs.readFileSync(path.join(releaseBase, 'release-manifest.json'), 'utf8'));
if (manifest.version !== version
  || manifest.pythonBusinessBackend !== false
  || manifest.pdfiumRuntime?.version !== '153.0.8009.0'
  || manifest.archiveRuntime?.version !== '26.02'
  || manifest.externalTools?.ffuf?.version !== '2.2.1'
  || manifest.externalTools?.ffuf?.artifactSha256 !== '717e3d103ee36ce743a18605be66a4424fca27758eebed1e8ebb2eb0a3645589'
  || manifest.externalTools?.nmap?.version !== '7.991'
  || manifest.externalTools?.nmap?.artifactSha256 !== '93bfd37bdb31a7adfd932beb5dbce06025da691d01a0939e806ea704f7367657') {
  throw new Error('Release manifest does not describe the Rust-only application.');
}
const digest = crypto.createHash('sha256').update(fs.readFileSync(path.join(appDir, 'koi.exe'))).digest('hex');
if (manifest.executableSha256 !== digest) throw new Error('Release executable hash does not match release manifest.');

const forbidden = [];
const visit = (directory) => {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    const lower = entry.name.toLowerCase();
    if (lower.startsWith('koi-backend') || lower.includes('pyinstaller') || lower.endsWith('.py')) forbidden.push(fullPath);
    if (entry.isDirectory()) visit(fullPath);
  }
};
visit(appDir);
if (forbidden.length) throw new Error(`Forbidden Python backend artifacts found:\n${forbidden.join('\n')}`);

if (fs.existsSync(contractPath)) {
  const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
  const pythonOwners = Array.isArray(contract.commands) ? contract.commands.filter((item) => item.owner === 'python') : [];
  if (process.env.KOI_RELEASE_STRICT !== '0' && pythonOwners.length) {
    throw new Error(`Rust-only release gate failed: ${pythonOwners.length} Python command owner(s) remain.`);
  }
}

console.log(`Release verification passed: KOI ${version}, Rust executable and portable data layout are valid.`);
