import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import {
  verifyArchiveRuntimeProvenance,
  verifyLockedRuntime,
  verifyProbeRuntime,
} from './locked-runtime.mjs';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const lockPath = path.join(projectRoot, 'archive-runtime.lock.json');
const runtimeDir = path.join(projectRoot, 'archive-runtime');
const probeLockPath = path.join(projectRoot, 'probe-runtime.lock.json');
const probeRuntimeDir = path.join(projectRoot, 'probe-runtime');

function loadVerifiedLock() {
  return verifyLockedRuntime({
    lockPath,
    runtimeDir,
    expectedFormat: 'koi-archive-runtime-v3',
  });
}

test('accepts only the publisher-signed NanaZip package and bound runtime files', () => {
  const lock = loadVerifiedLock();
  assert.equal(verifyArchiveRuntimeProvenance(lock, runtimeDir), lock);
  assert.equal(lock.trust.publisher_authenticated, true);
  assert.equal(lock.trust.publisher_signature.package, 'authenticode-valid');
  assert.equal(lock.trust.publisher_signature.runtime_binding, 'byte-identical-msix-entries');
});

test('rejects a lock that weakens publisher authentication', () => {
  const lock = structuredClone(loadVerifiedLock());
  lock.trust.publisher_authenticated = false;
  lock.trust.publisher_signature.package = 'not-signed';
  assert.throws(
    () => verifyArchiveRuntimeProvenance(lock, runtimeDir),
    /trust declaration/,
  );
});

test('rejects a NanaZip MSIX whose publisher signature no longer validates', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-archive-runtime-trust-'));
  try {
    fs.cpSync(runtimeDir, temporary, { recursive: true });
    const signedPackage = path.join(temporary, 'NanaZipPackage_7.0.1832.0_x64.msix');
    const bytes = fs.readFileSync(signedPackage);
    bytes[1024] ^= 1;
    fs.writeFileSync(signedPackage, bytes);
    assert.throws(
      () => verifyArchiveRuntimeProvenance(loadVerifiedLock(), temporary),
      /publisher signature|could not run/,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test('rejects a runtime file that is not byte-identical to its signed MSIX entry', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-archive-runtime-binding-'));
  try {
    fs.cpSync(runtimeDir, temporary, { recursive: true });
    const executable = path.join(temporary, 'NanaZip.Universal.Console.exe');
    const bytes = fs.readFileSync(executable);
    bytes[1024] ^= 1;
    fs.writeFileSync(executable, bytes);
    assert.throws(
      () => verifyArchiveRuntimeProvenance(loadVerifiedLock(), temporary),
      /not byte-identical/,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test('accepts only the complete hash-locked official CPython probe runtime', () => {
  const lock = verifyProbeRuntime({ lockPath: probeLockPath, runtimeDir: probeRuntimeDir });
  assert.equal(lock.version, '3.13.15');
  assert.equal(lock.url, 'https://www.python.org/ftp/python/3.13.15/python-3.13.15-embed-amd64.zip');
});

test('rejects an incomplete or relabeled CPython probe runtime lock', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-probe-runtime-lock-'));
  try {
    const lock = JSON.parse(fs.readFileSync(probeLockPath, 'utf8'));
    lock.files.pop();
    const temporaryLock = path.join(temporary, 'probe-runtime.lock.json');
    fs.writeFileSync(temporaryLock, `${JSON.stringify(lock)}\n`);
    assert.throws(
      () => verifyProbeRuntime({ lockPath: temporaryLock, runtimeDir: probeRuntimeDir }),
      /inventory mismatch/,
    );
    lock.url = 'https://example.invalid/python.zip';
    fs.writeFileSync(temporaryLock, `${JSON.stringify(lock)}\n`);
    assert.throws(
      () => verifyProbeRuntime({ lockPath: temporaryLock, runtimeDir: probeRuntimeDir }),
      /reviewed official CPython/,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
