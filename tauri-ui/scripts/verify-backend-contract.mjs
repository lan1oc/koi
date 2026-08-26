import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');

const frontendCommandFiles = [
  'tauri-ui/src/components/common/ProjectFileDialog.tsx',
  'tauri-ui/src/lib/config.ts',
  'tauri-ui/src/lib/open-path.ts',
  'tauri-ui/src/modules/information-gathering/module.tsx',
  'tauri-ui/src/modules/data-processing/module.tsx',
  'tauri-ui/src/modules/document-processing/module.tsx',
  'tauri-ui/src/modules/ai-testing/ModelToolsPage.tsx',
  'tauri-ui/src/modules/ai-testing/TestWorkbenchPage.tsx',
  'tauri-ui/src/modules/emergency-help/module.tsx',
];

// The production registry is the sole backend command source. Historical
// Python oracle modules are intentionally excluded from release validation.
const backendCommandFiles = [];

let rustRegistryFile = 'tauri-ui/src-tauri/src/backend/registry.rs';

const mainBackendCommands = [
  'app.version',
  'config.load',
  'config.set_dark_mode',
  'weekly_report.config.get',
  'weekly_report.config.set',
  'weekly_report.generate',
];

const dynamicFrontendCommands = [
  'data.templates.create',
  'data.templates.update',
  'info.enterprise.tyc.query',
  'info.enterprise.aiqicha.query',
  'info.asset.unified.query',
  'info.asset.fofa.query',
  'info.asset.hunter.query',
  'info.asset.quake.query',
  'info.threatbook.ip',
  'info.threatbook.ip.batch',
  'info.threatbook.dns',
  'info.threatbook.file_report',
  'info.threatbook.file_multiengines',
  'info.threatbook.file_upload',
];

const backendCompatibilityCommands = [
  'app.version',
  'data.template.create',
  'doc.open_path',
  'doc.retest.run',
  'doc.retest.open_output',
  'fs.path_info',
];

const contract = JSON.parse(readRelative('contracts/backend-commands.json'));
if (contract.schemaVersion !== 1 || !Array.isArray(contract.commands)) {
  console.error('Invalid contracts/backend-commands.json schema.');
  process.exit(1);
}
if (Object.prototype.hasOwnProperty.call(contract, 'rustHandlerSource')
  && typeof contract.rustHandlerSource !== 'string') {
  console.error('Invalid rustHandlerSource metadata; expected a repository-relative string.');
  process.exit(1);
}
if (typeof contract.rustHandlerSource === 'string' && contract.rustHandlerSource.trim()) {
  rustRegistryFile = contract.rustHandlerSource.trim();
}
if (path.isAbsolute(rustRegistryFile) || rustRegistryFile.split(/[\\/]+/).includes('..')) {
  console.error('Invalid rustHandlerSource path; it must stay inside the repository.');
  process.exit(1);
}
const validOwners = new Set(['rust']);
const validChannels = new Set(['rust_concurrent']);
const invalidContractEntries = contract.commands.filter((item) => {
  if (!item || typeof item.name !== 'string' || !item.name.trim()) return true;
  if (!validOwners.has(item.owner) || !validChannels.has(item.channel)) return true;
  if (!Number.isInteger(item.timeoutMs) || item.timeoutMs <= 0) return true;
  return item.owner !== 'rust' || item.channel !== 'rust_concurrent';
});
if (invalidContractEntries.length) {
  console.error('Command contract contains invalid owner/channel/timeout metadata:');
  for (const item of invalidContractEntries) console.error(`- ${item?.name || '<unnamed>'}`);
  process.exit(1);
}
const contractCommands = new Set(contract.commands.map((item) => item.name));
if (contractCommands.size !== contract.commands.length) {
  console.error('Command contract contains duplicate names.');
  process.exit(1);
}

function readRelative(relativePath) {
  return fs.readFileSync(path.join(projectRoot, relativePath), 'utf8');
}

function extractLiteralCallBackendCommands(source) {
  const commands = new Set();
  const pattern = /callBackend(?:<[^>]+>)?\(\s*(['"`])([^'"`$]+)\1/g;
  for (const match of source.matchAll(pattern)) {
    commands.add(match[2]);
  }
  return commands;
}

function extractBackendRegisteredCommands(source) {
  const commands = new Set();
  const setBodyPattern = /[A-Z_]+_COMMANDS\s*=\s*\{([\s\S]*?)\n\}/g;
  for (const setMatch of source.matchAll(setBodyPattern)) {
    const body = setMatch[1];
    for (const itemMatch of body.matchAll(/(['"])([^'"]+)\1/g)) {
      commands.add(itemMatch[2]);
    }
  }
  return commands;
}

function extractRustHandlerCommands(source) {
  const begin = source.indexOf('// CONTRACT_RUST_HANDLERS_BEGIN');
  const end = source.indexOf('// CONTRACT_RUST_HANDLERS_END');
  if (begin < 0 || end <= begin) {
    throw new Error(`Rust handler inventory markers missing from ${rustRegistryFile}`);
  }
  const inventory = source.slice(begin, end);
  return new Set([...inventory.matchAll(/\bname:\s*"([^"]+)"/g)].map((match) => match[1]));
}

const frontendCommands = new Set(dynamicFrontendCommands);
for (const relativePath of frontendCommandFiles) {
  const source = readRelative(relativePath);
  for (const command of extractLiteralCallBackendCommands(source)) {
    frontendCommands.add(command);
  }
}

const backendCommands = new Set(mainBackendCommands);
for (const relativePath of backendCommandFiles) {
  const source = readRelative(relativePath);
  for (const command of extractBackendRegisteredCommands(source)) {
    backendCommands.add(command);
  }
}
const rustHandlerCommands = extractRustHandlerCommands(readRelative(rustRegistryFile));
for (const command of rustHandlerCommands) backendCommands.add(command);

const missing = [...frontendCommands].filter((command) => !backendCommands.has(command)).sort();
const unusedBackend = [...backendCommands]
  .filter((command) => !frontendCommands.has(command) && !backendCompatibilityCommands.includes(command))
  .sort();

console.log(`Frontend backend commands: ${frontendCommands.size}`);
console.log(`Registered backend commands: ${backendCommands.size}`);
console.log(`Contract commands: ${contractCommands.size}`);
console.log(`Rust handler commands: ${rustHandlerCommands.size}`);

if (missing.length) {
  console.error('Missing backend registrations for frontend commands:');
  for (const command of missing) {
    console.error(`- ${command}`);
  }
  process.exit(1);
}

const missingContractRegistrations = [...contractCommands]
  .filter((command) => !backendCommands.has(command))
  .sort();
const uncontractedBackendCommands = [...backendCommands]
  .filter((command) => !contractCommands.has(command))
  .sort();
const uncontractedFrontendCommands = [...frontendCommands]
  .filter((command) => !contractCommands.has(command))
  .sort();
if (missingContractRegistrations.length || uncontractedBackendCommands.length || uncontractedFrontendCommands.length) {
  console.error('Backend command contract does not match source registrations:');
  for (const command of missingContractRegistrations) console.error(`- missing source registration: ${command}`);
  for (const command of uncontractedBackendCommands) console.error(`- missing contract entry: ${command}`);
  for (const command of uncontractedFrontendCommands) console.error(`- frontend command missing contract entry: ${command}`);
  process.exit(1);
}

const contractRustCommands = new Set(
  contract.commands.filter((item) => item.owner === 'rust').map((item) => item.name),
);
const missingRustHandlers = [...rustHandlerCommands]
  .filter((command) => !contractCommands.has(command))
  .sort();
const staleRustOwners = [...contractRustCommands]
  .filter((command) => !rustHandlerCommands.has(command))
  .sort();
const pythonOwnersForRustHandlers = [...rustHandlerCommands]
  .filter((command) => contract.commands.find((item) => item.name === command)?.owner === 'python')
  .sort();
const pythonOwners = contract.commands
  .filter((item) => item.owner === 'python')
  .map((item) => item.name)
  .sort();
if (missingRustHandlers.length || staleRustOwners.length) {
  console.error('Rust handler inventory and contracts/backend-commands.json disagree.');
  for (const command of missingRustHandlers) console.error(`- Rust handler missing contract entry: ${command}`);
  for (const command of staleRustOwners) console.error(`- Rust owner missing handler inventory entry: ${command}`);
  process.exit(1);
}

const strictRust = process.argv.includes('--strict-rust')
  || ['1', 'true', 'yes'].includes(String(process.env.KOI_STRICT_RUST || '').trim().toLowerCase());
if (strictRust && pythonOwners.length) {
  console.error('Strict Rust mode requires 97/97 Rust command owners:');
  for (const command of pythonOwners) console.error(`- ${command}`);
  process.exit(1);
}
if (pythonOwnersForRustHandlers.length) {
  console.error('Production registry contains a non-Rust owner for a Rust handler.');
  process.exit(1);
}

console.log('All frontend backend commands are registered.');

if (unusedBackend.length) {
  console.log('Backend commands not currently called directly by the Tauri frontend and not marked as compatibility commands:');
  for (const command of unusedBackend) {
    console.log(`- ${command}`);
  }
}
