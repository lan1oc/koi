import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

function vendorChunk(id: string) {
  if (!id.includes('node_modules')) {
    return undefined;
  }
  if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) {
    return 'vendor-react';
  }
  if (/[\\/]node_modules[\\/](html2canvas|css-line-break|text-segmentation|base64-arraybuffer|utrie)[\\/]/.test(id)) {
    return 'vendor-capture';
  }
  if (
    /[\\/]node_modules[\\/](@types[\\/]hast|@types[\\/]mdast|@types[\\/]unist|react-markdown|remark-|rehype-|unified|micromark|mdast-|hast-|unist-|vfile|bail|ccount|character-|comma-separated|decode-named|dequal|devlop|escape-string-regexp|estree-|html-url-attributes|inline-style-parser|is-|longest-streak|markdown-table|parse-entities|property-information|space-separated|style-|trim-lines|trough|zwitch)[\\/]/.test(id)
  ) {
    return 'vendor-markdown';
  }
  return undefined;
}

export default defineConfig({
  root: __dirname,
  plugins: [react()],
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
    rollupOptions: {
      output: {
        manualChunks: vendorChunk,
      },
    },
  },
});
