import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const contractPath = path.join(projectRoot, 'contracts', 'backend-commands.json');
const matrixPath = path.join(projectRoot, 'contracts', 'backend-behavior-matrix.v1.json');
const oraclePath = path.join(
  projectRoot,
  'tauri-ui',
  'src-tauri',
  'fixtures',
  'python_oracle',
  'command_boundaries.v1.json',
);

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function normalizedTextBytes(file) {
  return Buffer.from(fs.readFileSync(file, 'utf8').replaceAll('\r\n', '\n'), 'utf8');
}

function regularFile(relative, label) {
  const file = path.join(projectRoot, ...relative.split('/'));
  const stat = fs.lstatSync(file, { throwIfNoEntry: false });
  if (!stat?.isFile() || stat.isSymbolicLink()) {
    throw new Error(`${label} is missing or not a regular file: ${relative}`);
  }
  return file;
}

function walkFiles(root, predicate = () => true) {
  const files = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const stat = fs.lstatSync(fullPath);
      if (stat.isSymbolicLink()) throw new Error(`Source manifest contains a symlink: ${fullPath}`);
      if (stat.isDirectory()) pending.push(fullPath);
      else if (stat.isFile() && predicate(fullPath)) files.push(fullPath);
    }
  }
  return files.sort((left, right) => left.localeCompare(right, 'en'));
}

function rustSourceManifest() {
  const rustSourceRoot = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'src');
  const files = [
    ...walkFiles(rustSourceRoot, (file) => file.endsWith('.rs')),
    path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml'),
    path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.lock'),
    contractPath,
    path.join(projectRoot, 'tauri-ui', 'src-tauri', 'examples', 'backend_protocol_driver.rs'),
  ].sort((left, right) => left.localeCompare(right, 'en'));
  const records = files.map((file) => ({
    file: path.relative(projectRoot, file).replaceAll('\\', '/'),
    bytes: normalizedTextBytes(file).length,
    sha256: sha256(normalizedTextBytes(file)),
  }));
  return { fileCount: records.length, sha256: sha256(Buffer.from(JSON.stringify(records))) };
}

function evidenceExists(item, command) {
  if (!item || typeof item !== 'object' || typeof item.kind !== 'string') {
    throw new Error(`Invalid evidence for ${command}`);
  }
  const file = regularFile(item.file, `Evidence for ${command}`);
  if (item.kind === 'oracle-boundary') return;
  const source = fs.readFileSync(file, 'utf8');
  if (item.kind === 'rust-test') {
    const marker = `fn ${item.test}(`;
    const index = source.indexOf(marker);
    if (index < 0 || !source.slice(Math.max(0, index - 400), index).includes('#[test]')) {
      throw new Error(`Rust test evidence is missing for ${command}: ${item.file}#${item.test}`);
    }
    return;
  }
  if (item.kind === 'playwright') {
    if (!source.includes(`function ${item.test}(`)) {
      throw new Error(`Playwright evidence is missing for ${command}: ${item.test}`);
    }
    return;
  }
  if (item.kind === 'example') return;
  throw new Error(`Unsupported evidence kind for ${command}: ${item.kind}`);
}

const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
const matrix = JSON.parse(fs.readFileSync(matrixPath, 'utf8'));
const oracle = JSON.parse(fs.readFileSync(oraclePath, 'utf8'));
if (matrix.format !== 'koi-backend-behavior-matrix-v1'
  || matrix.productVersion !== '4.0.0'
  || matrix.platform !== 'windows-x64') {
  throw new Error('Behavior matrix has an unsupported format, version, or platform.');
}
if (matrix.baseline?.revision !== 'f059eacf18de2bc2c888d901d257a59cbe8e12ca'
  || matrix.baseline?.revision !== oracle.baseline?.revision
  || matrix.baseline?.sourceManifest?.sha256 !== oracle.baseline?.sourceManifest?.sha256) {
  throw new Error('Behavior matrix is not bound to the reviewed v3.1.4 Python oracle source.');
}
const currentRustManifest = rustSourceManifest();
if (JSON.stringify(matrix.rustSourceManifest) !== JSON.stringify(currentRustManifest)
  || JSON.stringify(oracle.rustSourceManifest) !== JSON.stringify(currentRustManifest)) {
  throw new Error('Rust source changed after the behavior matrix/oracle capture; recapture and regenerate.');
}
const contractNames = contract.commands.map((item) => item.name);
const matrixNames = matrix.commands.map((item) => item.name);
if (contractNames.length !== 97 || new Set(contractNames).size !== 97
  || matrixNames.length !== 97 || new Set(matrixNames).size !== 97
  || contractNames.some((name, index) => matrixNames[index] !== name)) {
  throw new Error('Behavior matrix must cover all 97 contract commands in contract order.');
}
const oracleCommands = new Set(oracle.cases.map((item) => item.command));
const accepted = new Set(['equivalent', 'improved', 'security-exception']);
const scenarioStatuses = new Set(['covered', 'not-applicable']);
for (const command of matrix.commands) {
  if (command.owner !== 'rust' || command.channel !== 'rust_concurrent'
    || command.verificationStatus !== 'verified'
    || !accepted.has(command.capabilityStatus)
    || command.comparison?.safeBoundary === 'unexplained'
    || typeof command.comparison?.rationale !== 'string'
    || command.comparison.rationale.length < 20
    || !oracleCommands.has(command.name)) {
    throw new Error(`Command is incomplete or unexplained: ${command.name}`);
  }
  if (!command.request?.typedRustBoundary
    || JSON.stringify(command.response?.envelope) !== JSON.stringify(['ok', 'data', 'error'])) {
    throw new Error(`Typed request or response envelope evidence is missing: ${command.name}`);
  }
  for (const required of ['normal', 'invalid_request', 'missing_configuration', 'overwrite_or_conflict', 'side_effects']) {
    const scenario = command.scenarios?.[required];
    if (!scenario || !scenarioStatuses.has(scenario.status)
      || (scenario.status === 'covered' && !scenario.evidence?.length)
      || (scenario.status === 'not-applicable' && String(scenario.reason || '').length < 12)) {
      throw new Error(`Scenario ${required} is incomplete for ${command.name}`);
    }
  }
  if (command.surfaces?.taskState?.applicable) {
    for (const required of ['start_status_stop', 'restart_recovery', 'late_result_generation']) {
      const scenario = command.scenarios?.[required];
      if (scenario?.status !== 'covered' || !scenario.evidence?.length) {
        throw new Error(`Async scenario ${required} is incomplete for ${command.name}`);
      }
    }
  }
  const evidence = [
    ...(command.evidence || []),
    ...Object.values(command.scenarios || {}).flatMap((item) => item.evidence || []),
    ...Object.values(command.surfaces || {}).flatMap((item) => item.evidence || []),
  ];
  evidence.forEach((item) => evidenceExists(item, command.name));
}

const fixtures = new Map(matrix.goldenFixtures.map((item) => [item.file, item]));
for (const [relative, item] of fixtures) {
  const file = regularFile(relative, 'Golden fixture');
  const bytes = normalizedTextBytes(file);
  if (bytes.length !== item.bytes || sha256(bytes) !== item.sha256) {
    throw new Error(`Golden fixture drifted after matrix generation: ${relative}`);
  }
}
const expectedFixtureFiles = fs.readdirSync(path.dirname(oraclePath))
  .filter((name) => name.endsWith('.json'))
  .map((name) => `tauri-ui/src-tauri/fixtures/python_oracle/${name}`)
  .sort();
if (JSON.stringify([...fixtures.keys()].sort()) !== JSON.stringify(expectedFixtureFiles)) {
  throw new Error('Behavior matrix golden fixture inventory is incomplete.');
}
const verified = matrix.commands.filter((item) => item.verificationStatus === 'verified').length;
const unexplained = matrix.commands.filter((item) => item.comparison.safeBoundary === 'unexplained').length;
if (verified !== 97 || unexplained !== 0
  || matrix.summary?.verifiedCount !== 97
  || matrix.summary?.unverifiedCount !== 0
  || matrix.summary?.unexplainedDifferenceCount !== 0) {
  throw new Error(`Behavior completion gate failed: verified=${verified}, unexplained=${unexplained}`);
}
console.log(`Behavior matrix verified: ${verified}/97 commands, zero unexplained differences.`);
