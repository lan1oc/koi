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

const backendCommandFiles = [
  'modules/backend_api/commands/filesystem.py',
  'modules/backend_api/commands/information_gathering.py',
  'modules/backend_api/commands/data_processing.py',
  'modules/backend_api/commands/document_processing.py',
  'modules/AI_Testing/backend_commands.py',
];

const mainBackendCommands = ['app.version', 'config.load', 'config.set_dark_mode', 'weekly_report.generate'];

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

const missing = [...frontendCommands].filter((command) => !backendCommands.has(command)).sort();
const unusedBackend = [...backendCommands]
  .filter((command) => !frontendCommands.has(command) && !backendCompatibilityCommands.includes(command))
  .sort();

console.log(`Frontend backend commands: ${frontendCommands.size}`);
console.log(`Registered backend commands: ${backendCommands.size}`);

if (missing.length) {
  console.error('Missing backend registrations for frontend commands:');
  for (const command of missing) {
    console.error(`- ${command}`);
  }
  process.exit(1);
}

console.log('All frontend backend commands are registered.');

if (unusedBackend.length) {
  console.log('Backend commands not currently called directly by the Tauri frontend and not marked as compatibility commands:');
  for (const command of unusedBackend) {
    console.log(`- ${command}`);
  }
}
