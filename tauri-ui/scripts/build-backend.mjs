import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const specPath = path.join(projectRoot, 'koi_backend.spec');
const releaseDir = path.join(projectRoot, 'dist-tauri', 'koi');
const legacyDistDir = path.join(projectRoot, 'dist');

fs.mkdirSync(releaseDir, { recursive: true });
fs.rmSync(path.join(releaseDir, 'koi-backend'), { recursive: true, force: true });
fs.rmSync(path.join(releaseDir, 'koi-backend.exe'), { force: true });
fs.rmSync(path.join(legacyDistDir, 'koi-backend'), { recursive: true, force: true });
fs.rmSync(path.join(legacyDistDir, 'koi-backend.exe'), { force: true });

const result = spawnSync('pyinstaller', ['--noconfirm', '--clean', '--distpath', releaseDir, specPath], {
  cwd: projectRoot,
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

process.exit(result.status ?? 1);
