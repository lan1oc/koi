import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function inventory(root) {
  const files = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const stat = fs.lstatSync(fullPath);
      if (stat.isSymbolicLink()) throw new Error(`Locked runtime contains a symbolic link: ${fullPath}`);
      if (stat.isDirectory()) pending.push(fullPath);
      else if (stat.isFile()) files.push(path.relative(root, fullPath).replaceAll('\\', '/'));
      else throw new Error(`Locked runtime contains an unsupported entry: ${fullPath}`);
    }
  }
  return files.sort();
}

export function verifyLockedRuntime({
  lockPath,
  runtimeDir,
  expectedFormat,
  expectedPlatform = 'windows-x64',
}) {
  if (!fs.statSync(lockPath, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`Missing locked runtime manifest: ${lockPath}`);
  }
  if (!fs.statSync(runtimeDir, { throwIfNoEntry: false })?.isDirectory()) {
    throw new Error(`Missing locked runtime directory: ${runtimeDir}`);
  }
  const lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  if (lock.format !== expectedFormat || lock.platform !== expectedPlatform || !Array.isArray(lock.files)) {
    throw new Error(`Locked runtime manifest has an unexpected format or platform: ${lockPath}`);
  }
  const expected = new Set();
  for (const entry of lock.files) {
    const relative = String(entry?.path || '');
    if (!relative
      || relative.includes('\\')
      || path.posix.isAbsolute(relative)
      || path.posix.normalize(relative) !== relative
      || relative.split('/').includes('..')
      || expected.has(relative)) {
      throw new Error(`Locked runtime manifest contains an unsafe or duplicate path: ${relative}`);
    }
    if (!Number.isSafeInteger(entry.size) || entry.size <= 0 || !/^[0-9a-f]{64}$/.test(String(entry.sha256 || ''))) {
      throw new Error(`Locked runtime manifest contains invalid metadata: ${relative}`);
    }
    expected.add(relative);
    const fullPath = path.join(runtimeDir, ...relative.split('/'));
    const stat = fs.statSync(fullPath, { throwIfNoEntry: false });
    if (!stat?.isFile() || stat.size !== entry.size || sha256(fullPath) !== entry.sha256) {
      throw new Error(`Locked runtime file failed size/hash verification: ${fullPath}`);
    }
  }
  const actual = inventory(runtimeDir);
  const missing = [...expected].filter((relative) => !actual.includes(relative));
  const extra = actual.filter((relative) => !expected.has(relative));
  if (missing.length || extra.length) {
    throw new Error(`Locked runtime inventory mismatch (missing: ${missing.join(', ')}; extra: ${extra.join(', ')})`);
  }
  return lock;
}

export function verifyArchiveRuntimeProvenance(lock) {
  const expectedFiles = new Map([
    ['7z.exe', ['console-runtime', 576000, '83967f1b02b43c4efeda302795722c809e0e81b8307de73558d10484d5676a7d']],
    ['7z.dll', ['codec-runtime', 1906688, '69fd4df057985c40e510e2fac182881c7f85e90aa13ec703f763a8fdb2ce61f8']],
    ['License.txt', ['license', 6031, '519ac0a4bded9c18ea02e0afb71f663d8c47373bd9facd3ac96a79f51d77765d']],
  ]);
  const validSource = lock?.format === 'koi-archive-runtime-v1'
    && lock.version === '26.02'
    && lock.platform === 'windows-x64'
    && lock.architecture === 'x86_64'
    && lock.executable === '7z.exe'
    && lock.source?.project === '7-Zip'
    && lock.source?.upstream_url === 'https://www.7-zip.org/'
    && lock.source?.release_url === 'https://github.com/ip7z/7zip/releases/tag/26.02'
    && lock.source?.installer_url === 'https://github.com/ip7z/7zip/releases/download/26.02/7z2602-x64.exe'
    && lock.source?.installer_size === 1657896
    && lock.source?.installer_sha256 === '6745fa76dc2ea031596d8678f6f6b99c3c1b435b4164a63485adbbc7b8d82ef0'
    && lock.licenses?.console_spdx === 'LGPL-2.1-or-later'
    && lock.licenses?.notice_file === 'License.txt'
    && String(lock.licenses?.library_summary || '').includes('LicenseRef-unRAR-restriction');
  const files = Array.isArray(lock?.files) ? lock.files : [];
  const validFiles = files.length === expectedFiles.size && files.every((entry) => {
    const expected = expectedFiles.get(entry.path);
    return expected
      && entry.role === expected[0]
      && entry.size === expected[1]
      && entry.sha256 === expected[2];
  });
  if (!validSource || !validFiles) {
    throw new Error('Archive runtime provenance does not match the reviewed 7-Zip 26.02 Windows x64 artifact.');
  }
  return lock;
}

export function verifyExternalToolsLock(lockPath) {
  if (!fs.statSync(lockPath, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`Missing external tool lock: ${lockPath}`);
  }
  let lock;
  try {
    lock = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  } catch (error) {
    throw new Error(`External tool lock is invalid JSON: ${error.message}`);
  }
  if (lock?.format !== 'koi-retest-tools-lock-v1'
    || lock.platform !== 'windows-x64'
    || !Array.isArray(lock.artifacts)
    || lock.artifacts.length !== 2) {
    throw new Error('External tool lock has an unexpected format, platform, or artifact count.');
  }
  const reviewed = new Map([
    ['ffuf', {
      version: '2.2.1',
      url: 'https://github.com/ffuf/ffuf/releases/download/v2.2.1/ffuf_2.2.1_windows_amd64.zip',
      size: 4205507,
      sha256: '717e3d103ee36ce743a18605be66a4424fca27758eebed1e8ebb2eb0a3645589',
      archiveFormat: 'zip',
      executable: 'ffuf.exe',
      machine: 'x86_64',
    }],
    ['nmap', {
      version: '7.991',
      url: 'https://nmap.org/dist/nmap-7.991-setup.exe',
      size: 37378768,
      sha256: '93bfd37bdb31a7adfd932beb5dbce06025da691d01a0939e806ea704f7367657',
      archiveFormat: 'nsis',
      executable: 'nmap.exe',
      machine: 'x86',
    }],
  ]);
  const seenTools = new Set();
  for (const artifact of lock.artifacts) {
    const expected = reviewed.get(artifact?.tool);
    if (!expected || seenTools.has(artifact.tool)
      || artifact.version !== expected.version
      || artifact.url !== expected.url
      || artifact.size !== expected.size
      || artifact.sha256 !== expected.sha256
      || artifact.archive_format !== expected.archiveFormat
      || artifact.executable !== expected.executable
      || artifact.executable_machine !== expected.machine
      || typeof artifact.license !== 'string'
      || !artifact.license.trim()
      || !Array.isArray(artifact.files)
      || !artifact.files.length
      || artifact.files.length > 64
      || !Array.isArray(artifact.trees)
      || artifact.trees.length > 8) {
      throw new Error(`External tool provenance is not reviewed: ${artifact?.tool || '<missing>'}`);
    }
    seenTools.add(artifact.tool);
    const archivePaths = new Set();
    const installPaths = new Set();
    let executableCount = 0;
    for (const entry of artifact.files) {
      for (const [label, relative] of [['archive', entry?.archive_path], ['install', entry?.install_path]]) {
      if (typeof relative !== 'string'
          || !relative
          || relative.includes('\\')
          || relative.includes(':')
          || relative.includes('*')
          || relative.includes('?')
          || path.posix.isAbsolute(relative)
          || path.posix.normalize(relative) !== relative
          || relative.split('/').some((part) => !part || part === '.' || part === '..')) {
          throw new Error(`External tool lock contains an unsafe ${label} path: ${relative}`);
        }
      }
      if (entry.archive_path.includes('/') || entry.install_path.includes('/')) {
        throw new Error(`External tool direct product paths must be top-level files: ${artifact.tool}/${entry.install_path}`);
      }
      if (!Number.isSafeInteger(entry.size)
        || entry.size <= 0
        || entry.size > 128 * 1024 * 1024
        || !/^[0-9a-f]{64}$/.test(String(entry.sha256 || ''))
        || typeof entry.role !== 'string'
        || !entry.role
        || archivePaths.has(entry.archive_path)
        || installPaths.has(entry.install_path)) {
        throw new Error(`External tool product inventory is invalid: ${artifact.tool}/${entry?.install_path}`);
      }
      archivePaths.add(entry.archive_path);
      installPaths.add(entry.install_path);
      if (entry.install_path === artifact.executable && entry.role === 'executable') executableCount += 1;
    }
    if (executableCount !== 1) {
      throw new Error(`External tool lock must identify exactly one executable: ${artifact.tool}`);
    }
    const expectedDirectFiles = artifact.tool === 'ffuf'
      ? ['CHANGELOG.md', 'LICENSE', 'README.md', 'ffuf.exe']
      : [
          '3rd-party-licenses.txt', 'CHANGELOG', 'LICENSE', 'README-WIN32',
          'libcrypto-3.dll', 'libssh2.dll', 'libssl-3.dll', 'nmap-mac-prefixes',
          'nmap-os-db', 'nmap-protocols', 'nmap-rpc', 'nmap-service-probes',
          'nmap-services', 'nmap.exe', 'nmap.xsl', 'nse_main.lua', 'zlibwapi.dll',
        ];
    if (installPaths.size !== expectedDirectFiles.length
      || expectedDirectFiles.some((relative) => !installPaths.has(relative))) {
      throw new Error(`External tool direct product inventory is not reviewed: ${artifact.tool}`);
    }
    const treeRoots = new Set();
    for (const tree of artifact.trees) {
      const root = tree?.install_root;
      if (typeof root !== 'string'
        || !root
        || root.includes('/')
        || root.includes('\\')
        || root.includes(':')
        || tree.archive_glob !== `${root}/*`
        || treeRoots.has(root)
        || installPaths.has(root)
        || !Number.isSafeInteger(tree.file_count)
        || tree.file_count <= 0
        || tree.file_count > 2000
        || !Number.isSafeInteger(tree.directory_count)
        || tree.directory_count < 0
        || tree.directory_count > 512
        || !Number.isSafeInteger(tree.total_size)
        || tree.total_size <= 0
        || tree.total_size > 128 * 1024 * 1024
        || !/^[0-9a-f]{64}$/.test(String(tree.manifest_sha256 || ''))
        || typeof tree.role !== 'string'
        || !tree.role) {
        throw new Error(`External tool product tree is invalid: ${artifact.tool}/${root}`);
      }
      treeRoots.add(root);
    }
    if (artifact.tool === 'ffuf' && treeRoots.size !== 0) {
      throw new Error('ffuf product lock must not contain directory trees.');
    }
    if (artifact.tool === 'nmap'
      && (treeRoots.size !== 2 || !treeRoots.has('nselib') || !treeRoots.has('scripts'))) {
      throw new Error('nmap product lock must contain exactly nselib and scripts trees.');
    }
    if (artifact.tool === 'nmap') {
      const nselib = artifact.trees.find((tree) => tree.install_root === 'nselib');
      const scripts = artifact.trees.find((tree) => tree.install_root === 'scripts');
      if (nselib.file_count !== 186
        || nselib.directory_count !== 3
        || nselib.total_size !== 8223140
        || nselib.manifest_sha256 !== '3b405a9f40dbc985c40c7fc5a5a20a8d76f5a19ac3f1d3562660398ef3842b6b'
        || scripts.file_count !== 612
        || scripts.directory_count !== 0
        || scripts.total_size !== 3895325
        || scripts.manifest_sha256 !== '740f923b6d74000195400302790adb9a57dab92a4db6ffd3d943c6a21a696085') {
        throw new Error('nmap product tree fingerprints are not reviewed.');
      }
    }
  }
  if (seenTools.size !== reviewed.size) {
    throw new Error('External tool lock must contain exactly nmap and ffuf.');
  }
  return lock;
}
