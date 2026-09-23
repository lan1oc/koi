import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const script = fs.readFileSync(path.join(root, 'push_workflow.ps1'));
const options = { skip: process.platform !== 'win32' };
function git(cwd, ...args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr);
  return result.stdout.trim();
}
function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-push-test-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const repo = path.join(directory, 'repo');
  const remote = path.join(directory, 'origin.git');
  fs.mkdirSync(repo);
  git(directory, 'init', '--bare', remote);
  git(repo, 'init', '-b', 'main');
  git(repo, 'config', 'user.name', 'Release test');
  git(repo, 'config', 'user.email', 'release@example.invalid');
  git(repo, 'config', 'commit.gpgsign', 'false');
  git(repo, 'remote', 'add', 'origin', remote);
  fs.mkdirSync(path.join(repo, 'tauri-ui/src-tauri'), { recursive: true });
  fs.mkdirSync(path.join(repo, '.github/workflows'), { recursive: true });
  fs.writeFileSync(path.join(repo, 'tauri-ui/src-tauri/Cargo.toml'), '[package]\nversion = "4.0.0"\n');
  fs.writeFileSync(path.join(repo, '.github/workflows/release.yml'), 'name: Release\n');
  fs.writeFileSync(path.join(repo, 'push_workflow.ps1'), script);
  git(repo, 'add', '.');
  git(repo, 'commit', '-m', 'initial fixture');
  return { repo, remote, initial: git(repo, 'rev-parse', 'HEAD') };
}
function run(repo, ...args) {
  return spawnSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(repo, 'push_workflow.ps1'), ...args], {
    cwd: repo, encoding: 'utf8', windowsHide: true, timeout: 30000,
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0' },
  });
}

test('dirty tree rejects unrelated staged changes', options, (t) => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.repo, 'feature.rs'), 'new source\n');
  git(f.repo, 'add', 'feature.rs');
  const before = git(f.repo, 'status', '--porcelain');
  const result = run(f.repo);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Uncommitted release changes/);
  assert.equal(git(f.repo, 'rev-parse', 'HEAD'), f.initial);
  assert.equal(git(f.repo, 'status', '--porcelain'), before);
  assert.equal(git(f.repo, 'tag', '--list'), '');
});

test('unreachable origin stops before commit and preserves local tag', options, (t) => {
  const f = fixture(t);
  git(f.repo, 'remote', 'set-url', 'origin', path.join(f.repo, 'missing-origin'));
  git(f.repo, 'tag', 'v4.0.0');
  fs.writeFileSync(path.join(f.repo, 'feature.rs'), 'new source\n');
  const result = run(f.repo, '-CommitChanges');
  assert.notEqual(result.status, 0);
  assert.equal(git(f.repo, 'rev-parse', 'HEAD'), f.initial);
  assert.equal(git(f.repo, 'rev-parse', 'v4.0.0'), f.initial);
  assert.doesNotMatch(result.stdout, /Source and release tag verified/);
});

test('complete commit pushes branch and tag atomically', options, (t) => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.repo, 'feature.rs'), 'reviewed source\n');
  const result = run(f.repo, '-CommitChanges', '-CommitMessage', 'fix: include complete source');
  assert.equal(result.status, 0, result.stderr);
  const head = git(f.repo, 'rev-parse', 'HEAD');
  assert.notEqual(head, f.initial);
  assert.equal(git(f.remote, 'rev-parse', 'main'), head);
  assert.equal(git(f.remote, 'rev-parse', 'v4.0.0'), head);
  assert.equal(git(f.repo, 'status', '--porcelain'), '');
  assert.match(result.stdout, /successful push is not a successful build/);
});

test('push rejection restores local tag and leaves remote refs intact', options, (t) => {
  const f = fixture(t);
  git(f.repo, 'tag', 'v4.0.0');
  git(f.repo, 'push', 'origin', 'main', 'v4.0.0');
  fs.writeFileSync(path.join(f.repo, 'feature.rs'), 'new source\n');
  git(f.repo, 'add', '.');
  git(f.repo, 'commit', '-m', 'next');
  fs.writeFileSync(path.join(f.remote, 'hooks/pre-receive'), '#!/bin/sh\nexit 1\n', { mode: 0o755 });
  const result = run(f.repo, '-Force');
  assert.notEqual(result.status, 0);
  assert.equal(git(f.repo, 'rev-parse', 'v4.0.0'), f.initial);
  assert.equal(git(f.remote, 'rev-parse', 'main'), f.initial);
  assert.equal(git(f.remote, 'rev-parse', 'v4.0.0'), f.initial);
  assert.doesNotMatch(result.stdout, /Source and release tag verified/);
});

test('dry run does not mutate index commits tags or remote refs', options, (t) => {
  const f = fixture(t);
  fs.writeFileSync(path.join(f.repo, 'feature.rs'), 'local source\n');
  const before = git(f.repo, 'status', '--porcelain');
  const result = run(f.repo, '-DryRun', '-CommitChanges');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(git(f.repo, 'status', '--porcelain'), before);
  assert.equal(git(f.repo, 'rev-parse', 'HEAD'), f.initial);
  assert.equal(git(f.repo, 'tag', '--list'), '');
  assert.equal(git(f.remote, 'for-each-ref', '--format=%(refname)'), '');
});
