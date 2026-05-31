import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { spawn } from 'node:child_process';
import path from 'node:path';

function koiBackendPreviewPlugin(): Plugin {
  return {
    name: 'koi-backend-preview',
    configureServer(server) {
      server.middlewares.use('/__koi_backend', (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405;
          res.end('Method Not Allowed');
          return;
        }

        const chunks: Buffer[] = [];
        req.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
        req.on('end', () => {
          const rootDir = path.resolve(__dirname, '..');
          const bridgePath = path.join(rootDir, 'modules', 'backend_api', 'main.py');
          const child = spawn('python', [bridgePath], {
            cwd: rootDir,
            stdio: ['pipe', 'pipe', 'pipe'],
          });
          const stdout: Buffer[] = [];
          const stderr: Buffer[] = [];

          child.stdout.on('data', (chunk) => stdout.push(Buffer.from(chunk)));
          child.stderr.on('data', (chunk) => stderr.push(Buffer.from(chunk)));
          child.on('error', (error) => {
            res.statusCode = 500;
            res.end(error.message);
          });
          child.on('close', () => {
            const body = Buffer.concat(stdout).toString('utf8');
            const errorBody = Buffer.concat(stderr).toString('utf8');
            res.setHeader('Content-Type', 'application/json; charset=utf-8');
            res.end(body || JSON.stringify({ ok: false, data: null, error: errorBody || '后端无响应' }));
          });
          child.stdin.end(Buffer.concat(chunks));
        });
      });
    },
  };
}

export default defineConfig({
  root: __dirname,
  plugins: [react(), koiBackendPreviewPlugin()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  envPrefix: ['VITE_', 'TAURI_'],
  build: {
    target: process.env.TAURI_ENV_PLATFORM === 'windows' ? 'chrome105' : 'safari13',
    minify: !process.env.TAURI_ENV_DEBUG ? 'esbuild' : false,
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
  },
});
