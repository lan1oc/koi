import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import {
  RELEASE_COMMAND_COUNT,
  REQUIRED_SUPPLY_CHAIN_INPUTS,
  assertArtifactBuiltAfterStamp,
  assertCleanReleaseTree,
  assertGitTrackedInputs,
  assertPinnedReleaseVersion,
  cargoTargetCandidates,
  createSupplyChainInputs,
  normalizeFullSourceRevision,
  readBuildSourceStamp,
  resolveStrictSourceRevision,
  validatePortableEntryInventory,
  validateRustOnlyContract,
  verifyPortableArchive,
  verifySupplyChainInputs,
  writeBuildSourceStamp,
} from './release-gates.mjs';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');

function temporaryDirectory(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function write(root, relative, contents = 'fixture\n') {
  const destination = path.join(root, ...relative.split('/'));
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, contents);
  return destination;
}

function contractFixture() {
  const root = temporaryDirectory('koi-release-contract-');
  const contract = JSON.parse(fs.readFileSync(path.join(projectRoot, 'contracts', 'backend-commands.json'), 'utf8'));
  const registry = fs.readFileSync(path.join(projectRoot, contract.rustHandlerSource), 'utf8');
  write(root, 'contracts/backend-commands.json', `${JSON.stringify(contract)}\n`);
  write(root, contract.rustHandlerSource, registry);
  return { root, contract };
}

function runGit(root, args, extra = {}) {
  const result = spawnSync('git', args, {
    cwd: root,
    encoding: 'utf8',
    windowsHide: true,
    ...extra,
  });
  assert.equal(result.status, 0, String(result.stderr || result.stdout));
  return String(result.stdout || '').trim();
}

function makeStoredZip(entries) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  for (const [name, rawValue] of entries) {
    const nameBytes = Buffer.from(name, 'utf8');
    const value = Buffer.isBuffer(rawValue) ? rawValue : Buffer.from(rawValue);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0800, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt32LE(value.length, 18);
    local.writeUInt32LE(value.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    localParts.push(local, nameBytes, value);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(0x0314, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt32LE(value.length, 20);
    central.writeUInt32LE(value.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE((0o100644 << 16) >>> 0, 38);
    central.writeUInt32LE(offset, 42);
    centralParts.push(central, nameBytes);
    offset += local.length + nameBytes.length + value.length;
  }
  const central = Buffer.concat(centralParts);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(central.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...localParts, central, eocd]);
}

test('current KOI metadata and actual Rust registry are exactly 4.0.0 and 97/97', () => {
  assert.equal(assertPinnedReleaseVersion(projectRoot), '4.0.0');
  const inventory = validateRustOnlyContract(projectRoot);
  assert.equal(inventory.commandCount, RELEASE_COMMAND_COUNT);
  assert.equal(inventory.handlerCount, RELEASE_COMMAND_COUNT);
});

test('strict version gate rejects overrides and drift between Cargo and package metadata', () => {
  const root = temporaryDirectory('koi-release-version-');
  try {
    write(root, 'tauri-ui/src-tauri/Cargo.toml', '[package]\nversion = "4.0.0"\n');
    write(root, 'tauri-ui/package.json', '{"version":"4.0.0"}\n');
    assert.equal(assertPinnedReleaseVersion(root), '4.0.0');
    assert.throws(() => assertPinnedReleaseVersion(root, '4.0.1'), /refusing expected-version override/);
    write(root, 'tauri-ui/package.json', '{"version":"4.0.1"}\n');
    assert.throws(() => assertPinnedReleaseVersion(root), /must all equal 4\.0\.0/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

for (const [label, mutate, expected] of [
  ['Python owner', (contract) => { contract.commands[0].owner = 'python'; }, /owner=python/],
  ['Python serial channel', (contract) => { contract.commands[0].channel = 'python_serial'; }, /channel=python_serial/],
  ['missing command', (contract) => { contract.commands.pop(); }, /exactly 97 commands/],
]) {
  test(`strict command gate rejects ${label}`, () => {
    const fixture = contractFixture();
    try {
      mutate(fixture.contract);
      write(fixture.root, 'contracts/backend-commands.json', `${JSON.stringify(fixture.contract)}\n`);
      assert.throws(() => validateRustOnlyContract(fixture.root), expected);
    } finally {
      fs.rmSync(fixture.root, { recursive: true, force: true });
    }
  });
}

test('strict command gate rejects a declared command without an actual Rust registration', () => {
  const fixture = contractFixture();
  try {
    const registryPath = path.join(fixture.root, fixture.contract.rustHandlerSource);
    const source = fs.readFileSync(registryPath, 'utf8');
    fs.writeFileSync(registryPath, source.replace('name: "app.version"', 'name: "not.in.contract"'));
    assert.throws(() => validateRustOnlyContract(fixture.root), /disagree/);
  } finally {
    fs.rmSync(fixture.root, { recursive: true, force: true });
  }
});

test('release trees reject bytecode caches and private state', () => {
  const root = temporaryDirectory('koi-release-tree-');
  try {
    write(root, 'safe/file.txt');
    assert.doesNotThrow(() => assertCleanReleaseTree(root));
    write(root, 'safe/__pycache__/module.pyc');
    assert.throws(() => assertCleanReleaseTree(root), /loose Python artifact/);
    fs.rmSync(path.join(root, 'safe', '__pycache__'), { recursive: true, force: true });
    write(root, 'nested/config.json', '{"api_key":"must-not-ship"}');
    assert.throws(() => assertCleanReleaseTree(root), /private runtime state/);
    fs.rmSync(path.join(root, 'nested'), { recursive: true, force: true });
    write(root, 'aiqicha_browser_profile/Default/Cookies', 'session-cookie');
    assert.throws(() => assertCleanReleaseTree(root), /private runtime state/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('release trees reject directory junctions instead of traversing them', (context) => {
  const root = temporaryDirectory('koi-release-link-');
  const target = temporaryDirectory('koi-release-link-target-');
  try {
    write(target, 'outside.txt');
    try {
      fs.symlinkSync(target, path.join(root, 'linked'), 'junction');
    } catch (error) {
      if (['EPERM', 'EACCES', 'UNKNOWN'].includes(error.code)) {
        context.skip(`Creating a test junction is unavailable: ${error.code}`);
        return;
      }
      throw error;
    }
    assert.throws(() => assertCleanReleaseTree(root), /symbolic link\/reparse entry/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
    fs.rmSync(target, { recursive: true, force: true });
  }
});

test('supply-chain inputs are complete and byte-for-byte verified', () => {
  const root = temporaryDirectory('koi-release-inputs-');
  try {
    for (const relative of REQUIRED_SUPPLY_CHAIN_INPUTS) write(root, relative, `${relative}\n`);
    const inputs = createSupplyChainInputs(root);
    assert.equal(inputs.length, REQUIRED_SUPPLY_CHAIN_INPUTS.length);
    assert.doesNotThrow(() => verifySupplyChainInputs(root, inputs));
    assert.throws(() => verifySupplyChainInputs(root, inputs.slice(1)), /exactly/);
    const tampered = structuredClone(inputs);
    tampered[0].bytes += 1;
    assert.throws(() => verifySupplyChainInputs(root, tampered), /hash or size/);
    write(root, REQUIRED_SUPPLY_CHAIN_INPUTS[0], 'changed\n');
    assert.throws(() => verifySupplyChainInputs(root, inputs), /hash or size/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('source revision must be the full clean checkout HEAD', () => {
  const root = temporaryDirectory('koi-release-git-');
  try {
    runGit(root, ['init']);
    runGit(root, ['config', 'user.name', 'KOI release test']);
    runGit(root, ['config', 'user.email', 'release-test@example.invalid']);
    write(root, 'tracked.txt');
    write(root, 'Report_Template/template.doc', 'reviewed template\n');
    runGit(root, ['add', 'tracked.txt', 'Report_Template/template.doc']);
    runGit(root, ['commit', '-m', 'fixture']);
    const head = runGit(root, ['rev-parse', '--verify', 'HEAD^{commit}']);
    assert.equal(resolveStrictSourceRevision(root, head), head);
    assert.throws(() => normalizeFullSourceRevision(head.slice(0, 12)), /full 40- or 64-character/);
    const differentHead = `${head[0] === 'f' ? 'e' : 'f'}${head.slice(1)}`;
    assert.throws(() => normalizeFullSourceRevision(differentHead, head), /does not equal/);
    write(root, 'Report_Template/template.doc', 'uncommitted user template change\n');
    assert.throws(() => resolveStrictSourceRevision(root, head), /completely clean source tree/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('strict resource inventory rejects ignored local files that Git status would hide', () => {
  const root = temporaryDirectory('koi-release-tracked-');
  try {
    runGit(root, ['init']);
    runGit(root, ['config', 'user.name', 'KOI release test']);
    runGit(root, ['config', 'user.email', 'release-test@example.invalid']);
    write(root, '.gitignore', '*.pyd\n');
    write(root, 'runtime/python.exe', 'tracked runtime');
    runGit(root, ['add', '.gitignore', 'runtime/python.exe']);
    runGit(root, ['commit', '-m', 'fixture']);
    assert.doesNotThrow(() => assertGitTrackedInputs(root, ['runtime']));
    write(root, 'runtime/_socket.pyd', 'ignored but package-visible');
    assert.equal(runGit(root, ['status', '--porcelain=v1', '--untracked-files=all']), '');
    assert.throws(() => assertGitTrackedInputs(root, ['runtime']), /untracked\/ignored/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('build source stamp binds packaging to the preflight checkout', () => {
  const root = temporaryDirectory('koi-release-stamp-');
  try {
    const revision = '0123456789abcdef0123456789abcdef01234567';
    const stampPath = writeBuildSourceStamp(root, revision);
    assert.equal(readBuildSourceStamp(root, revision).stampPath, stampPath);
    const artifact = write(root, 'target/release/koi.exe', 'binary');
    const stampTime = fs.statSync(stampPath).mtime;
    fs.utimesSync(artifact, new Date(stampTime.getTime() - 2_000), new Date(stampTime.getTime() - 2_000));
    assert.throws(() => assertArtifactBuiltAfterStamp(artifact, stampPath), /predates/);
    fs.utimesSync(artifact, new Date(stampTime.getTime() + 2_000), new Date(stampTime.getTime() + 2_000));
    assert.doesNotThrow(() => assertArtifactBuiltAfterStamp(artifact, stampPath));
    assert.throws(
      () => readBuildSourceStamp(root, '1123456789abcdef0123456789abcdef01234567'),
      /does not equal/,
    );
    const stamp = JSON.parse(fs.readFileSync(stampPath, 'utf8'));
    stamp.version = '4.0.1';
    fs.writeFileSync(stampPath, JSON.stringify(stamp));
    assert.throws(() => readBuildSourceStamp(root, revision), /does not match/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('relative CARGO_TARGET_DIR follows the invoking Cargo working directory first', () => {
  const project = path.join(os.tmpdir(), 'koi-project-root-fixture');
  const candidates = cargoTargetCandidates(project, '.cargo-release-fixture');
  assert.equal(candidates[0], path.resolve('.cargo-release-fixture'));
  assert.ok(candidates.includes(path.resolve(project, 'tauri-ui', 'src-tauri', '.cargo-release-fixture')));
});

test('portable entry gate rejects symlinks, Python caches, and secret state names', () => {
  const baseline = [
    { name: 'koi/koi.exe' },
    { name: 'koi-data/enterprise_classification.db' },
    { name: 'koi-data/Report_Template/template.doc' },
    { name: 'koi-data/templates/template.json' },
    { name: 'release-manifest.json' },
    { name: 'koi-portable.marker' },
  ];
  assert.doesNotThrow(() => validatePortableEntryInventory(baseline));
  assert.throws(
    () => validatePortableEntryInventory([...baseline, { name: 'koi/cache/result.pyo' }]),
    /loose Python artifact/,
  );
  assert.throws(
    () => validatePortableEntryInventory([...baseline, { name: 'koi-data/secrets.dpapi.json' }]),
    /private runtime state/,
  );
  assert.throws(
    () => validatePortableEntryInventory([...baseline, { name: 'koi/linked', symbolicLink: true }]),
    /symbolic link/,
  );
});

test('portable ZIP contents must exactly match the staged trees and manifests', () => {
  const root = temporaryDirectory('koi-release-zip-');
  try {
    const app = path.join(root, 'koi');
    const data = path.join(root, 'koi-data');
    const manifest = write(root, 'release-manifest.json', '{"format":"fixture"}\n');
    const marker = write(root, 'koi-portable.marker', '{"format":"fixture-marker"}\n');
    const entries = [
      ['koi/koi.exe', 'exe'],
      ['koi-data/enterprise_classification.db', 'db'],
      ['koi-data/Report_Template/template.doc', 'doc'],
      ['koi-data/templates/template.json', '{}'],
      ['release-manifest.json', fs.readFileSync(manifest)],
      ['koi-portable.marker', fs.readFileSync(marker)],
    ];
    for (const [name, value] of entries.slice(0, 4)) write(root, name, value);
    const zip = write(root, 'portable.zip', makeStoredZip(entries));
    assert.doesNotThrow(() => verifyPortableArchive(zip, {
      releaseManifestPath: manifest,
      portableMarkerPath: marker,
      expectedTrees: [{ prefix: 'koi', root: app }, { prefix: 'koi-data', root: data }],
    }));
    write(root, 'koi/koi.exe', 'different');
    assert.throws(() => verifyPortableArchive(zip, {
      releaseManifestPath: manifest,
      portableMarkerPath: marker,
      expectedTrees: [{ prefix: 'koi', root: app }, { prefix: 'koi-data', root: data }],
    }), /does not match/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
