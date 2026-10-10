import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyArchiveRuntimeProvenance, verifyLockedRuntime, verifyProbeRuntime } from './locked-runtime.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
verifyProbeRuntime({ lockPath: path.join(root, 'probe-runtime.lock.json'), runtimeDir: path.join(root, 'probe-runtime') });
verifyLockedRuntime({ lockPath: path.join(root, 'pdfium-runtime.lock.json'), runtimeDir: path.join(root, 'pdfium-runtime'), expectedFormat: 'koi-pdfium-runtime-v1' });
const archiveRoot = path.join(root, 'archive-runtime');
const archiveLock = verifyLockedRuntime({ lockPath: path.join(root, 'archive-runtime.lock.json'), runtimeDir: archiveRoot, expectedFormat: 'koi-archive-runtime-v3' });
verifyArchiveRuntimeProvenance(archiveLock, archiveRoot);
for (const relative of ['enterprise_classification.db', 'modules/data_processing/templates', 'tauri-ui/src-tauri/resources/report-template-placeholder']) {
  if (!fs.existsSync(path.join(root, relative))) throw new Error(`Required CI resource is missing: ${relative}`);
}
console.log('CI runtime files and signed archive provenance verified.');
