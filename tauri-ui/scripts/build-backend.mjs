import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const specPath = path.join(projectRoot, 'koi_backend.spec');
const configuredReleaseBase = String(process.env.KOI_RELEASE_BASE || '').trim();
const releaseBase = configuredReleaseBase
  ? path.resolve(projectRoot, configuredReleaseBase)
  : path.join(projectRoot, 'dist-tauri', 'koi');
const releaseDir = configuredReleaseBase ? path.join(releaseBase, 'koi') : releaseBase;
const legacyDistDir = path.join(projectRoot, 'dist');

fs.mkdirSync(releaseDir, { recursive: true });
fs.rmSync(path.join(releaseDir, 'koi-backend'), { recursive: true, force: true });
fs.rmSync(path.join(releaseDir, 'koi-backend.exe'), { force: true });
if (!configuredReleaseBase) {
  fs.rmSync(path.join(legacyDistDir, 'koi-backend'), { recursive: true, force: true });
  fs.rmSync(path.join(legacyDistDir, 'koi-backend.exe'), { force: true });
}

const targetDir = String(process.env.CARGO_TARGET_DIR || '').trim();
const pyinstallerArgs = [
  '--noconfirm',
  '--clean',
  '--distpath',
  releaseDir,
  specPath,
];
console.log(`Building Python backend into: ${releaseDir}`);
if (targetDir) console.log(`Cargo target isolation: ${targetDir}`);

const result = spawnSync('pyinstaller', pyinstallerArgs, {
  cwd: projectRoot,
  stdio: 'inherit',
  shell: process.platform === 'win32',
});

process.exit(result.status ?? 1);
