import crypto from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';

const BASELINE_REVISION = 'f059eacf18de2bc2c888d901d257a59cbe8e12ca';
const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const contractPath = path.join(projectRoot, 'contracts', 'backend-commands.json');

function parseArgs(argv) {
  const options = {
    oracleRoot: '',
    rustDriver: path.join(projectRoot, 'tauri-ui', 'src-tauri', 'target', 'debug', 'examples', 'backend_protocol_driver.exe'),
    output: path.join(projectRoot, 'tauri-ui', 'src-tauri', 'fixtures', 'python_oracle', 'command_boundaries.v1.json'),
    python: process.env.PYTHON || 'python.exe',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === '--oracle-root' || key === '--rust-driver' || key === '--output' || key === '--python') {
      if (!value) throw new Error(`${key} requires a value`);
      const property = {
        '--oracle-root': 'oracleRoot',
        '--rust-driver': 'rustDriver',
        '--output': 'output',
        '--python': 'python',
      }[key];
      options[property] = value;
      index += 1;
    } else {
      throw new Error(`Unsupported argument: ${key}`);
    }
  }
  if (!options.oracleRoot) throw new Error('--oracle-root is required');
  options.oracleRoot = path.resolve(options.oracleRoot);
  options.rustDriver = path.resolve(options.rustDriver);
  options.output = path.resolve(options.output);
  return options;
}

function runGit(root, args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true });
  if (result.status !== 0) {
    throw new Error(`git ${args.join(' ')} failed: ${String(result.stderr || result.stdout).trim()}`);
  }
  return String(result.stdout || '').trim();
}

function requireCleanBaseline(root) {
  const revision = runGit(root, ['rev-parse', '--verify', 'HEAD^{commit}']);
  if (revision !== BASELINE_REVISION) {
    throw new Error(`Oracle checkout must be ${BASELINE_REVISION}; found ${revision}`);
  }
  const status = runGit(root, ['status', '--porcelain=v1', '--untracked-files=all']);
  if (status) throw new Error(`Oracle checkout must be clean:\n${status}`);
}

function walkFiles(root, predicate = () => true) {
  const files = [];
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const stat = fs.lstatSync(fullPath);
      if (stat.isSymbolicLink()) throw new Error(`Oracle source contains a symlink: ${fullPath}`);
      if (stat.isDirectory()) pending.push(fullPath);
      else if (stat.isFile() && predicate(fullPath)) files.push(fullPath);
    }
  }
  return files.sort((left, right) => left.localeCompare(right, 'en'));
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function normalizedTextBytes(file) {
  return Buffer.from(fs.readFileSync(file, 'utf8').replaceAll('\r\n', '\n'), 'utf8');
}

function legacySourceManifest(oracleRoot) {
  const modules = path.join(oracleRoot, 'modules');
  const records = walkFiles(modules, (file) => file.toLowerCase().endsWith('.py')).map((file) => ({
    file: path.relative(oracleRoot, file).replaceAll('\\', '/'),
    bytes: normalizedTextBytes(file).length,
    sha256: sha256(normalizedTextBytes(file)),
  }));
  return {
    fileCount: records.length,
    sha256: sha256(Buffer.from(JSON.stringify(records))),
    files: records,
  };
}

function rustSourceManifest() {
  const rustSourceRoot = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'src');
  const files = [
    ...walkFiles(rustSourceRoot, (file) => file.toLowerCase().endsWith('.rs')),
    path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml'),
    path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.lock'),
    path.join(projectRoot, 'contracts', 'backend-commands.json'),
    path.join(projectRoot, 'tauri-ui', 'src-tauri', 'examples', 'backend_protocol_driver.rs'),
  ].sort((left, right) => left.localeCompare(right, 'en'));
  const records = files.map((file) => ({
    file: path.relative(projectRoot, file).replaceAll('\\', '/'),
    bytes: normalizedTextBytes(file).length,
    sha256: sha256(normalizedTextBytes(file)),
  }));
  return {
    fileCount: records.length,
    sha256: sha256(Buffer.from(JSON.stringify(records))),
  };
}

function copyMissingTree(source, destination) {
  fs.mkdirSync(destination, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const from = path.join(source, entry.name);
    const to = path.join(destination, entry.name);
    const stat = fs.lstatSync(from);
    if (stat.isSymbolicLink()) throw new Error(`Seed tree contains a symlink: ${from}`);
    if (stat.isDirectory()) copyMissingTree(from, to);
    else if (stat.isFile() && !fs.existsSync(to)) fs.copyFileSync(from, to, fs.constants.COPYFILE_EXCL);
  }
}

function prepareLegacyData(oracleRoot, dataDir) {
  fs.mkdirSync(dataDir, { recursive: true });
  fs.copyFileSync(
    path.join(oracleRoot, 'enterprise_classification.db'),
    path.join(dataDir, 'enterprise_classification.db'),
    fs.constants.COPYFILE_EXCL,
  );
  copyMissingTree(path.join(oracleRoot, 'Report_Template'), path.join(dataDir, 'Report_Template'));
  copyMissingTree(
    path.join(oracleRoot, 'modules', 'data_processing', 'templates'),
    path.join(dataDir, 'templates'),
  );
  // The v3 resource initializer copies a root config.json only when the data
  // directory has none. Always pre-seed a deterministic blank configuration
  // so an auditor's real credentials can never enter a capture.
  fs.writeFileSync(path.join(dataDir, 'config.json'), `${JSON.stringify({
    hunter: { api_key: '', last_updated: '' },
    quake: { api_key: '', last_updated: '' },
    fofa: { email: '', api_key: '', last_updated: '' },
    aiqicha: { cookie: '', xunkebao_cookie: '', last_updated: '' },
    tyc: { cookie: '', last_updated: '' },
    ui: {
      theme: 'default',
      window_size: { width: 1400, height: 900 },
      window_position: { x: -1, y: -1 },
      dark_mode: false,
      last_updated: '',
    },
    ui_settings: { dark_mode: false, close_to_tray: false, last_updated: '' },
    app: { first_run: true, last_updated: '' },
    report_counters: {
      notification_number: 1,
      rectification_number: 1,
      unavailable_notification_numbers: [],
      unavailable_rectification_numbers: [],
      year: 2026,
      last_updated: '',
    },
    weekly_report: {
      vulnerability_notice_dir: '',
      event_notice_dir: '',
      exclude_monday_next_notice: false,
      last_updated: '',
    },
    debug: { tianyancha_debug_output: false, tianyancha_console_log: false, last_updated: '' },
    retest_ai_agent: {
      enabled: false,
      active_profile_id: 'default',
      profiles: [{
        id: 'default',
        name: '默认 OpenAI',
        provider: 'openai',
        base_url: '',
        api_key: '',
        model: '',
        temperature: 0.1,
        max_tokens: 800,
        last_updated: '',
      }],
      last_updated: '',
    },
    threatbook_api_key: '',
  }, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
}

class LineClient {
  constructor(child, label) {
    this.child = child;
    this.label = label;
    this.pending = [];
    this.stderr = '';
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk) => {
      this.stderr = `${this.stderr}${chunk}`.slice(-32_768);
    });
    const lines = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });
    lines.on('line', (line) => {
      const pending = this.pending.shift();
      if (!pending) return;
      clearTimeout(pending.timer);
      try {
        pending.resolve(JSON.parse(line));
      } catch (error) {
        pending.reject(new Error(`${label} returned invalid JSON: ${line}\n${error.message}`));
      }
    });
    child.on('exit', (code) => {
      while (this.pending.length) {
        const pending = this.pending.shift();
        clearTimeout(pending.timer);
        pending.reject(new Error(`${label} exited with code ${code}: ${this.stderr}`));
      }
    });
  }

  request(value, timeoutMs = 15_000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const index = this.pending.findIndex((item) => item.timer === timer);
        if (index >= 0) this.pending.splice(index, 1);
        reject(new Error(`${this.label} request timed out after ${timeoutMs} ms`));
      }, timeoutMs);
      this.pending.push({ resolve, reject, timer });
      this.child.stdin.write(`${JSON.stringify(value)}\n`, 'utf8');
    });
  }

  close() {
    this.child.stdin.end();
    setTimeout(() => this.child.kill(), 1_000).unref();
  }
}

function startClients(options, legacyData, rustData) {
  const python = spawn(options.python, ['modules/backend_api/main.py'], {
    cwd: options.oracleRoot,
    windowsHide: true,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      KOI_USER_DATA_DIR: legacyData,
      KOI_APP_DIR: options.oracleRoot,
      KOI_APP_VERSION: '3.1.4',
      PYTHONIOENCODING: 'utf-8',
    },
  });
  const rust = spawn(options.rustDriver, ['--data-dir', rustData], {
    cwd: projectRoot,
    windowsHide: true,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  return {
    python: new LineClient(python, 'Python oracle'),
    rust: new LineClient(rust, 'Rust driver'),
  };
}

function pathValue(root, relative = '') {
  return path.join(root, ...relative.split('/').filter(Boolean));
}

function boundaryPayload(command, dataRoot) {
  const emptyNotices = pathValue(dataRoot, 'empty-notices');
  const noticeProcess = pathValue(dataRoot, 'notice-process');
  const noticeStart = pathValue(dataRoot, 'notice-start');
  const noticeClassify = pathValue(dataRoot, 'notice-classify');
  const noticeFailedPdf = pathValue(dataRoot, 'notice-failed-pdf');
  const filesystemFixture = pathValue(dataRoot, 'filesystem-fixture');
  const missing = pathValue(dataRoot, 'missing-target');
  const fixedAgentSession = 'oracle-agent-session';
  const fixedRetestSession = 'oracle-retest-session';
  const payloads = {
    'config.set_dark_mode': { dark_mode: false },
    'fs.list_dir': { path: filesystemFixture },
    'fs.path_info': { path: missing },
    'weekly_report.config.set': {
      vulnerability_notice_dir: emptyNotices,
      event_notice_dir: emptyNotices,
      exclude_monday_next_notice: false,
    },
    'weekly_report.generate': {
      vulnerability_notice_dir: emptyNotices,
      event_notice_dir: emptyNotices,
      exclude_monday_next_notice: false,
      report_date: '2026-09-14',
    },
    'data.templates.get': { id: '__missing__' },
    'data.templates.create': {},
    'data.templates.update': { id: '__missing__' },
    'data.templates.delete': { id: '__missing__' },
    'data.templates.import': { file_path: missing },
    'data.templates.export': { id: '__missing__', file_path: pathValue(dataRoot, 'missing.json') },
    'info.config.set': {},
    'info.export_text': { content: 'oracle-boundary', output_path: pathValue(dataRoot, 'export.txt') },
    'fs.open_path': { path: missing },
    'fs.open_url': { url: 'file:///forbidden' },
    'doc.convert.run': { input_path: missing, conversion_type: 'word_to_pdf' },
    'doc.notice.process': { target_path: noticeProcess, auto_group: false },
    'doc.notice.process.start': { target_path: noticeStart, auto_group: false },
    'doc.notice.process.status': { task_id: '__missing__' },
    'doc.notice.counters.save': { notice_number: '1', rectification_number: '1' },
    'doc.notice.classify': { target_path: noticeClassify },
    'doc.notice.convert_failed_pdf': { target_path: noticeFailedPdf, failed_files: [] },
    'doc.open_path': { path: missing },
    'doc.agent.message': { session_id: fixedAgentSession, message: 'oracle boundary' },
    'doc.agent.status': { session_id: fixedAgentSession },
    'doc.agent.stop': { session_id: fixedAgentSession },
    'doc.agent.approval.respond': { approval_id: '__missing__', decision: 'reject' },
    'doc.agent.auto_approval.set': { session_id: fixedAgentSession, enabled: false },
    'doc.agent.auto_approval.status': { session_id: fixedAgentSession },
    'doc.agent.operation.status': { session_id: fixedAgentSession, operation_id: '__missing__' },
    'doc.agent.operation.stop': { session_id: fixedAgentSession, operation_id: '__missing__' },
    'doc.agent.tools': { session_id: fixedAgentSession },
    'doc.retest.run': { target_dir: emptyNotices, generate_reports: false },
    'doc.retest.list_files': { target_dir: emptyNotices },
    'doc.retest.run_one': { source_file: missing, use_ai: false },
    'doc.retest.run_one.start': { source_file: missing, use_ai: false },
    'doc.retest.run_one.status': { task_id: '__missing__' },
    'doc.retest.run_one.stop': { task_id: '__missing__' },
    'doc.retest.confirmation.respond': { confirmation_id: '__missing__', decision: 'reject' },
    'doc.retest.agent.start': { session_id: fixedRetestSession, target_dir: emptyNotices, message: 'oracle boundary' },
    'doc.retest.agent.message': { session_id: fixedRetestSession, message: 'oracle boundary' },
    'doc.retest.agent.status': { session_id: fixedRetestSession },
    'doc.retest.agent.stop': { session_id: fixedRetestSession },
    'doc.retest.agent_chat': { session_id: fixedRetestSession, message: 'oracle boundary' },
    'doc.retest.session.compact': { session_id: fixedRetestSession },
    'doc.retest.ai_config.set': {},
    'doc.retest.ai_config.test': {},
    'doc.retest.ai_config.key_status': {},
    'doc.retest.tools.install.status': { task_id: '__missing__' },
    'doc.retest.generate_reports_with_screenshot': { target_dir: emptyNotices, source_files: [] },
    'doc.retest.open_output': { target_dir: missing },
  };
  return payloads[command] ?? {};
}

const SKIPPED_BOUNDARIES = new Map([
  ['doc.retest.tools.install', 'legacy command downloads and executes unpinned Python-based tools; covered as a reviewed security exception'],
]);

function normalizeString(value, roots) {
  let output = value.replace(/\\\\\?\\/g, '');
  for (const [root, token] of roots) {
    const variants = [root, root.replaceAll('\\', '/'), `\\\\?\\${root}`];
    for (const variant of variants) {
      output = output.split(variant).join(token);
    }
  }
  output = output
    .replace(/\b[0-9a-f]{32}\b/gi, '<ID>')
    .replace(/\bnotice-\d+-\d+\b/gi, '<ID>')
    .replace(/\bagent-runtime-\d+-[0-9a-f]+\b/gi, '<ID>')
    .replace(/\b(?:run|step)-[0-9a-f]+\b/gi, '<ID>')
    .replace(/\btrace-\d+-\d+\b/gi, '<ID>')
    .replace(/\b(agent:[^:\s]+:turn:)\d+:[0-9a-f]+\b/gi, '$1<ID>')
    .replace(/\btrace-[0-9a-f]{10}\b/gi, '<TRACE_ID>')
    .replace(/\b20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b/g, '<TIMESTAMP>')
    .replace(/\b\d{2}:\d{2}:\d{2}\b/g, '<TIMESTAMP>')
    .replace(/(ws:\/\/127\.0\.0\.1:)\d+/g, '$1<PORT>');
  return output;
}

function normalize(value, roots, key = '') {
  if (Array.isArray(value)) return value.map((item) => normalize(item, roots));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right, 'en'))
      .map(([childKey, childValue]) => [childKey, normalize(childValue, roots, childKey)]));
  }
  if (typeof value === 'string') {
    if (['last_updated', 'updated_at', 'created_at', 'finished_at'].includes(key) && value) return '<TIMESTAMP>';
    if (key === 'token' && value) return '<TOKEN>';
    if (key === 'ws_url') return normalizeString(value, roots).replace(/token=[^&]+/i, 'token=<TOKEN>');
    if (key === 'name' && /^(?:.+\s+\()?([A-Za-z]):\)?$/.test(value)) {
      return `<DRIVE_LABEL:${RegExp.$1.toUpperCase()}:>`;
    }
    return normalizeString(value, roots);
  }
  if (key === 'port' && typeof value === 'number') return '<PORT>';
  if ([
    'modified',
    'created_at',
    'updated_at',
    'finished_at',
    'started_at',
    'resolved_at',
    'timestamp',
  ].includes(key) && typeof value === 'number') return '<TIMESTAMP>';
  return value;
}

function responseComparable(command, response) {
  const clone = structuredClone(response);
  if (command === 'app.version' && clone?.data?.version) clone.data.version = '<VERSION>';
  return clone;
}

function assertNoSecrets(value, key = '') {
  if (Array.isArray(value)) {
    value.forEach((item) => assertNoSecrets(item, key));
    return;
  }
  if (value && typeof value === 'object') {
    Object.entries(value).forEach(([childKey, childValue]) => assertNoSecrets(childValue, childKey));
    return;
  }
  const normalizedKey = key.toLowerCase().replaceAll(/[^a-z0-9]/g, '');
  const secretKey = normalizedKey === 'apikey'
    || normalizedKey.endsWith('cookie')
    || normalizedKey === 'authorization'
    || normalizedKey === 'authtoken'
    || normalizedKey === 'password'
    || normalizedKey === 'secret';
  if (secretKey && typeof value === 'string' && value && value !== '<TOKEN>' && !value.includes('***')) {
    throw new Error(`Captured oracle output contains a non-empty secret field: ${key}`);
  }
  const text = typeof value === 'string' ? value.toLowerCase() : String(value ?? '').toLowerCase();
  for (const marker of ['authorization: bearer ', 'x-quake-token', 'x-threatbook-key', 'cookie:']) {
    if (text.includes(marker)) throw new Error(`Captured oracle output contains forbidden secret marker: ${marker}`);
  }
  const hostHome = os.homedir().toLowerCase().replaceAll('\\', '/');
  const normalizedText = text.replaceAll('\\', '/');
  if (hostHome && normalizedText.includes(hostHome)) {
    throw new Error('Captured oracle output contains the host home directory');
  }
  const username = String(process.env.USERNAME || process.env.USER || '').trim().toLowerCase();
  if (username && username.length >= 3 && normalizedText.includes(`users/${username}`)) {
    throw new Error('Captured oracle output contains the host username');
  }
}

const options = parseArgs(process.argv.slice(2));
requireCleanBaseline(options.oracleRoot);
if (!fs.statSync(options.rustDriver, { throwIfNoEntry: false })?.isFile()) {
  throw new Error(`Rust driver is missing: ${options.rustDriver}\nRun cargo build --example backend_protocol_driver first.`);
}
const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'koi-python-oracle-'));
const legacyData = path.join(tempRoot, 'python-data');
const rustData = path.join(tempRoot, 'rust-data');
prepareLegacyData(options.oracleRoot, legacyData);
for (const directory of [
  rustData,
  path.join(legacyData, 'empty-notices'),
  path.join(rustData, 'empty-notices'),
  path.join(legacyData, 'filesystem-fixture'),
  path.join(rustData, 'filesystem-fixture'),
  path.join(legacyData, 'notice-process'),
  path.join(rustData, 'notice-process'),
  path.join(legacyData, 'notice-start'),
  path.join(rustData, 'notice-start'),
  path.join(legacyData, 'notice-classify'),
  path.join(rustData, 'notice-classify'),
  path.join(legacyData, 'notice-failed-pdf'),
  path.join(rustData, 'notice-failed-pdf'),
]) {
  fs.mkdirSync(directory, { recursive: true });
}
for (const dataRoot of [legacyData, rustData]) {
  fs.writeFileSync(path.join(dataRoot, 'filesystem-fixture', 'sample.txt'), 'oracle fixture\n', 'utf8');
}

const clients = startClients(options, legacyData, rustData);
const roots = [
  [legacyData, '<DATA>'],
  [rustData, '<DATA>'],
  [options.oracleRoot, '<ORACLE_ROOT>'],
  [projectRoot, '<PROJECT_ROOT>'],
  [tempRoot, '<TEMP_ROOT>'],
  [os.homedir(), '<HOME>'],
];
const cases = [];
try {
  for (const { name } of contract.commands) {
    if (SKIPPED_BOUNDARIES.has(name)) {
      cases.push({
        command: name,
        scenario: 'safe-boundary',
        status: 'security-exception',
        reason: SKIPPED_BOUNDARIES.get(name),
      });
      continue;
    }
    const pythonPayload = boundaryPayload(name, legacyData);
    const rustPayload = boundaryPayload(name, rustData);
    process.stderr.write(`capture ${name}\n`);
    let pythonRaw;
    let rustRaw;
    try {
      [pythonRaw, rustRaw] = await Promise.all([
        clients.python.request({ command: name, payload: pythonPayload }, 30_000),
        clients.rust.request({ command: name, payload: rustPayload }, 30_000),
      ]);
    } catch (error) {
      throw new Error(`Boundary capture failed for ${name}: ${error.message}`);
    }
    const python = normalize(responseComparable(name, pythonRaw), roots);
    const rust = normalize(responseComparable(name, rustRaw), roots);
    const equal = JSON.stringify(python) === JSON.stringify(rust);
    const record = {
      command: name,
      scenario: 'safe-boundary',
      payload: normalize(rustPayload, roots),
      python,
      rust,
      equal,
    };
    assertNoSecrets(record);
    cases.push(record);
  }
} finally {
  clients.python.close();
  clients.rust.close();
}

const sourceManifest = legacySourceManifest(options.oracleRoot);
const currentRustSource = rustSourceManifest();
const output = {
  format: 'koi-python-oracle-command-boundaries-v1',
  baseline: {
    version: '3.1.4',
    revision: BASELINE_REVISION,
    sourceManifest: {
      fileCount: sourceManifest.fileCount,
      sha256: sourceManifest.sha256,
    },
  },
  rustSourceManifest: currentRustSource,
  normalization: [
    'isolated temporary roots',
    'application version',
    'timestamps',
    'generated identifiers',
    'loopback event-stream port and token',
  ],
  commandCount: contract.commands.length,
  capturedCount: cases.filter((item) => item.python).length,
  exactMatchCount: cases.filter((item) => item.equal).length,
  securityExceptionCount: cases.filter((item) => item.status === 'security-exception').length,
  cases,
};
assertNoSecrets(output);
fs.mkdirSync(path.dirname(options.output), { recursive: true });
const temporary = `${options.output}.${process.pid}.tmp`;
fs.writeFileSync(temporary, `${JSON.stringify(output, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
if (fs.existsSync(options.output) && !fs.lstatSync(options.output).isFile()) {
  throw new Error(`Oracle output is not a regular file: ${options.output}`);
}
fs.rmSync(options.output, { force: true });
fs.renameSync(temporary, options.output);
console.log(
  `Captured ${output.capturedCount}/${output.commandCount} safe command boundaries; `
  + `${output.exactMatchCount} normalized responses are exact and ${output.securityExceptionCount} are reviewed security exceptions.`,
);
console.log(`Output: ${options.output}`);
