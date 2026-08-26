import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Compatibility entry point for old local wrappers. The backend is compiled
// into the Rust/Tauri executable; this script must never invoke Python or a
// PyInstaller sidecar.
const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptsDir, '..', '..');
const cargoTomlPath = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'Cargo.toml');
const contractPath = path.join(projectRoot, 'contracts', 'backend-commands.json');
const defaultRustRegistryPath = path.join(projectRoot, 'tauri-ui', 'src-tauri', 'src', 'backend', 'registry.rs');

function readVersion() {
  const source = fs.readFileSync(cargoTomlPath, 'utf8');
  const match = source.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) {
    throw new Error(`Unable to read Rust application version from ${cargoTomlPath}`);
  }
  return match[1];
}

function validateContract() {
  if (!fs.existsSync(contractPath)) {
    throw new Error(`Missing backend contract: ${contractPath}`);
  }
  const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
  if (contract.schemaVersion !== 1 || !Array.isArray(contract.commands)) {
    throw new Error('Invalid backend command contract.');
  }
  const names = new Set();
const validOwners = new Set(['rust']);
const validChannels = new Set(['rust_concurrent']);
  for (const command of contract.commands) {
    if (!command || typeof command.name !== 'string' || !command.name.trim() || names.has(command.name)) {
      throw new Error('Backend command contract contains an invalid or duplicate command.');
    }
    if (!validOwners.has(command.owner) || !validChannels.has(command.channel)
      || !Number.isInteger(command.timeoutMs) || command.timeoutMs <= 0
      || command.owner !== 'rust'
      || command.channel !== 'rust_concurrent') {
      throw new Error(`Backend command contract contains invalid metadata for ${command.name}.`);
    }
    names.add(command.name);
  }
  if (Object.prototype.hasOwnProperty.call(contract, 'rustHandlerSource')
    && typeof contract.rustHandlerSource !== 'string') {
    throw new Error('Invalid rustHandlerSource metadata; expected a repository-relative string.');
  }
  const rustRegistryPath = typeof contract.rustHandlerSource === 'string' && contract.rustHandlerSource.trim()
    ? path.join(projectRoot, contract.rustHandlerSource.trim())
    : defaultRustRegistryPath;
  if (path.isAbsolute(contract.rustHandlerSource || '') || String(contract.rustHandlerSource || '').split(/[\\/]+/).includes('..')) {
    throw new Error('Invalid rustHandlerSource path; it must stay inside the repository.');
  }
  if (!fs.existsSync(rustRegistryPath)) {
    throw new Error(`Missing Rust handler inventory: ${rustRegistryPath}`);
  }
  const registrySource = fs.readFileSync(rustRegistryPath, 'utf8');
  const begin = registrySource.indexOf('// CONTRACT_RUST_HANDLERS_BEGIN');
  const end = registrySource.indexOf('// CONTRACT_RUST_HANDLERS_END');
  if (begin < 0 || end <= begin) {
    throw new Error(`Rust handler inventory markers missing from ${rustRegistryPath}`);
  }
  const rustHandlers = new Set(
    [...registrySource.slice(begin, end).matchAll(/\bname:\s*"([^"]+)"/g)].map((match) => match[1]),
  );
  const pythonOwnersForRustHandlers = contract.commands.filter(
    (item) => rustHandlers.has(item.name) && item.owner === 'python',
  );
  const rustOwnersWithoutHandlers = contract.commands.filter(
    (item) => item.owner === 'rust' && !rustHandlers.has(item.name),
  );
  if (rustOwnersWithoutHandlers.length) {
    throw new Error(
      `Backend contract declares Rust owner without a Rust handler: ${rustOwnersWithoutHandlers
        .map((item) => item.name).join(', ')}`,
    );
  }
  return {
    count: names.size,
    pythonOwners: contract.commands.filter((item) => item.owner === 'python').length,
    rustHandlers: rustHandlers.size,
    pythonOwnersForRustHandlers,
  };
}

function validatePythonBusinessSourceRemoved() {
  const modulesRoot = path.join(projectRoot, 'modules');
  const forbidden = [];
  const pending = fs.existsSync(modulesRoot) ? [modulesRoot] : [];
  while (pending.length) {
    const directory = pending.pop();
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      const lower = entry.name.toLowerCase();
      if (entry.isDirectory()) {
        if (lower === '__pycache__') forbidden.push(fullPath);
        else pending.push(fullPath);
      } else if (lower.endsWith('.py') || lower.endsWith('.pyc') || lower.endsWith('.pyo')) {
        forbidden.push(fullPath);
      }
    }
  }
  if (forbidden.length) {
    throw new Error(`KOI 4.0.0 production source contains legacy Python business artifacts:\n${forbidden.join('\n')}`);
  }
}

const version = readVersion();
const inventory = validateContract();
const strictRelease = process.env.KOI_RELEASE_STRICT !== '0';
if (strictRelease) validatePythonBusinessSourceRemoved();
if (strictRelease && inventory.pythonOwners > 0) {
  throw new Error(
    `Production release requires 97/97 Rust command owners; ${inventory.pythonOwners} Python owner(s) remain in ${contractPath}. ` +
      'Use a development/differential build with KOI_RELEASE_STRICT=0 only while migration validation is in progress.',
  );
}

console.log(`Rust backend preflight passed for KOI ${version}: ${inventory.count} command contract entries, ${inventory.rustHandlers} Rust handlers.`);
console.log('The backend is built by the Tauri Rust target; no Python business backend or sidecar is packaged.');
