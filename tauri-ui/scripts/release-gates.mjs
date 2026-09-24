import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

export const RELEASE_VERSION = '4.0.0';
export const RELEASE_COMMAND_COUNT = 97;
export const BUILD_SOURCE_STAMP = '.koi-build-source.json';

export const REQUIRED_SUPPLY_CHAIN_INPUTS = Object.freeze([
  '.github/workflows/release.yml',
  'archive-runtime.lock.json',
  'build_release.ps1',
  'contracts/backend-behavior-matrix.v1.json',
  'contracts/backend-commands.json',
  'contracts/python-oracle-cutover-audit.v1.json',
  'pdfium-runtime.lock.json',
  'probe-runtime.lock.json',
  'probe-wheels.lock.json',
  'tauri-ui/package-lock.json',
  'tauri-ui/package.json',
  'tauri-ui/e2e/retest-workflows.mjs',
  'tauri-ui/scripts/capture-python-oracle.mjs',
  'tauri-ui/scripts/build-backend.mjs',
  'tauri-ui/scripts/generate-behavior-matrix.mjs',
  'tauri-ui/scripts/finalize-release.mjs',
  'tauri-ui/scripts/locked-runtime.mjs',
  'tauri-ui/scripts/locked-runtime.test.mjs',
  'tauri-ui/scripts/package-flat-release.mjs',
  'tauri-ui/scripts/package-nsis-release.mjs',
  'tauri-ui/scripts/release-gates.mjs',
  'tauri-ui/scripts/release-gates.test.mjs',
  'tauri-ui/scripts/test-nsis-lifecycle.ps1',
  'tauri-ui/scripts/verify-backend-contract.mjs',
  'tauri-ui/scripts/verify-behavior-matrix.mjs',
  'tauri-ui/scripts/verify-release.mjs',
  'tauri-ui/src-tauri/Cargo.lock',
  'tauri-ui/src-tauri/Cargo.toml',
  'tauri-ui/src-tauri/examples/backend_protocol_driver.rs',
  'tauri-ui/src-tauri/fixtures/python_oracle/command_boundaries.v1.json',
  'tauri-ui/src-tauri/build.rs',
  'tauri-ui/src-tauri/src/backend/external_tools.lock.json',
  'tauri-ui/src-tauri/tauri.conf.json',
  'tauri-ui/src-tauri/resources/report-template-placeholder/README.md',
]);

const PRIVATE_DIRECTORY_NAMES = new Set([
  '.koi_agent_sessions',
  '.koi-runtime',
  '.retest-control',
  'aiqicha_browser_profile',
  'ebwebview',
  'logs',
  'tyc_browser_profile',
  'webview2',
  'webview2-data',
]);

const PRIVATE_FILE_NAMES = new Set([
  '.koi-batch-tasks.json',
  '.koi-native-runtime.json',
  '.koi-notice-tasks.json',
  '.koi_notice_process_state.json',
  '.env',
  '.env.local',
  'config.json',
  'cookies',
  'cookies.sqlite',
  'local state',
  'login data',
  'secrets.dpapi.json',
  'web data',
]);

function runGit(projectRoot, args) {
  const result = spawnSync('git', args, {
    cwd: projectRoot,
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || '').trim();
    throw new Error(`Git command failed: git ${args.join(' ')}${detail ? `\n${detail}` : ''}`);
  }
  return String(result.stdout || '').trim();
}

export function sha256File(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

export function requireRegularFile(filePath, label = 'File') {
  const stat = fs.lstatSync(filePath, { throwIfNoEntry: false });
  if (!stat || stat.isSymbolicLink() || !stat.isFile()) {
    throw new Error(`${label} must be a regular, non-symbolic-link file: ${filePath}`);
  }
  return stat;
}

export function requireRealDirectory(directory, label = 'Directory') {
  const stat = fs.lstatSync(directory, { throwIfNoEntry: false });
  if (!stat || stat.isSymbolicLink() || !stat.isDirectory()) {
    throw new Error(`${label} must be a real, non-symbolic-link directory: ${directory}`);
  }
  return stat;
}

function normalizedRepositoryPath(relative, label) {
  if (typeof relative !== 'string'
    || !relative
    || relative.includes('\\')
    || relative.includes('\0')
    || relative.includes(':')
    || path.posix.isAbsolute(relative)
    || path.posix.normalize(relative) !== relative
    || relative.split('/').some((part) => !part || part === '.' || part === '..')) {
    throw new Error(`${label} contains an unsafe repository-relative path: ${String(relative)}`);
  }
  return relative;
}

export function readReleaseVersions(projectRoot) {
  const cargoPath = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml');
  const packagePath = path.join(projectRoot, 'tauri-ui', 'package.json');
  requireRegularFile(cargoPath, 'Cargo manifest');
  requireRegularFile(packagePath, 'UI package manifest');
  const cargoMatch = fs.readFileSync(cargoPath, 'utf8').match(/^version\s*=\s*"([^"]+)"/m);
  if (!cargoMatch) throw new Error(`Unable to read the Cargo application version: ${cargoPath}`);
  let packageManifest;
  try {
    packageManifest = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
  } catch (error) {
    throw new Error(`Unable to read the UI package version: ${error.message}`);
  }
  if (typeof packageManifest.version !== 'string' || !packageManifest.version) {
    throw new Error(`Unable to read the UI package version: ${packagePath}`);
  }
  return { cargo: cargoMatch[1], package: packageManifest.version };
}

export function assertPinnedReleaseVersion(projectRoot, expectedVersion = RELEASE_VERSION) {
  if (expectedVersion !== RELEASE_VERSION) {
    throw new Error(
      `Strict KOI release gates are pinned to ${RELEASE_VERSION}; refusing expected-version override ${expectedVersion || '<empty>'}.`,
    );
  }
  const versions = readReleaseVersions(projectRoot);
  if (versions.cargo !== RELEASE_VERSION || versions.package !== RELEASE_VERSION) {
    throw new Error(
      `KOI version metadata must all equal ${RELEASE_VERSION}; Cargo=${versions.cargo}, package=${versions.package}.`,
    );
  }
  return RELEASE_VERSION;
}

export function normalizeFullSourceRevision(value, expectedHead = null) {
  const revision = String(value || '').trim().toLowerCase();
  if (!/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(revision)) {
    throw new Error('Source revision must be a full 40- or 64-character Git commit object ID.');
  }
  if (expectedHead != null) {
    const head = String(expectedHead || '').trim().toLowerCase();
    if (revision !== head) {
      throw new Error(`Source revision ${revision} does not equal the build checkout HEAD ${head || '<empty>'}.`);
    }
  }
  return revision;
}

export function resolveStrictSourceRevision(projectRoot, requestedRevision = '') {
  const head = normalizeFullSourceRevision(runGit(projectRoot, ['rev-parse', '--verify', 'HEAD^{commit}']));
  const revision = requestedRevision
    ? normalizeFullSourceRevision(requestedRevision, head)
    : head;
  // `git status` can report generated Tauri files as modified on Windows
  // when only the working-tree line ending differs from the index. Compare
  // normalized content for tracked files, while still rejecting staged edits
  // and untracked files.
  const changedEntries = [
    runGit(projectRoot, ['diff', '--name-only', '--diff-filter=ACDMRTUXB']),
    runGit(projectRoot, ['diff', '--cached', '--name-only', '--diff-filter=ACDMRTUXB']),
    runGit(projectRoot, ['ls-files', '--others', '--exclude-standard']),
  ]
    .flatMap((output) => output.split(/\r?\n/).map((entry) => entry.trim()).filter(Boolean));
  const entries = [...new Set(changedEntries)];
  if (entries.length) {
    throw new Error(
      `Strict release requires a completely clean source tree at ${revision}. `
      + `Build from a detached clean worktree; changed entries:\n${entries.slice(0, 20).join('\n')}`,
    );
  }
  return revision;
}

function filesystemFileInventory(projectRoot, repositoryRelative) {
  const root = path.resolve(projectRoot, ...repositoryRelative.split('/'));
  const rootStat = fs.lstatSync(root, { throwIfNoEntry: false });
  if (!rootStat || rootStat.isSymbolicLink()) {
    throw new Error(`Release input is missing or is a symbolic link: ${repositoryRelative}`);
  }
  if (rootStat.isFile()) return [repositoryRelative];
  if (!rootStat.isDirectory()) throw new Error(`Release input has an unsupported type: ${repositoryRelative}`);
  const files = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const stat = fs.lstatSync(fullPath);
      const relative = path.relative(projectRoot, fullPath).replaceAll('\\', '/');
      if (stat.isSymbolicLink()) throw new Error(`Release input contains a symbolic link: ${relative}`);
      if (stat.isDirectory()) pending.push(fullPath);
      else if (stat.isFile()) files.push(relative);
      else throw new Error(`Release input has an unsupported type: ${relative}`);
    }
  }
  return files;
}

export function assertGitTrackedInputs(projectRoot, relativeInputs) {
  if (!Array.isArray(relativeInputs) || !relativeInputs.length) {
    throw new Error('Git-tracked release input list must not be empty.');
  }
  const normalizedInputs = relativeInputs.map((relative) => normalizedRepositoryPath(relative, 'Release input'));
  const trackedOutput = runGit(projectRoot, ['ls-files', '--cached', '-z', '--', ...normalizedInputs]);
  const tracked = new Set(trackedOutput.split('\0').filter(Boolean).map((relative) => relative.replaceAll('\\', '/')));
  const actual = new Set(normalizedInputs.flatMap((relative) => filesystemFileInventory(projectRoot, relative)));
  const untracked = [...actual].filter((relative) => !tracked.has(relative));
  const missing = [...tracked].filter((relative) => !actual.has(relative));
  if (untracked.length || missing.length) {
    throw new Error(
      `Strict release resources must exactly match Git-tracked files `
      + `(untracked/ignored: ${untracked.sort().join(', ') || '<none>'}; `
      + `missing: ${missing.sort().join(', ') || '<none>'}).`,
    );
  }
  return tracked;
}

export function cargoTargetCandidates(projectRoot, configuredTarget = process.env.CARGO_TARGET_DIR || '') {
  const configured = String(configuredTarget || '').trim();
  if (!configured) return [path.join(projectRoot, 'tauri-ui', 'src-tauri', 'target')];
  if (path.isAbsolute(configured)) return [path.normalize(configured)];
  return [
    path.resolve(configured),
    path.resolve(projectRoot, 'tauri-ui', configured),
    path.resolve(projectRoot, 'tauri-ui', 'src-tauri', configured),
    path.resolve(projectRoot, configured),
  ].filter((candidate, index, values) => values.indexOf(candidate) === index);
}

export function writeBuildSourceStamp(projectRoot, sourceRevision, configuredTarget = process.env.CARGO_TARGET_DIR || '') {
  const revision = normalizeFullSourceRevision(sourceRevision);
  const [targetDirectory] = cargoTargetCandidates(projectRoot, configuredTarget);
  fs.mkdirSync(targetDirectory, { recursive: true });
  requireRealDirectory(targetDirectory, 'Cargo target directory');
  const destination = path.join(targetDirectory, BUILD_SOURCE_STAMP);
  const temporary = `${destination}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify({
    format: 'koi-build-source-v1',
    version: RELEASE_VERSION,
    sourceRevision: revision,
  }, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  if (fs.existsSync(destination)) requireRegularFile(destination, 'Existing build source stamp');
  fs.rmSync(destination, { force: true });
  fs.renameSync(temporary, destination);
  return destination;
}

export function readBuildSourceStamp(projectRoot, sourceRevision, configuredTarget = process.env.CARGO_TARGET_DIR || '') {
  const revision = normalizeFullSourceRevision(sourceRevision);
  const candidates = cargoTargetCandidates(projectRoot, configuredTarget);
  const stampPaths = candidates.map((candidate) => path.join(candidate, BUILD_SOURCE_STAMP));
  const stampPath = stampPaths.find((candidate) => fs.lstatSync(candidate, { throwIfNoEntry: false })?.isFile());
  if (!stampPath) {
    throw new Error(`Missing strict build source stamp. Checked:\n${stampPaths.join('\n')}`);
  }
  requireRegularFile(stampPath, 'Build source stamp');
  let stamp;
  try {
    stamp = JSON.parse(fs.readFileSync(stampPath, 'utf8'));
  } catch (error) {
    throw new Error(`Build source stamp is invalid JSON: ${error.message}`);
  }
  if (stamp.format !== 'koi-build-source-v1'
    || stamp.version !== RELEASE_VERSION
    || normalizeFullSourceRevision(stamp.sourceRevision, revision) !== revision) {
    throw new Error('Build source stamp does not match the exact checkout used for packaging.');
  }
  return { stamp, stampPath, targetDirectory: path.dirname(stampPath) };
}

export function assertArtifactBuiltAfterStamp(artifactPath, stampPath, label = 'Build artifact') {
  const artifactStat = requireRegularFile(artifactPath, label);
  const stampStat = requireRegularFile(stampPath, 'Build source stamp');
  if (!artifactStat.size) throw new Error(`${label} is empty: ${artifactPath}`);
  if (artifactStat.mtimeMs <= stampStat.mtimeMs) {
    throw new Error(`${label} predates the strict build-source stamp: ${artifactPath}`);
  }
  return artifactStat;
}

function resolveRepositoryFile(projectRoot, relative, label) {
  normalizedRepositoryPath(relative, label);
  const resolved = path.resolve(projectRoot, ...relative.split('/'));
  const relativeFromRoot = path.relative(projectRoot, resolved);
  if (!relativeFromRoot || relativeFromRoot.startsWith(`..${path.sep}`) || path.isAbsolute(relativeFromRoot)) {
    throw new Error(`${label} must resolve to a file inside the repository: ${relative}`);
  }
  requireRegularFile(resolved, label);
  return resolved;
}

export function validateRustOnlyContract(projectRoot, {
  contractRelative = 'contracts/backend-commands.json',
  expectedCount = RELEASE_COMMAND_COUNT,
} = {}) {
  const contractPath = resolveRepositoryFile(projectRoot, contractRelative, 'Backend command contract');
  let contract;
  try {
    contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
  } catch (error) {
    throw new Error(`Backend command contract is invalid JSON: ${error.message}`);
  }
  if (contract?.schemaVersion !== 1 || !Array.isArray(contract.commands)
    || contract.commands.length !== expectedCount) {
    throw new Error(`Backend command contract must use schemaVersion 1 and contain exactly ${expectedCount} commands.`);
  }

  const contractNames = new Set();
  for (const command of contract.commands) {
    if (!command || typeof command.name !== 'string' || !command.name.trim()
      || contractNames.has(command.name)) {
      throw new Error('Backend command contract contains an invalid or duplicate command name.');
    }
    if (command.owner !== 'rust' || command.channel !== 'rust_concurrent'
      || !Number.isInteger(command.timeoutMs) || command.timeoutMs <= 0) {
      throw new Error(
        `Strict Rust command metadata is invalid for ${command.name}: owner=${command.owner}, channel=${command.channel}.`,
      );
    }
    contractNames.add(command.name);
  }

  const registryRelative = contract.rustHandlerSource || 'tauri-ui/src-tauri/src/backend/registry.rs';
  const registryPath = resolveRepositoryFile(projectRoot, registryRelative, 'Rust handler registry');
  const registrySource = fs.readFileSync(registryPath, 'utf8');
  const beginMarker = '// CONTRACT_RUST_HANDLERS_BEGIN';
  const endMarker = '// CONTRACT_RUST_HANDLERS_END';
  const begin = registrySource.indexOf(beginMarker);
  const end = registrySource.indexOf(endMarker);
  if (begin < 0 || end <= begin
    || registrySource.indexOf(beginMarker, begin + beginMarker.length) >= 0
    || registrySource.indexOf(endMarker, end + endMarker.length) >= 0) {
    throw new Error(`Rust handler inventory markers are missing, duplicated, or out of order: ${registryRelative}`);
  }
  const handlerMatches = [...registrySource.slice(begin, end).matchAll(/\bname:\s*"([^"]+)"/g)]
    .map((match) => match[1]);
  const handlerNames = new Set(handlerMatches);
  if (handlerMatches.length !== expectedCount || handlerNames.size !== expectedCount) {
    throw new Error(`Rust handler registry must contain exactly ${expectedCount} unique handlers.`);
  }
  const missingHandlers = [...contractNames].filter((name) => !handlerNames.has(name));
  const uncontractedHandlers = [...handlerNames].filter((name) => !contractNames.has(name));
  if (missingHandlers.length || uncontractedHandlers.length) {
    throw new Error(
      `Backend contract and Rust handler registry disagree `
      + `(missing handlers: ${missingHandlers.join(', ') || '<none>'}; `
      + `uncontracted handlers: ${uncontractedHandlers.join(', ') || '<none>'}).`,
    );
  }
  return {
    contract,
    contractPath,
    registryPath,
    commandCount: contractNames.size,
    handlerCount: handlerNames.size,
  };
}

export function forbiddenReleaseEntryReason(relativePath, { includePrivateState = true } = {}) {
  const normalized = String(relativePath || '').replaceAll('\\', '/').replace(/^\/+/, '');
  const parts = normalized.split('/').filter(Boolean);
  for (const part of parts) {
    const lower = part.toLowerCase();
    if (lower.startsWith('koi-backend')) return 'legacy Python backend';
    if (lower.includes('pyinstaller')) return 'PyInstaller artifact';
    if (lower === '__pycache__' || lower.endsWith('.py') || lower.endsWith('.pyc') || lower.endsWith('.pyo')) {
      return 'loose Python artifact';
    }
    if (includePrivateState && (PRIVATE_DIRECTORY_NAMES.has(lower) || PRIVATE_FILE_NAMES.has(lower)
      || lower.endsWith('.log'))) {
      return 'private runtime state';
    }
  }
  return null;
}

export function assertCleanReleaseTree(root, {
  label = 'Release tree',
  includePrivateState = true,
} = {}) {
  requireRealDirectory(root, label);
  const forbidden = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const relative = path.relative(root, fullPath).replaceAll('\\', '/');
      const stat = fs.lstatSync(fullPath);
      const reason = stat.isSymbolicLink()
        ? 'symbolic link/reparse entry'
        : forbiddenReleaseEntryReason(relative, { includePrivateState });
      if (reason) {
        forbidden.push(`${relative} (${reason})`);
        continue;
      }
      if (stat.isDirectory()) pending.push(fullPath);
      else if (!stat.isFile()) forbidden.push(`${relative} (unsupported filesystem entry)`);
    }
  }
  if (forbidden.length) {
    throw new Error(`${label} contains forbidden entries:\n${forbidden.sort().join('\n')}`);
  }
}

export function createSupplyChainInputs(projectRoot) {
  return REQUIRED_SUPPLY_CHAIN_INPUTS.map((relative) => {
    const filePath = resolveRepositoryFile(projectRoot, relative, 'Supply-chain input');
    const stat = fs.statSync(filePath);
    if (!Number.isSafeInteger(stat.size) || stat.size <= 0) {
      throw new Error(`Supply-chain input must be non-empty: ${relative}`);
    }
    return { file: relative, bytes: stat.size, sha256: sha256File(filePath) };
  });
}

export function verifySupplyChainInputs(projectRoot, inputs) {
  if (!Array.isArray(inputs) || inputs.length !== REQUIRED_SUPPLY_CHAIN_INPUTS.length) {
    throw new Error(
      `Supply-chain input inventory must contain exactly ${REQUIRED_SUPPLY_CHAIN_INPUTS.length} required inputs.`,
    );
  }
  const records = new Map();
  for (const input of inputs) {
    const relative = normalizedRepositoryPath(input?.file, 'Supply-chain input');
    if (records.has(relative)
      || !Number.isSafeInteger(input?.bytes) || input.bytes <= 0
      || !/^[0-9a-f]{64}$/.test(String(input?.sha256 || ''))) {
      throw new Error(`Supply-chain input inventory has invalid metadata: ${relative}`);
    }
    records.set(relative, input);
  }
  const missing = REQUIRED_SUPPLY_CHAIN_INPUTS.filter((relative) => !records.has(relative));
  const extra = [...records.keys()].filter((relative) => !REQUIRED_SUPPLY_CHAIN_INPUTS.includes(relative));
  if (missing.length || extra.length) {
    throw new Error(
      `Supply-chain input inventory is incomplete `
      + `(missing: ${missing.join(', ') || '<none>'}; extra: ${extra.join(', ') || '<none>'}).`,
    );
  }
  for (const relative of REQUIRED_SUPPLY_CHAIN_INPUTS) {
    const input = records.get(relative);
    const filePath = resolveRepositoryFile(projectRoot, relative, 'Supply-chain input');
    const stat = fs.statSync(filePath);
    const actualHash = sha256File(filePath);
    if (stat.size !== input.bytes || actualHash !== input.sha256) {
      throw new Error(`Supply-chain input hash or size does not match: ${relative}`);
    }
  }
  return records;
}

function findEndOfCentralDirectory(bytes) {
  const minimum = Math.max(0, bytes.length - 65_557);
  for (let offset = bytes.length - 22; offset >= minimum; offset -= 1) {
    if (bytes.readUInt32LE(offset) !== 0x06054b50) continue;
    const commentLength = bytes.readUInt16LE(offset + 20);
    if (offset + 22 + commentLength === bytes.length) return offset;
  }
  throw new Error('Portable archive is not a supported ZIP file (EOCD missing).');
}

function decodeZipName(bytes, utf8) {
  const decoded = bytes.toString(utf8 ? 'utf8' : 'latin1');
  if (decoded.includes('\uFFFD')) throw new Error('Portable archive contains an invalid encoded path.');
  return decoded;
}

export function readZipInventory(zipPath) {
  requireRegularFile(zipPath, 'Portable archive');
  const bytes = fs.readFileSync(zipPath);
  if (bytes.length < 22) throw new Error('Portable archive is too short to be a ZIP file.');
  const eocd = findEndOfCentralDirectory(bytes);
  const disk = bytes.readUInt16LE(eocd + 4);
  const centralDisk = bytes.readUInt16LE(eocd + 6);
  const entriesOnDisk = bytes.readUInt16LE(eocd + 8);
  const entryCount = bytes.readUInt16LE(eocd + 10);
  const centralSize = bytes.readUInt32LE(eocd + 12);
  const centralOffset = bytes.readUInt32LE(eocd + 16);
  if (disk !== 0 || centralDisk !== 0 || entriesOnDisk !== entryCount
    || entryCount === 0xffff || centralSize === 0xffffffff || centralOffset === 0xffffffff) {
    throw new Error('Portable archive uses unsupported multi-disk or ZIP64 metadata.');
  }
  if (centralOffset + centralSize !== eocd || centralOffset > bytes.length) {
    throw new Error('Portable archive central directory is inconsistent.');
  }
  const entries = [];
  let cursor = centralOffset;
  for (let index = 0; index < entryCount; index += 1) {
    if (cursor + 46 > eocd || bytes.readUInt32LE(cursor) !== 0x02014b50) {
      throw new Error('Portable archive central directory entry is invalid.');
    }
    const madeBy = bytes.readUInt16LE(cursor + 4);
    const flags = bytes.readUInt16LE(cursor + 8);
    const method = bytes.readUInt16LE(cursor + 10);
    const compressedSize = bytes.readUInt32LE(cursor + 20);
    const uncompressedSize = bytes.readUInt32LE(cursor + 24);
    const nameLength = bytes.readUInt16LE(cursor + 28);
    const extraLength = bytes.readUInt16LE(cursor + 30);
    const commentLength = bytes.readUInt16LE(cursor + 32);
    const externalAttributes = bytes.readUInt32LE(cursor + 38);
    const localOffset = bytes.readUInt32LE(cursor + 42);
    const end = cursor + 46 + nameLength + extraLength + commentLength;
    if (!nameLength || end > eocd || localOffset >= centralOffset) {
      throw new Error('Portable archive central directory contains invalid offsets.');
    }
    const name = decodeZipName(bytes.subarray(cursor + 46, cursor + 46 + nameLength), Boolean(flags & 0x0800));
    const unixMode = externalAttributes >>> 16;
    entries.push({
      name,
      flags,
      method,
      compressedSize,
      uncompressedSize,
      localOffset,
      symbolicLink: (madeBy >>> 8) === 3 && (unixMode & 0xf000) === 0xa000,
    });
    cursor = end;
  }
  if (cursor !== eocd) throw new Error('Portable archive central directory has trailing data.');
  return { bytes, entries };
}

function normalizedZipPath(name) {
  const directory = name.endsWith('/');
  const bare = directory ? name.slice(0, -1) : name;
  if (!bare
    || name.includes('\\')
    || name.includes('\0')
    || name.startsWith('/')
    || bare.includes(':')
    || path.posix.normalize(bare) !== bare
    || bare.split('/').some((part) => !part || part === '.' || part === '..')) {
    throw new Error(`Portable archive contains an unsafe path: ${name}`);
  }
  return bare;
}

export function validatePortableEntryInventory(entries) {
  if (!Array.isArray(entries) || !entries.length) throw new Error('Portable archive contains no entries.');
  const names = new Map();
  for (const entry of entries) {
    const normalized = normalizedZipPath(String(entry?.name || ''));
    const folded = normalized.toLowerCase();
    if (names.has(folded)) throw new Error(`Portable archive contains a duplicate Windows path: ${normalized}`);
    names.set(folded, { ...entry, normalized });
    if (entry.symbolicLink) throw new Error(`Portable archive contains a symbolic link: ${normalized}`);
    const top = normalized.split('/')[0];
    if (!['koi', 'koi-data', 'release-manifest.json', 'koi-portable.marker'].includes(top)) {
      throw new Error(`Portable archive contains an unexpected top-level entry: ${normalized}`);
    }
    const reason = forbiddenReleaseEntryReason(normalized, { includePrivateState: true });
    if (reason) throw new Error(`Portable archive contains ${reason}: ${normalized}`);
  }
  for (const required of [
    'koi/koi.exe',
    'koi-data/enterprise_classification.db',
    'release-manifest.json',
    'koi-portable.marker',
  ]) {
    if (!names.has(required.toLowerCase())) {
      throw new Error(`Portable archive is missing required entry: ${required}`);
    }
  }
  for (const prefix of ['koi-data/report_template/', 'koi-data/templates/']) {
    if (![...names.keys()].some((name) => name.startsWith(prefix) && name !== prefix)) {
      throw new Error(`Portable archive is missing immutable seed files below ${prefix}`);
    }
  }
  return names;
}

export function readZipEntry(inventory, requestedName, maximumBytes = 1024 * 1024) {
  const requested = requestedName.toLowerCase();
  const entry = inventory.entries.find((candidate) => normalizedZipPath(candidate.name).toLowerCase() === requested);
  if (!entry) throw new Error(`Portable archive is missing required entry: ${requestedName}`);
  if ((entry.flags & 0x0001) !== 0) throw new Error(`Portable archive entry is encrypted: ${requestedName}`);
  if (entry.uncompressedSize > maximumBytes) throw new Error(`Portable archive entry is too large: ${requestedName}`);
  const { bytes } = inventory;
  const offset = entry.localOffset;
  if (offset + 30 > bytes.length || bytes.readUInt32LE(offset) !== 0x04034b50) {
    throw new Error(`Portable archive local header is invalid: ${requestedName}`);
  }
  const nameLength = bytes.readUInt16LE(offset + 26);
  const extraLength = bytes.readUInt16LE(offset + 28);
  const localFlags = bytes.readUInt16LE(offset + 6);
  const localMethod = bytes.readUInt16LE(offset + 8);
  const dataStart = offset + 30 + nameLength + extraLength;
  const dataEnd = dataStart + entry.compressedSize;
  const localName = decodeZipName(
    bytes.subarray(offset + 30, offset + 30 + nameLength),
    Boolean(localFlags & 0x0800),
  );
  if (localName !== entry.name || localMethod !== entry.method || dataEnd > bytes.length) {
    throw new Error(`Portable archive local header disagrees with the central directory: ${requestedName}`);
  }
  const compressed = bytes.subarray(dataStart, dataEnd);
  let value;
  if (entry.method === 0) value = Buffer.from(compressed);
  else if (entry.method === 8) value = zlib.inflateRawSync(compressed, { maxOutputLength: maximumBytes });
  else throw new Error(`Portable archive uses an unsupported compression method for ${requestedName}.`);
  if (value.length !== entry.uncompressedSize) {
    throw new Error(`Portable archive entry size is inconsistent: ${requestedName}`);
  }
  return value;
}

export function verifyPortableArchive(zipPath, {
  releaseManifestPath,
  portableMarkerPath,
  expectedTrees = [],
} = {}) {
  const inventory = readZipInventory(zipPath);
  const archivedNames = validatePortableEntryInventory(inventory.entries);
  for (const [entryName, externalPath] of [
    ['release-manifest.json', releaseManifestPath],
    ['koi-portable.marker', portableMarkerPath],
  ]) {
    if (!externalPath) continue;
    requireRegularFile(externalPath, entryName);
    const embedded = readZipEntry(inventory, entryName);
    const external = fs.readFileSync(externalPath);
    if (!embedded.equals(external)) {
      throw new Error(`Portable archive ${entryName} does not match the finalized release tree.`);
    }
  }
  const expectedFiles = new Map();
  for (const tree of expectedTrees) {
    const prefix = normalizedZipPath(String(tree?.prefix || ''));
    requireRealDirectory(tree?.root, `Portable source tree ${prefix}`);
    const pending = [tree.root];
    while (pending.length) {
      const directory = pending.pop();
      for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        const fullPath = path.join(directory, entry.name);
        const stat = fs.lstatSync(fullPath);
        const relative = path.relative(tree.root, fullPath).replaceAll('\\', '/');
        const archived = `${prefix}/${relative}`;
        if (stat.isSymbolicLink()) throw new Error(`Portable source tree contains a symbolic link: ${archived}`);
        if (stat.isDirectory()) pending.push(fullPath);
        else if (stat.isFile()) expectedFiles.set(archived.toLowerCase(), { archived, fullPath, size: stat.size });
        else throw new Error(`Portable source tree contains an unsupported entry: ${archived}`);
      }
    }
  }
  if (expectedFiles.size) {
    const archivedFiles = [...archivedNames.entries()]
      .filter(([, entry]) => !String(entry.name).endsWith('/'))
      .map(([folded]) => folded);
    const standalone = new Set(['release-manifest.json', 'koi-portable.marker']);
    const unexpected = archivedFiles.filter((name) => !expectedFiles.has(name) && !standalone.has(name));
    const missing = [...expectedFiles.keys()].filter((name) => !archivedNames.has(name));
    if (missing.length || unexpected.length) {
      throw new Error(
        `Portable archive file inventory disagrees with the staged trees `
        + `(missing: ${missing.join(', ') || '<none>'}; unexpected: ${unexpected.join(', ') || '<none>'}).`,
      );
    }
    for (const { archived, fullPath, size } of expectedFiles.values()) {
      const embedded = readZipEntry(inventory, archived, Math.max(size, 1));
      if (!embedded.equals(fs.readFileSync(fullPath))) {
        throw new Error(`Portable archive entry does not match the staged release tree: ${archived}`);
      }
    }
  }
  return inventory;
}
